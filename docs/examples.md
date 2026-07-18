# Examples

Runnable scripts live in the [`examples/`](../examples) directory. Each is a
small, self-contained file you can copy, run, and tweak.

| Example | What it shows |
| --- | --- |
| [`discover_boards.py`](../examples/discover_boards.py) | Finding every board on the LAN (with an IP fallback for networks that block broadcast), then connecting to each to print its IP, name, firmware, and game state |
| [`elvira_hurryup.py`](../examples/elvira_hurryup.py) | Polling an SRAM byte in a loop and inferring game state to draw a live ELVIRA hurry-up display |
| [`update_all_boards.py`](../examples/update_all_boards.py) | Discovering every board, checking each for a firmware update, then (after one confirmation) updating them all concurrently with a live per-board progress bar |

## Discover boards on the network

[`examples/discover_boards.py`](../examples/discover_boards.py) lists every
Vector board on your LAN and prints what each one is.

```bash
python examples/discover_boards.py
```

`warpedpinball.discover()` broadcasts on the network and returns a
`DiscoveredMachine` (an `ip` and a `name`) for every board that answers — no
password and no per-board request, so it works even on a busy network. That
inventory prints first:

```python
boards = warpedpinball.discover(timeout=DISCOVERY_TIMEOUT)
for board in sorted(boards, key=lambda b: b.name.lower()):
    print(f"{board.name}  {board.ip}")
```

To show more than name and IP, the script then connects to each board by IP and
asks it a few read-only questions — `version()`, `game_name()`, and
`game_status()` — none of which need a password. Boards are contacted
concurrently with a `ThreadPoolExecutor` so one slow board doesn't hold up the
rest, and any board that fails to answer (mid-reboot, briefly unreachable) is
reported inline instead of aborting the whole run:

```python
try:
    with warpedpinball.connect(board.ip) as m:
        facts["firmware"] = _version_string(m.version())
        facts["game"] = _scalar(m.game_name())
        ...
except (TransportError, VectorError, OSError) as error:
    facts["error"] = str(error)
```

Connecting by IP (rather than by name) skips a second discovery round-trip —
you already have the address from the first broadcast. See
[connecting](machine.md) and the
[error handling](machine.md#connection-and-timeout-failures) reference for the
`TransportError` / `VectorError` families.

### When broadcast finds nothing

Some networks — phone hotspots, guest Wi-Fi, and some travel routers — isolate
clients and silently drop the broadcast traffic that `discover()` relies on. The
boards are still reachable by unicast HTTP; only the broadcast is blocked. So
when the broadcast turns up empty, the script asks for one board's IP and
enumerates the rest from that board's own peer table over HTTP — no broadcast
involved:

```python
found = warpedpinball.discover(timeout=DISCOVERY_TIMEOUT)
if not found:
    ip = input("Enter a board's IP address (blank to give up): ").strip()
    with warpedpinball.connect(ip) as m:
        peers = m.peers()   # GET /api/network/peers
```

`peers()` returns the board's view of every board it knows about, so one known
IP is enough to list the whole network. The script parses that payload
defensively (the exact JSON shape can vary by firmware) and always includes the
IP you supplied, so it works even if the peer table comes back empty.

## Update every board on the network

[`examples/update_all_boards.py`](../examples/update_all_boards.py) finds every
board, checks which ones have a firmware update available, asks you once, and
then updates them all at the same time — each board gets its own line with a
progress bar that fills as its update streams.

```bash
VECTOR_PASSWORD=secret python examples/update_all_boards.py
```

Checking is read-only and needs no password; each board's
`check_for_updates()` (`/api/update/check`, which has a 10 s server-side
cooldown) is called concurrently, and "the payload contains a `url`" is
treated as the signal that an update exists. Applying is the authenticated
part: `apply_update()` streams `{"log": ..., "percent": ...}` records as the
board downloads and flashes, and the script feeds each record's `percent`
into a shared display:

```python
def on_record(record):
    progress.update(name, percent=record.get("percent"), status=record.get("log"))

m.apply_update(url=url, progress=on_record)
```

The progress display is ~25 lines: a dict of `name -> (percent, status)`
behind a lock, redrawn in place by moving the cursor up N lines with
`"\x1b[NA"` and erasing each line with `"\x1b[2K"` before rewriting it. Any
thread that reports progress repaints the whole table, so all bars stay live
even though the updates run in parallel. When stdout isn't a terminal the
cursor moves are skipped and each repaint just prints fresh lines.

A board that fails mid-update shows `FAILED: ...` on its own line instead of
killing the others, and boards reboot themselves to finish applying — use
`wait_until_reachable()` if you want to block until they're back. See
[updates](machine.md) for `check_for_updates()` / `apply_update()` details.

## ELVIRA hurry-up display

[`examples/elvira_hurryup.py`](../examples/elvira_hurryup.py) watches an
*Elvira* pinball machine and spells out **ELVIRA** in your terminal, lighting
one letter red each time the player makes the hurry-up shot.

```bash
python examples/elvira_hurryup.py
```

The interesting part: the letter count at `0x076D` is truthful *except* while a
hurry-up is running, when the machine preemptively writes the 4 the player will
drop to if they miss — even though all six letters are lit and up for grabs.
The tell is the **timer** (`0x0175`) — it only moves while a hurry-up is live.
It arms at 20, sits there through a short intro, then ticks down once a second;
when the shot is made it freezes, and when it's missed it reaches 0. So the
script polls both bytes a few times a second and uses the timer's *motion* to
decide what to show:

```python
grace = INTRO_GRACE if timer == 20 else FROZEN_AFTER
hurryup_live = timer > 0 and (now - last_change) < grace

lit = len(WORD) if hurryup_live else letters
```

While the timer is moving, all six letters light (matching the machine) and
the countdown shows. Once the timer stops for more than `FROZEN_AFTER` (1.5 s —
comfortably longer than the 1 s tick, so a normal countdown never looks
"stopped"), whatever the machine now reports is shown faithfully. `INTRO_GRACE`
(3.5 s) allows the extra stillness at 20 while the intro plays. Because the
letters byte is re-read whenever no hurry-up is live, starting the script
mid-game shows the correct letters immediately.

One startup detail: the first read is treated as a baseline, not a change —
otherwise a stale timer value left in memory would look "live" for the first
second and briefly hide the true letters.

Two more small things worth copying:

**Redraw with an erase-to-end-of-line.** `"\r"` only moves the cursor back to
the start of the line — it doesn't clear what's there, so when the timer
disappears the old digits would linger. Ending each frame with `"\033[K"` wipes
the rest of the line:

```python
print("\r" + text + "\033[K", end="", flush=True)
```

**A long-running loop will hit a network hiccup.** A dropped packet or a busy
board raises a `TransportError` (with a clean, one-line message — no `urllib3`
stack). Catch it, show it, and keep going instead of crashing:

```python
try:
    timer = machine.read(0x0175)
except TransportError as error:
    draw(str(error))
    time.sleep(READ_PERIOD)
    continue
```

`read(offset)` returns the byte at that address as an `int` — see
[reading memory](memory.md#a-single-value-read), and
[error handling](machine.md#connection-and-timeout-failures) for the
`TransportError` family. To point this at a different machine, change the name
in `connect()` and the address at the top.
