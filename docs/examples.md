# Examples

Runnable scripts live in the [`examples/`](../examples) directory. Each is a
single self-contained file you can copy, run, and adapt.

| Example | What it shows |
| --- | --- |
| [`elvira_hurryup.py`](../examples/elvira_hurryup.py) | A live, animated ELVIRA display driven by two SRAM bytes — plus robust state tracking and clean error handling for a long-running poll loop |

## ELVIRA hurry-up display

[`examples/elvira_hurryup.py`](../examples/elvira_hurryup.py) watches an
*Elvira* pinball machine and spells out **ELVIRA** in your terminal, lighting
one letter red each time the player makes the hurry-up shot — the same thing
the machine shows on the backbox.

```bash
python examples/elvira_hurryup.py Elvira --password pinball
```

```
E  L  V  I  R  A   [######----]   6      # counting down, letter 3 pulsing
E  L  V  I  R  A   *** COMPLETE! ***      # all six earned
```

It redraws a single line in place (no scrolling), pulses the letter currently
up for grabs, and flashes when a new one is earned. `--no-color` falls back to
plain text; `--interval` changes the poll rate.

### Why it tracks state

The naive version — read the timer, read the letter count, print them — has two
problems this example fixes.

**The timer byte lies when idle.** `0x0175` is only meaningful *while a
hurry-up is live*. The instant the player makes the shot, the timer **freezes**
at whatever it was; if they miss, it drains to **0**. After that it holds a
stale "junk" value until the next hurry-up. So the script never trusts a single
reading — it watches how the timer *changes* between polls:

- timer **jumped up** → a fresh hurry-up just started;
- timer **ticked down** → a live countdown, safe to display;
- timer **unchanged** → frozen or idle junk, stop showing the countdown.

**"Made" vs. "missed" is a transition, not a value.** A shot is *made* when a
live countdown freezes early (and the flashing letters reset); it's *missed*
when the countdown reaches 0. The script only counts a made shot on that
transition, and lights exactly one ELVIRA letter per made shot. That state —
"how many letters earned so far" — is what you have to keep yourself; it isn't
in either byte.

The `HurryUp` class holds all of this. `poll(timer, letters)` returns
`"made"`, `"missed"`, or `None` for each reading, and exposes `.progress`
(letters earned), `.counting`, and `.timer` for rendering.

### Surviving a flaky network

A poll loop that runs for hours *will* hit a dropped WiFi packet or a board
that's briefly too busy to answer. Rather than let that crash the script with a
wall of `urllib3` traceback, the loop catches the transport errors and keeps
going:

```python
try:
    timer = read_byte(machine, TIMER_ADDR)
    letters = read_byte(machine, LETTERS_ADDR)
except (DeviceTimeoutError, DeviceUnreachableError) as exc:
    draw(f"... {exc}")     # show the friendly message, retry next tick
    time.sleep(args.interval)
    continue
```

`DeviceTimeoutError` and `DeviceUnreachableError` are subclasses of
`TransportError` with human-readable messages — see
[error handling](machine.md#connection-and-timeout-failures).

### Adapting it

The two addresses (`TIMER_ADDR`, `LETTERS_ADDR`) and the target word are
constants at the top of the file — point them at a different machine's memory
map and the same display machinery works. `read_byte()` wraps
`machine.read_bytes(addr, 1)`; swap in a wider read and your own decode (little-
or big-endian) for multi-byte values.
