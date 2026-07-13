# warped-pinball-vector

[![CI](https://github.com/warped-pinball/python-library/actions/workflows/ci.yml/badge.svg)](https://github.com/warped-pinball/python-library/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/warped-pinball-vector.svg)](https://pypi.org/project/warped-pinball-vector/)

A Python client for **Warped Pinball "Vector"** boards — the WiFi board
(Raspberry Pi Pico 2W) that lives inside a pinball machine and exposes:

- an **HTTP API** on port 80 (scores, players, live game status, raw SRAM
  access, firmware updates, and more),
- **UDP discovery** on port 37020, so boards on your LAN can be found by name,
- a **USB serial tunnel** of the same HTTP routes, for when you're plugged in
  directly, and
- **HMAC-SHA256 challenge/response authentication** for mutating routes.

This library wraps all of that behind one `Machine` object, plus a `vector`
command-line tool.

Detailed guides live in [`docs/`](docs/README.md) — including
[reading & writing memory](docs/memory.md), [address maps](docs/address-maps.md),
and the [HTTP API reference](docs/http-api.md) for the raw
`/api/address/read` / `/api/address/write` routes.

## Install

Requires Python 3.9+.

```bash
pip install warped-pinball-vector
```

For USB serial support (adds [pyserial](https://pypi.org/project/pyserial/)):

```bash
pip install "warped-pinball-vector[usb]"
```

## Quickstart

```python
import warpedpinball

# Find every Vector board on the LAN (UDP broadcast, port 37020)
for m in warpedpinball.discover(timeout=5):
    print(m.name, m.ip)

# Connect by machine name (case-insensitive; unique prefix/substring works too)
machine = warpedpinball.connect("elvira", password="hunter2")

# ...or by IP address (skips discovery)
machine = warpedpinball.connect("192.168.1.42")

# ...or over USB (auto-picks the port when exactly one board is attached)
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
score resets, ...) are protected by an HMAC-SHA256 challenge/response scheme.
You just provide the password — the library fetches a single-use challenge and
signs each request automatically and invisibly. Give it the password any of
three ways:

```python
# 1. At connect time
m = warpedpinball.connect("elvira", password="hunter2")

# 2. On the machine object
m.password = "hunter2"

# 3. Via the environment
#    export VECTOR_PASSWORD=hunter2
```

Over **USB no password is needed at all** — the firmware trusts physical
access and skips HMAC for requests arriving on the serial port.

To validate credentials up front instead of failing on the first write:

```python
if not m.verify_password():
    raise SystemExit("wrong password")
```

If an authenticated call is attempted with no password configured, you get an
`AuthenticationRequiredError` before any network traffic; a rejected signature
raises `AuthenticationError`.

## API tour

### Common wrappers

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

# Logs (authenticated; 10 s server-side cooldown) — streamed as bytes
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

### The raw escape hatch

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
transmitted, so authenticated `call()`s work for any route.

### Watching a game live

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

## Named memory addresses

The firmware exposes raw SRAM reads/writes, but it can't store names. An
`AddressMap` maps friendly names to `(offset, length, encoding)` so mod makers
can ship an address map for a specific game ROM alongside their code:

```python
from warpedpinball import AddressMap

amap = AddressMap(active_config="elvira_l4")
amap.define("credits", 0x2134)                            # raw single byte
amap.define("player1_score", 0x0200, length=4, encoding="bcd")
amap.define("counter", 0x0300, length=2, encoding="le_uint")

m.addresses = amap
score = m.read("player1_score")   # decoded int
m.write("credits", 5)

# Raw offsets work too
m.read(0x2134)             # single byte -> int
m.read(0x0200, count=4)    # -> bytes
```

Built-in encodings are `"bcd"` (packed BCD, most-significant byte first — the
classic Williams/Bally score format), `"le_uint"`, and `"be_uint"`; you can
also pass a custom `(decode, encode)` callable pair. Reads and writes are
automatically chunked at 256 bytes per request (the firmware's limit).

### Sharing maps as JSON

```python
amap.save("elvira_l4.json")
amap = AddressMap.load("elvira_l4.json")   # warns if the machine's
                                           # active_config doesn't match
```

There's also a registry convention: drop a map at
`~/.warpedpinball/addressmaps/<active_config>.json` and `connect()` /
`connect_usb()` will auto-load it based on the machine's
`/api/game/active_config` value (only when that directory exists and you didn't
pass `addresses=` yourself). `AddressMap.load_registry("elvira_l4")` does the
lookup explicitly.

### Finding addresses

Use full-memory snapshots and diff them to hunt for the byte you care about:

```python
before = m.memory_snapshot()      # full SRAM dump (streamed)
# ... add a credit on the machine ...
after = m.memory_snapshot()

for offset, old, new in m.diff_snapshots(before, after):
    print(f"{offset:#06x}: {old} -> {new}")
```

## Being kind to the device

The board is a single-threaded microcontroller. The library helps you not
overwhelm it:

- **Requests are serialized per machine** — each `Machine` holds a lock, so
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

## Command line

Installing the package adds a `vector` command:

```
vector discover                          # find boards on the LAN
vector status elvira                     # show live game status
vector version elvira                    # show firmware version
vector leaders elvira                    # show the leaderboard
vector read elvira 0x2134 --count 4      # read SRAM bytes
vector write elvira 0x2134 5 --password hunter2
vector snapshot elvira -o dump.bin       # dump full SRAM
vector update elvira --password hunter2  # check for + apply a firmware update
```

Each machine-targeting subcommand accepts a machine name or IP address, plus
`--password/-p` (or `$VECTOR_PASSWORD`), `--timeout` for discovery, and
`--usb [PORT]` to go over USB serial instead of the network.

## Errors

All exceptions derive from `warpedpinball.VectorError`:

| Exception | Meaning |
| --- | --- |
| `TransportError` | Connection, timeout, or protocol-level failure |
| `MachineNotFoundError` | Discovery found no matching machine (`.seen_names` lists what it did see) |
| `AmbiguousMachineError` | A name matched more than one machine (`.candidates`) |
| `AuthenticationRequiredError` | Authenticated route called with no password set (raised before any traffic) |
| `AuthenticationError` | The device rejected the credentials (HTTP 401; `.reason`) |
| `RateLimitedError` | Too many outstanding auth challenges (HTTP 429 on the challenge route); retry after a short sleep |
| `CooldownError` | Route locked or in cooldown (HTTP 409/429; `.retry_after` hint in seconds) |
| `VectorServerError` | The device handler raised an error (HTTP 5xx; `.status`) |
| `UnsupportedFirmwareError` | The route doesn't exist on this firmware (HTTP 404); an update may be required |

## Development

```bash
git clone https://github.com/warped-pinball/python-library
cd python-library
pip install -e ".[dev,usb]"

pytest          # run the tests
ruff check .    # lint
```
