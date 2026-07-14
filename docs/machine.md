# Working with a machine

Everything in the library goes through one `Machine` object. This page covers
getting one, authenticating, the wrapper methods, live game events, and the
errors you might see.

## Connecting

```python
import warpedpinball

# Find every Vector board on the LAN (UDP broadcast, port 37020)
for m in warpedpinball.discover(timeout=5):
    print(m.name, m.ip)

# Connect by machine name (case-insensitive; a unique prefix or substring works)
machine = warpedpinball.connect("elvira", password="hunter2")

# Or by IP address, which skips discovery
machine = warpedpinball.connect("192.168.1.42")

# Or over USB (auto-picks the port when exactly one board is attached).
# Requires the usb extra:  pip install "warpedpinball[usb]"
machine = warpedpinball.connect_usb()

# Machines are context managers
with warpedpinball.connect("elvira") as m:
    print(m.version())
    print(m.game_status())
    print(m.leaderboard())
```

`connect()` raises `MachineNotFoundError` (listing the names it *did* see) or
`AmbiguousMachineError` (listing the candidates) when a name doesn't resolve to
exactly one board.

## Authentication

Read-only routes need no credentials. Mutating routes (reboot, writes, updates,
score resets, and so on) are protected by an HMAC-SHA256 challenge/response
scheme. You just provide the password; the library fetches a single-use
challenge and signs each request for you. Give it the password any of three
ways:

```python
# 1. At connect time
m = warpedpinball.connect("elvira", password="hunter2")

# 2. On the machine object
m.password = "hunter2"

# 3. Via the environment
#    export VECTOR_PASSWORD=hunter2
```

Over **USB no password is needed at all**: the firmware trusts physical
access and skips HMAC for requests arriving on the serial port.

> **Power the machine down before connecting or disconnecting USB.** When you
> plug a USB cable into the Vector board, the board is powered *through the USB
> port* instead of by the pinball machine's own power supply. To avoid
> back-powering the board while the machine is also energizing it, we recommend
> this sequence:
>
> - **Connecting:** turn the pinball machine **off**, plug in the USB cable,
>   then turn the machine **on**.
> - **Disconnecting:** turn the pinball machine **off**, then unplug the USB
>   cable.

To validate credentials up front instead of failing on the first write:

```python
if not m.verify_password():
    raise SystemExit("wrong password")
```

If an authenticated call is attempted with no password configured, you get an
`AuthenticationRequiredError` before any network traffic; a rejected signature
raises `AuthenticationError`.

## Common wrappers

```python
m.version()             # firmware version
m.game_status()         # live game status (scores, ball in play, ...)
m.leaderboard()         # high scores
m.players()             # player roster
m.update_player(id=3, initials="MAX", full_name="Max M.")   # authenticated

# Firmware updates, with streamed progress
info = m.check_for_updates()          # note: 10 s server-side cooldown
m.apply_update(progress=lambda rec: print(rec.get("percent"), rec.get("log")))
m.wait_until_reachable()              # poll /api/version until the board is back

# Logs (authenticated; 10 s server-side cooldown), streamed as bytes
for chunk in m.logs():
    print(chunk.decode(errors="replace"), end="")

# Power
m.reboot()        # reboot the Vector board
m.reboot_game()   # power-cycle the pinball machine itself
m.wait_until_reachable(timeout=120)
```

Other wrappers include `machine_id()`, `game_name()`, `active_config()`,
`wifi_status()`, `faults()`, `peers()`, `tournament()`,
`claimable_scores()` / `claim_score()`, `export_scores()` / `import_scores()`,
`reset_leaderboard()` / `reset_tournament()`, `date()` / `set_date()`, and the
adjustments family (`adjustments()`, `capture_adjustments()`,
`restore_adjustments()`, `name_adjustment()`).

## The raw escape hatch

Every firmware route is reachable even without a wrapper:

```python
m.call("/api/game/name")
m.call("/api/player/update",
       body={"id": 1, "initials": "ABC"},
       authenticated=True)

# Streaming variant: an iterator of raw byte chunks
for chunk in m.call_stream("/api/memory-snapshot"):
    ...
```

