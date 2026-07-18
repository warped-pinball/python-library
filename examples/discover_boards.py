"""Find every Vector board on the LAN and print what each one is.

Discovery (a UDP broadcast on port 37020) gives you the cheap facts for free --
each board's IP and its LAN name -- with no password and no per-board HTTP
round-trip. That alone is enough for an inventory, so it prints first and always
works even on a locked-down or busy network.

Then, for a richer listing, the script connects to each board over HTTP and asks
it a few read-only questions (firmware version, configured game name, whether a
game is in progress). None of these need a password. Boards are contacted
concurrently so one slow or unreachable board doesn't hold up the rest, and any
board that fails to answer is reported inline rather than aborting the run.

    python examples/discover_boards.py
"""

from concurrent.futures import ThreadPoolExecutor

import warpedpinball
from warpedpinball import TransportError, VectorError

DISCOVERY_TIMEOUT = 20.0  # seconds to listen for boards (see discover() docs)


def describe(board):
    """Connect to one discovered board and gather a few read-only details.

    Returns a dict of facts. Every field beyond ip/name is best-effort: a board
    might be mid-reboot or briefly unreachable, so a failed lookup becomes an
    ``error`` entry instead of raising and sinking the whole run.
    """
    facts = {"name": board.name, "ip": board.ip}
    try:
        with warpedpinball.connect(board.ip) as m:
            facts["firmware"] = _version_string(m.version())
            facts["game"] = _scalar(m.game_name())
            status = m.game_status()
            facts["in_game"] = bool(_field(status, "GameActive", "game_active"))
    except (TransportError, VectorError, OSError) as error:
        facts["error"] = str(error)
    return facts


def _version_string(payload):
    """Pull a version out of /api/version, which may be a dict or a bare value."""
    if isinstance(payload, dict):
        return str(payload.get("version") or payload.get("Version") or payload)
    return str(payload)


def _scalar(payload):
    """Unwrap a single-value API payload (often a 1-key dict) to something short."""
    if isinstance(payload, dict):
        values = list(payload.values())
        if len(values) == 1:
            return str(values[0])
    return str(payload)


def _field(payload, *keys):
    """First present key from a dict payload (firmware casing varies), else None."""
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                return payload[key]
    return None


def main():
    print(f"Listening for boards (up to {DISCOVERY_TIMEOUT:.0f}s)...")
    boards = warpedpinball.discover(timeout=DISCOVERY_TIMEOUT)
    if not boards:
        print("No boards found. Are you on the same network as the machines?")
        return

    boards = sorted(boards, key=lambda b: b.name.lower())
    print(f"\nFound {len(boards)} board(s):\n")
    for board in boards:
        print(f"  {board.name:<20} {board.ip}")

    # Enrich each board over HTTP, all at once so slow boards overlap.
    print("\nAsking each board about itself...\n")
    with ThreadPoolExecutor(max_workers=min(8, len(boards))) as pool:
        details = list(pool.map(describe, boards))

    for facts in details:
        print(f"{facts['name']}  ({facts['ip']})")
        if "error" in facts:
            print(f"  unreachable: {facts['error']}")
        else:
            print(f"  firmware : {facts['firmware']}")
            print(f"  game     : {facts['game']}")
            print(f"  in game  : {'yes' if facts['in_game'] else 'no'}")
        print()


if __name__ == "__main__":
    main()
