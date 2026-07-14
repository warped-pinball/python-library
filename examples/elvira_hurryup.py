"""Live ELVIRA hurry-up display for an Elvira pinball machine.

Spell out ELVIRA in the terminal, lighting the letters red as the machine
awards them, with the hurry-up countdown shown while a shot is live.

The letters byte (0x076D) is truthful except during a hurry-up, when the
machine preemptively sets it to 4. The tell is the timer (0x0175): it only
moves while a hurry-up is running (it arms at 20, sits there through a short
intro, then ticks down once a second). So we poll twice a second and:

* while the timer is changing (or briefly holding at 20 for the intro), a
  hurry-up is live -- keep the letters we last trusted and show the countdown;
* once the timer stops moving for over a second, the hurry-up is over (made,
  missed, or none running) -- show the letters byte faithfully.

    python examples/elvira_hurryup.py
"""

import os
import time

import warpedpinball
from warpedpinball import TransportError

os.system("")  # enable ANSI colors on Windows terminals (no-op elsewhere)

WORD = "ELVIRA"
RED = "\033[91m"
DIM = "\033[90m"
RESET = "\033[0m"
CLEAR_EOL = "\033[K"  # erase from the cursor to the end of the line

TIMER_ADDR = 0x0175
LETTERS_ADDR = 0x076D
READ_PERIOD = 0.5    # seconds between reads
FROZEN_AFTER = 1.5   # timer unchanged this long (> the 1 s tick) => not live
INTRO_GRACE = 2.5    # the intro holds the timer at 20 a bit longer than a tick

machine = warpedpinball.connect("Elvira", password="pinball")


def draw(text):
    # "\r" returns to the start of the line; CLEAR_EOL wipes the old text so a
    # shorter line fully overwrites the previous one (no stale timer digits).
    print("\r" + text + CLEAR_EOL, end="", flush=True)


lit = 0
previous_timer = None
last_change = float("-inf")  # when the timer last changed value

while True:
    try:
        timer = machine.read(TIMER_ADDR)
        letters = machine.read(LETTERS_ADDR)
    except TransportError as error:
        # A dropped packet or a busy board shouldn't kill the display.
        draw(str(error))
        time.sleep(READ_PERIOD)
        continue

    now = time.monotonic()
    # The first read is a baseline, not a change: a stale timer value at
    # startup must not look "live", so mid-game the letters show right away.
    if previous_timer is not None and timer != previous_timer:
        last_change = now
    previous_timer = timer

    # The timer only moves while a hurry-up is live. Allow a little extra
    # stillness at 20, where it waits out the intro before ticking.
    grace = INTRO_GRACE if timer == 20 else FROZEN_AFTER
    hurryup_live = timer > 0 and (now - last_change) < grace

    # The letters byte is only wrong *during* a hurry-up (preemptively set to
    # 4); the rest of the time, believe it. While one is live, keep the last
    # trusted value so the word doesn't dip.
    if not hurryup_live:
        lit = letters

    # Light the awarded letters red and dim the rest, so ELVIRA fills in.
    line = "".join(
        (RED if i < lit else DIM) + letter + RESET + " "
        for i, letter in enumerate(WORD)
    )
    if hurryup_live:
        line += f" {timer:>3}"
    draw(line)
    time.sleep(READ_PERIOD)