Bodies are serialized to JSON exactly once; the same string is signed and
transmitted, so authenticated `call()`s work for any route. The exact
request/response shapes for the memory routes are in the
[HTTP API reference](http-api.md).

## Watching a game live

`watch_game()` polls `/api/game/status` and yields `GameEvent`s
(`game_started`, `game_ended`, `ball_changed`, `score_changed`,
`status_changed`) forever:

```python
for event in m.watch_game(interval=1.0):   # interval is clamped to >= 0.5 s
    if event.type == "score_changed":
        print(f"player {event.player}: {event.old} -> {event.new}")
    elif event.type == "game_ended":
        print("game over", event.status)
```

## Being kind to the device

The board is a single-threaded microcontroller. The library helps you not
overwhelm it:

- **Requests are serialized per machine.** Each `Machine` holds a lock, so
  even multi-threaded programs send one request at a time (auth challenges are
  single-use, so this also keeps signing correct).
- **`watch_game()` enforces a minimum 0.5 s poll interval.**
- **Some routes have server-side cooldowns**: `/api/logs` 10 s,
  `/api/update/check` 10 s, `/api/adjustments/restore` 5 s. Hitting one raises
  `CooldownError` with a best-effort `retry_after` hint (seconds).
- **`RateLimitedError`** means the device had too many outstanding auth
  challenges (it holds ~10; expired ones are purged on each challenge request).
  The HTTP transport already retries this a few times internally; if it still
  surfaces, sleep briefly and retry.

```python
import time
from warpedpinball import CooldownError

try:
    m.check_for_updates()
except CooldownError as exc:
    time.sleep(exc.retry_after or 10)
    m.check_for_updates()
```

## Errors

All exceptions derive from `warpedpinball.VectorError`:

| Exception | Meaning |
| --- | --- |
| `TransportError` | Connection, timeout, or protocol-level failure (base class for the two below) |
| `DeviceUnreachableError` | Couldn't open a connection — board powered off, wrong address, or different subnet (`.target`, `.cause`) |
| `DeviceTimeoutError` | The board accepted the connection but didn't answer in time — busy or a flaky link (`.target`, `.timeout`, `.cause`) |
| `MachineNotFoundError` | Discovery found no matching machine (`.seen_names` lists what it did see) |
| `AmbiguousMachineError` | A name matched more than one machine (`.candidates`) |
| `AuthenticationRequiredError` | Authenticated route called with no password set (raised before any traffic) |
| `AuthenticationError` | The device rejected the credentials (HTTP 401; `.reason`) |
| `RateLimitedError` | Too many outstanding auth challenges (HTTP 429 on the challenge route); retry after a short sleep |
| `CooldownError` | Route locked or in cooldown (HTTP 409/429; `.retry_after` hint in seconds) |
| `VectorServerError` | The device handler raised an error (HTTP 5xx; `.status`) |
| `UnsupportedFirmwareError` | The route doesn't exist on this firmware (HTTP 404); an update may be required |

### Connection and timeout failures

A dropped WiFi link or a busy board is the most common thing you'll hit,
especially in a long-running poll loop. Those surface as `DeviceTimeoutError`
(the board didn't answer in time) or `DeviceUnreachableError` (couldn't connect
at all). Both are subclasses of `TransportError`, so a single `except
TransportError` still catches them — but catching them by name lets you react
differently, and their messages are already human-readable (no `urllib3`
`HTTPConnectionPool(...)` stack to wade through):

```python
from warpedpinball import DeviceTimeoutError, DeviceUnreachableError, TransportError

try:
    credits = m.read_bytes(0x2134, 1)
except DeviceUnreachableError:
    print("Machine is offline — is it powered on and on the network?")
except DeviceTimeoutError as exc:
    print(f"{exc}")            # e.g. "The machine at 192.168.1.42 did not respond within 10s"
```

The friendly message is the exception's `str()`; the original networking error
is kept on `.cause` if you need the low-level detail. These are raised so an
*uncaught* one prints a single short traceback instead of the full
requests/urllib3 chain.

In a polling loop, catch the transport error, report it, and keep going rather
than crashing on a single hiccup — see the
[ELVIRA hurry-up example](examples.md), which does exactly that.
