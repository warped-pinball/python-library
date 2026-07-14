"""Live ELVIRA hurry-up display for an Elvira pinball machine.

Spell out ELVIRA in the terminal, lighting each letter red as the machine
awards it, and show the hurry-up timer while it's ticking down.

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

machine = warpedpinball.connect("Elvira", password="pinball")

previous_timer = 0
while True:
    try:
        timer = machine.read(0x0175)      # hurry-up countdown
        letters = machine.read(0x076D)    # letters awarded so far
    except TransportError as error:
        # A dropped packet or a busy board shouldn't kill the display; the
        # library gives us a clean message, so show it and try again.
        print("\r" + str(error), end="", flush=True)
        time.sleep(1)
        continue

    # Light the awarded letters red and dim the rest, so ELVIRA fills in.
    line = ""
    for i, letter in enumerate(WORD):
        line += (RED if i < letters else DIM) + letter + RESET + " "

    # The timer byte only means something while it's counting down: once the
    # shot is made or missed it freezes on a junk value. So only show it while
    # it's actually smaller than last time (still ticking).
    if 0 < timer < previous_timer:
        line += f" {timer:>3}"
    previous_timer = timer

    # "\r" redraws over the same line instead of scrolling down the screen.
    print("\r" + line, end="", flush=True)
    time.sleep(1)
