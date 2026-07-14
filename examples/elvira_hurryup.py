#!/usr/bin/env python3
"""Live ELVIRA hurry-up display for an Elvira pinball machine.

Watch the machine's SRAM and spell out **ELVIRA** in your terminal, lighting
one letter red each time the player makes the hurry-up shot before the timer
runs out -- exactly like the machine does on the backbox.

    python examples/elvira_hurryup.py Elvira --password pinball

Two SRAM bytes drive this:

* ``0x0175`` -- the hurry-up **timer** (counts down while a shot is live).
* ``0x076D`` -- the **letters** currently flashing in the prompt.

The catch, and the reason this script tracks state instead of trusting the
raw bytes frame by frame: the timer byte is only meaningful *while a hurry-up
is running*. The moment the player makes the shot the timer **freezes** at its
current value (and the flashing letters reset), and if they miss, it drains to
**0**. Either way it then holds a stale "junk" value until the next hurry-up.
So we don't read the timer as gospel -- we watch how it changes between polls
to tell a live countdown from leftover junk, and only count a shot as *made*
when the timer freezes early. Every made shot lights one letter of ELVIRA.
"""

from __future__ import annotations

import argparse
import sys
import time

import warpedpinball
from warpedpinball import (
    DeviceTimeoutError,
    DeviceUnreachableError,
    MachineNotFoundError,
    TransportError,
)

WORD = "ELVIRA"
TIMER_ADDR = 0x0175
LETTERS_ADDR = 0x076D
POLL_SECONDS = 1.0

