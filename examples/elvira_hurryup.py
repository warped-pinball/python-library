"""Live ELVIRA hurry-up display for an Elvira pinball machine.

Spell out ELVIRA in the terminal and light a letter red each time the player
makes the hurry-up shot.

The letters byte the machine exposes isn't trustworthy during a hurry-up -- the
machine sets it to 4 preemptively -- so we watch the hurry-up *timer* instead
(address 0x0175, read twice a second):

* it arms at 20 and holds there for a beat while a short intro plays;
* then it ticks down once a second;
* if it freezes partway down (stops updating for more than a second) the shot
  was made -- light the next letter;
* if it reaches 0, the shot was missed.

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
READ_PERIOD = 0.5   # seconds between reads
FROZEN_AFTER = 1.5  # timer unchanged this long (> the 1 s tick) => it stopped

machine = warpedpinball.connect("Elvira", password="pinball")


def draw(text):
    # "\r" returns to the start of the line; CLEAR_EOL wipes the old text so a
    # shorter line fully overwrites the previous one (no stale timer digits).
    print("\r" + text + CLEAR_EOL, end="", flush=True)


earned = 0                      # ELVIRA letters lit so far
previous_timer = None           # last timer reading
last_change = time.monotonic()  # when the timer last changed value
counting = False                # True once the timer has started ticking down
resolved = True                 # True once this hurry-up is made/missed (or idle)

while True:
    try:
        timer = machine.read(TIMER_ADDR)
    except TransportError as error:
        # A dropped packet or a busy board shouldn't kill the display.
        draw(str(error))
        time.sleep(READ_PERIOD)
        continue

    now = time.monotonic()
    if previous_timer is None:
        previous_timer = timer  # first read: nothing to compare against yet

    if timer != previous_timer:
        last_change = now
        if timer > previous_timer or previous_timer - timer > 3:
            # The board (re)armed the timer: a new hurry-up is starting. The
            # intro plays now, so the value sits still for a beat before ticking.
            counting = False
            resolved = False
        elif timer == 0:
            resolved = True   # ticked all the way down: shot missed
        else:
            counting = True   # a normal 1-per-second tick: we're past the intro

    # A live countdown that stops partway down means the shot was made. (The
    # intro also sits still, but counting is still False then, so it's ignored.)
    if counting and not resolved and timer > 0 and now - last_change > FROZEN_AFTER:
        earned = min(earned + 1, len(WORD))
        resolved = True
        counting = False

    previous_timer = timer

    # Light the earned letters red and dim the rest, so ELVIRA fills in.
    line = "".join(
        (RED if i < earned else DIM) + letter + RESET + " "
        for i, letter in enumerate(WORD)
    )
    # Show the countdown only while a hurry-up is live (not once it's resolved).
    if not resolved and timer > 0:
        line += f" {timer:>3}"
    draw(line)
    time.sleep(READ_PERIOD)
