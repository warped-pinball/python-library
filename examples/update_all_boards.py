"""Find every Vector board on the LAN, check each for a firmware update, and
-- after you confirm -- apply the updates with a live progress bar per board.

The flow is three phases:

1. **Discover** boards with a UDP broadcast (no password needed).
2. **Check** each board's ``/api/update/check`` concurrently and list which
   ones have an update available (note: the firmware enforces a 10 s
   server-side cooldown on this route, so re-runs in quick succession may
   report nothing).
3. **Ask once**, then update every out-of-date board at the same time.
   ``Machine.apply_update()`` streams ``{"log": ..., "percent": ...}`` records
   as the board downloads and flashes, so each board gets its own line with a
   progress bar that fills in as its update runs.

Applying an update is an authenticated route: set each board's password via
the $VECTOR_PASSWORD environment variable (all boards must share it for this
script), or edit connect() below.

    VECTOR_PASSWORD=secret python examples/update_all_boards.py
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import warpedpinball
from warpedpinball import TransportError, VectorError

DISCOVERY_TIMEOUT = 20.0  # seconds to listen for boards
BAR_WIDTH = 30


def check_board(board):
    """Ask one ``(name, ip)`` board whether it has an update available.

    Returns ``(name, ip, url_or_None, error_or_None)``. The update-check
    payload shape isn't rigidly guaranteed, so treat "has a url" as the
    signal that an update exists.
    """
    name, ip = board
    try:
        with warpedpinball.connect(ip) as m:
            info = m.check_for_updates()
    except (TransportError, VectorError, OSError) as error:
        return name, ip, None, str(error)
    url = info.get("url") if isinstance(info, dict) else None
    return name, ip, url, None


class ProgressBoard:
    """One status line per board, redrawn in place with ANSI cursor moves.

    Each updater thread reports its percent/status here; the writer that
    happens to hold the lock repaints all lines. Falls back gracefully when
    stdout isn't a terminal (each repaint just prints fresh lines).
    """

    def __init__(self, names):
        self.lock = threading.Lock()
        self.names = names
        self.state = {name: (0, "waiting") for name in names}
        self.width = max(len(n) for n in names)
        self.drawn = False

    def update(self, name, percent=None, status=None):
        with self.lock:
            old_pct, old_status = self.state[name]
            self.state[name] = (
                old_pct if percent is None else percent,
                old_status if status is None else status,
            )
            self._draw()

    def _draw(self):
        if self.drawn and sys.stdout.isatty():
            sys.stdout.write(f"\x1b[{len(self.names)}A")  # cursor up N lines
        for name in self.names:
            pct, status = self.state[name]
            filled = int(BAR_WIDTH * pct / 100)
            bar = "#" * filled + "-" * (BAR_WIDTH - filled)
            sys.stdout.write(f"\x1b[2K{name:<{self.width}} [{bar}] {pct:3d}%  {status}\n")
        sys.stdout.flush()
        self.drawn = True


def update_board(board, progress):
    """Run one board's update, feeding its streamed percent into the display."""
    name, ip, url, _ = board

    def on_record(record):
        percent = record.get("percent")
        log = record.get("log")
        progress.update(
            name,
            percent=int(percent) if percent is not None else None,
            status=str(log)[:40] if log else None,
        )

    try:
        with warpedpinball.connect(ip) as m:
            progress.update(name, status="updating")
            m.apply_update(url=url, progress=on_record)
            progress.update(name, percent=100, status="done")
    except (TransportError, VectorError, OSError) as error:
        progress.update(name, status=f"FAILED: {error}")


def main():
    print(f"Listening for boards (up to {DISCOVERY_TIMEOUT:.0f}s)...")
    found = warpedpinball.discover(timeout=DISCOVERY_TIMEOUT)
    if not found:
        print("No boards found. Are you on the same network as the machines?")
        return
    boards = sorted(((b.name or b.ip, b.ip) for b in found), key=lambda b: b[0].lower())

    print(f"Found {len(boards)} board(s). Checking for updates...\n")
    with ThreadPoolExecutor(max_workers=min(8, len(boards))) as pool:
        results = list(pool.map(check_board, boards))

    updatable = []
    for name, ip, url, error in results:
        if error:
            print(f"  {name:<20} {ip:<15} unreachable: {error}")
        elif url:
            print(f"  {name:<20} {ip:<15} update available")
            updatable.append((name, ip, url, None))
        else:
            print(f"  {name:<20} {ip:<15} up to date")

    if not updatable:
        print("\nNothing to update.")
        return

    answer = input(f"\nUpdate {len(updatable)} board(s)? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted; no boards were touched.")
        return

    print()
    progress = ProgressBoard([b[0] for b in updatable])
    progress.update(updatable[0][0])  # draw the initial table
    with ThreadPoolExecutor(max_workers=len(updatable)) as pool:
        for board in updatable:
            pool.submit(update_board, board, progress)

    print("\nAll done. Boards reboot themselves to finish applying an update.")


if __name__ == "__main__":
    main()
