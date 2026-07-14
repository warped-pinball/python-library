# Examples

Runnable scripts live in the [`examples/`](../examples) directory. Each is a
small, self-contained file you can copy, run, and tweak.

| Example | What it shows |
| --- | --- |
| [`elvira_hurryup.py`](../examples/elvira_hurryup.py) | Polling an SRAM byte in a loop and inferring game state to draw a live ELVIRA hurry-up display |

## ELVIRA hurry-up display

[`examples/elvira_hurryup.py`](../examples/elvira_hurryup.py) watches an
*Elvira* pinball machine and spells out **ELVIRA** in your terminal, lighting
one letter red each time the player makes the hurry-up shot.

```bash
python examples/elvira_hurryup.py
```

The interesting part: the letter count at `0x076D` is truthful *except* while a
hurry-up is running, when the machine preemptively sets it to 4 even though the
letters you've earned stay lit. The tell is the **timer** (`0x0175`) — it only
moves while a hurry-up is live. It arms at 20, sits there through a short
intro, then ticks down once a second; when the shot is made it freezes, and
when it's missed it reaches 0. So the script polls both bytes twice a second
and uses the timer's *motion* to decide when to believe the letters:

```python
grace = INTRO_GRACE if timer == 20 else FROZEN_AFTER
hurryup_live = timer > 0 and (now - last_change) < grace

if not hurryup_live:
    lit = letters      # timer still => no hurry-up running: byte is truthful
```

While the timer is moving, the display keeps the last trusted letter count (so
the word never dips to 4) and shows the countdown. Once the timer stops for
more than `FROZEN_AFTER` (1.5 s — comfortably longer than the 1 s tick, so a
normal countdown never looks "stopped"), whatever the machine now reports is
shown faithfully. `INTRO_GRACE` (2.5 s) allows the extra stillness at 20 while
the intro plays. Because the letters byte is re-read whenever no hurry-up is
live, starting the script mid-game shows the correct letters immediately.

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
