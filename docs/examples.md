# Examples

Runnable scripts live in the [`examples/`](../examples) directory. Each is a
small, self-contained file you can copy, run, and tweak.

| Example | What it shows |
| --- | --- |
| [`elvira_hurryup.py`](../examples/elvira_hurryup.py) | Reading a couple of SRAM bytes in a loop and drawing a live ELVIRA hurry-up display |

## ELVIRA hurry-up display

[`examples/elvira_hurryup.py`](../examples/elvira_hurryup.py) watches an
*Elvira* pinball machine and spells out **ELVIRA** in your terminal, lighting
one letter red as the machine awards it — and showing the hurry-up timer while
it counts down.

```bash
python examples/elvira_hurryup.py
```

It's deliberately short. Two things are worth pointing out, because they're easy
to get wrong:

**The timer byte is only meaningful while it's ticking.** `0x0175` counts down
during a hurry-up, but the moment the shot is made or missed it freezes on a
stale "junk" value. So the script keeps the previous reading and only shows the
timer while it's actually getting smaller:

```python
if 0 < timer < previous_timer:
    line += f" {timer:>3}"
previous_timer = timer
```

**A long-running loop will hit a network hiccup.** A dropped packet or a busy
board raises a `TransportError` (now with a clean, one-line message — no
`urllib3` stack). Catch it, show it, and keep going instead of crashing:

```python
try:
    timer = machine.read(0x0175)
    letters = machine.read(0x076D)
except TransportError as error:
    print("\r" + str(error), end="", flush=True)
    time.sleep(1)
    continue
```

`read(offset)` returns the byte at that address as an `int` — see
[reading memory](memory.md#a-single-value-read).

See [error handling](machine.md#connection-and-timeout-failures) for the
`TransportError` family. To point this at a different machine or memory map,
change the name in `connect()` and the two addresses at the top.