# -- ANSI helpers ------------------------------------------------------------

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[90m"
RED = "\x1b[91m"
WHITE = "\x1b[97m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR_LINE = "\r\x1b[2K"  # carriage-return + erase-to-end: redraw in place


def enable_windows_ansi() -> None:
    """Turn on ANSI escape handling in legacy Windows consoles (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass  # worst case: colors show as raw codes; the display still works


def paint(text: str, style: str, color: bool) -> str:
    return f"{style}{text}{RESET}" if color else text


def draw(line: str) -> None:
    """Overwrite the current terminal line (no scrolling)."""
    sys.stdout.write(CLEAR_LINE + line)
    sys.stdout.flush()


# -- state tracking ----------------------------------------------------------


class HurryUp:
    """Turns the two noisy SRAM bytes into ELVIRA progress.

    ``progress`` is the number of ELVIRA letters earned so far; it only ever
    goes up, one letter per hurry-up shot made. ``poll()`` returns ``"made"``,
    ``"missed"``, or ``None`` for each reading so the caller can react.
    """

    def __init__(self, word: str = WORD):
        self.word = word
        self.progress = 0      # ELVIRA letters earned (0..len(word))
        self.lit = 0           # letters flashing in the current prompt
        self.timer = 0         # last timer reading
        self.timer_max = 1     # highest timer value seen this hurry-up (bar scale)
        self.counting = False  # True only while the timer is a live countdown
        self._prev_timer: "int | None" = None
        self._prev_lit = 0

    def poll(self, raw_timer: int, raw_letters: int) -> "str | None":
        timer = max(0, int(raw_timer))
        lit = max(0, int(raw_letters))
        event = None

        # Decide whether the timer is a *live* countdown. It counts only when
        # it actually ticks; a value that jumped up starts a fresh hurry-up,
        # and an unchanged value is frozen junk we should stop trusting.
        counting = self.counting
        if self._prev_timer is None:
            counting = False
        elif timer > self._prev_timer:
            counting = timer > 0
            self.timer_max = max(timer, 1)
        elif timer < self._prev_timer:
            counting = timer > 0
            self.timer_max = max(self.timer_max, self._prev_timer, 1)
        else:  # unchanged: frozen (shot made) or idle leftover
            counting = False

        # A live countdown just ended. Which way?
        if self.counting and not counting:
            if timer == 0:
                event = "missed"           # drained to zero -> shot missed
            elif lit < self._prev_lit:
                event = "made"             # froze early + letters reset -> made

        if event == "made" and self.progress < len(self.word):
            self.progress += 1

        self._prev_timer = timer
        self._prev_lit = lit
        self.timer = timer
        self.lit = lit
        self.counting = counting
        return event


# -- rendering ---------------------------------------------------------------


def countdown_bar(timer: int, timer_max: int, width: int = 10) -> str:
    filled = max(0, min(width, round(width * timer / max(timer_max, 1))))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def render(hurry: HurryUp, frame: int, color: bool) -> str:
    cells = []
    for i, ch in enumerate(hurry.word):
        if i < hurry.progress:
            cells.append(paint(ch, BOLD + RED, color))          # earned
        elif hurry.counting and i == hurry.progress:
            style = BOLD + RED if frame % 2 else DIM             # pulse the target
            cells.append(paint(ch, style, color))
        else:
            cells.append(paint(ch, DIM, color))                 # not yet lit
    line = "  ".join(cells)

    if hurry.counting:
        bar = paint(countdown_bar(hurry.timer, hurry.timer_max), WHITE, color)
        line += f"   {bar} {hurry.timer:>3}"
    elif hurry.progress >= len(hurry.word):
        line += "   " + paint("*** COMPLETE! ***", BOLD + RED, color)
    else:
        line += "   " + paint("waiting for the shot...", DIM, color)
    return line


def flash_award(hurry: HurryUp, color: bool) -> None:
    """Quick local blink when a letter is earned (no network calls)."""
    if not color:
        return
    for i in range(6):
        cells = []
        for j, ch in enumerate(hurry.word):
            if j == hurry.progress - 1:
                style = BOLD + WHITE if i % 2 else BOLD + RED   # blink the new letter
            elif j < hurry.progress:
                cells.append(paint(ch, BOLD + RED, color))
                continue
            else:
                style = DIM
            cells.append(paint(ch, style, color))
        draw("  ".join(cells) + "   " + paint("LETTER!", BOLD + RED, color))
        time.sleep(0.07)


# -- device access -----------------------------------------------------------


def read_byte(machine: "warpedpinball.Machine", address: int) -> int:
    """Read a single unsigned byte from SRAM at ``address``."""
    return machine.read_bytes(address, 1)[0]


def connect(args: argparse.Namespace) -> "warpedpinball.Machine | None":
    """Connect, turning the library's errors into friendly one-liners."""
    try:
        return warpedpinball.connect(args.machine, password=args.password)
    except MachineNotFoundError as exc:
        print(f"Couldn't find a machine named {args.machine!r}.")
        if exc.seen_names:
            print("Machines I can see on the network: " + ", ".join(exc.seen_names))
        else:
            print(
                "No Warped Pinball machines answered discovery. Is it powered on "
                "and on the same network as this computer?"
            )
    except TransportError as exc:
        # DeviceUnreachableError / DeviceTimeoutError already read cleanly here.
        print(str(exc))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Live ELVIRA hurry-up display.")
    parser.add_argument("machine", nargs="?", default="Elvira",
                        help="machine name or IP (default: Elvira)")
    parser.add_argument("--password", default=None,
                        help="machine password (or set $VECTOR_PASSWORD)")
    parser.add_argument("--interval", type=float, default=POLL_SECONDS,
                        help="seconds between reads (default: 1.0)")
    parser.add_argument("--no-color", action="store_true",
                        help="disable ANSI colors and animation")
    args = parser.parse_args()

    enable_windows_ansi()
    color = not args.no_color and sys.stdout.isatty()

    machine = connect(args)
    if machine is None:
        return 1

    hurry = HurryUp()
    frame = 0
    print(f"Watching {args.machine} -- press Ctrl-C to stop.")
    try:
        if color:
            sys.stdout.write(HIDE_CURSOR)
        while True:
            try:
                timer = read_byte(machine, TIMER_ADDR)
                letters = read_byte(machine, LETTERS_ADDR)
            except (DeviceTimeoutError, DeviceUnreachableError) as exc:
                # Transient: the board is busy or briefly off the network.
                # Show it, keep the loop alive, and try again next tick.
                draw(paint(f"... {exc}", DIM, color))
                time.sleep(args.interval)
                continue

            event = hurry.poll(timer, letters)
            if event == "made":
                flash_award(hurry, color)
            draw(render(hurry, frame, color))
            frame += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if color:
            sys.stdout.write(SHOW_CURSOR)
        print()
        machine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
