"""Live ELVIRA hurry-up display for an Elvira pinball machine.

Spell out ELVIRA in the terminal, lighting each letter red, and show the
hurry-up timer while it's ticking down.

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

machine = warpedpinball.connect("Elvira", password="pinball")

previous_timer = 0
lit = 0  # ELVIRA letters currently lit (held across a hurry-up; see below)
while True:
    try:
        timer = machine.read(0x0175)      # hurry-up countdown
        letters = machine.read(0x076D)    # letters lit on the machine
    except TransportError as error:
        # A dropped packet or a busy board shouldn't kill the display; the
        # library gives us a clean message, so show it and try again.
        print("\r" + str(error) + CLEAR_EOL, end="", flush=True)
        time.sleep(1)
        continue

    # During a hurry-up the machine drives this byte down to 4 (and to 0 once
    # it's over), even though the letters you've already earned stay lit. So
    # hold the highest count we've seen and only clear it when the byte hits 0.
    lit = 0 if letters == 0 else max(lit, letters)

    # Light the earned letters red and dim the rest, so ELVIRA fills in.
    line = ""
    for i, letter in enumerate(WORD):
        line += (RED if i < lit else DIM) + letter + RESET + " "

    # The timer byte only counts down during a live hurry-up; once the shot is
    # made or missed it freezes on a junk value, so only show it while it's
    # actually smaller than last time (still ticking).
    if 0 < timer < previous_timer:
        line += f" {timer:>3}"
    previous_timer = timer

    # "\r" returns to the start of the line and CLEAR_EOL wipes the old text,
    # so a shorter line (once the timer disappears) fully overwrites the
    # previous one instead of leaving stale characters behind.
    print("\r" + line + CLEAR_EOL, end="", flush=True)
    time.sleep(1)
