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

The interesting part is that the obvious byte to read — the letter count at
`0x076D` — can't be trusted: while a hurry-up is running the machine sets it to
4 preemptively, even though the letters you've earned are still lit. So the
script ignores it and reads the hurry-up **timer** (`0x0175`) twice a second,
inferring the outcome from how it moves:

- it **arms at 20** and holds there for a beat while a short intro plays;
- then it **ticks down once a second**;
- if it **freezes partway down** — stops updating for more than a second — the
  shot was made, so we light the next letter;
- if it **reaches 0**, the shot was missed.

The one subtlety is telling the intro (timer sitting still at 20) apart from a
made shot (timer sitting still partway down). A `counting` flag, set only once
the timer has actually started ticking down, does that:

```python
if counting and not resolved and timer > 0 and now - last_change > FROZEN_AFTER:
    earned = min(earned + 1, len(WORD))   # timer stopped mid-countdown: made
    resolved = True
    counting = False
```

`FROZEN_AFTER` is 1.5 s — comfortably longer than the 1 s tick, so a normal
countdown never looks "stopped." Because it tracks made shots itself, the
display starts empty and fills in as you make shots while it's watching.

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
