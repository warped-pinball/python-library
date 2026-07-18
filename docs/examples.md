# Examples

Runnable scripts live in the [`examples/`](../examples) directory. Each is a
small, self-contained file you can copy, run, and tweak.

| Example | What it shows |
| --- | --- |
| [`discover_boards.py`](../examples/discover_boards.py) | Finding every board on the LAN, then connecting to each to print its IP, name, firmware, and game state |
| [`elvira_hurryup.py`](../examples/elvira_hurryup.py) | Polling an SRAM byte in a loop and inferring game state to draw a live ELVIRA hurry-up display |

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
