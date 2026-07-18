"""Find every Vector board on the LAN and print what each one is.

Discovery (a UDP broadcast on port 37020) gives you the cheap facts for free --
each board's IP and its LAN name -- with no password and no per-board HTTP
round-trip. That alone is enough for an inventory, so it prints first and always
works even on a locked-down or busy network.

Some networks -- phone hotspots, guest Wi-Fi, some travel routers -- silently
drop the broadcast traffic discovery relies on (client isolation), so the
broadcast finds nothing even though the boards are reachable by unicast HTTP.
When that happens this script asks you for one board's IP and enumerates the
rest from that board's own peer table (``GET /api/network/peers``) -- no
broadcast required.

Once it has a list of boards -- from discovery or from the IP you supply -- it
connects to each over HTTP and asks a few read-only questions (firmware version,
configured game name, whether a game is in progress). None of these need a
password. Boards are contacted concurrently so one slow or unreachable board
doesn't hold up the rest, and any board that fails to answer is reported inline
rather than aborting the run.

    python examples/discover_boards.py
"""

from concurrent.futures import ThreadPoolExecutor

import warpedpinball
from warpedpinball import TransportError, VectorError

DISCOVERY_TIMEOUT = 20.0  # seconds to listen for boards (see discover() docs)


def describe(board):
    """Connect to one board (a ``(name, ip)`` pair) and gather read-only details.

    Returns a dict of facts. Every field beyond ip/name is best-effort: a board
    might be mid-reboot or briefly unreachable, so a failed lookup becomes an
    ``error`` entry instead of raising and sinking the whole run.
    """
    name, ip = board
    facts = {"name": name, "ip": ip}
    try:
        with warpedpinball.connect(ip) as m:
            facts["firmware"] = _version_string(m.version())
            facts["game"] = _scalar(m.game_name())
            status = m.game_status()
            facts["in_game"] = bool(_field(status, "GameActive", "game_active"))
    except (TransportError, VectorError, OSError) as error:
        facts["error"] = str(error)
    return facts


def find_boards():
    """Return a list of ``(name, ip)`` boards, via broadcast or an IP fallback."""
    print(f"Listening for boards (up to {DISCOVERY_TIMEOUT:.0f}s)...")
    found = warpedpinball.discover(timeout=DISCOVERY_TIMEOUT)
    if found:
        return [(b.name, b.ip) for b in found]

    # Broadcast turned up nothing. On networks that block broadcast (hotspots,
    # some travel routers) the boards are still reachable by IP, so ask for one
    # and enumerate the rest from its peer table.
    print("\nNo boards answered the broadcast. This network may be blocking it.")
    ip = input("Enter a board's IP address (blank to give up): ").strip()
    if not ip:
        return []
    return boards_from_ip(ip)


def boards_from_ip(ip):
    """Enumerate boards starting from one known IP, via its /api/network/peers."""
    boards = {ip: None}  # ip -> name; the supplied board is always included
    try:
        with warpedpinball.connect(ip) as m:
            for name, peer_ip in _parse_peers(m.peers()):
                boards.setdefault(peer_ip, None)
                if name:
                    boards[peer_ip] = name
    except (TransportError, VectorError, OSError) as error:
        # Couldn't reach that IP at all -- still return it so describe() can
        # report the connection error to the user rather than silently dropping.
        print(f"Could not read the peer table from {ip}: {error}")
    return [(name or ip, ip) for ip, name in boards.items()]


def _parse_peers(payload):
    """Yield ``(name, ip)`` from a peer payload, tolerant of its exact shape.

    The firmware's /api/network/peers JSON shape isn't guaranteed here, so accept
    the common ones -- a list of dicts, a list of ip/name pairs, or an ip->name
    mapping -- and skip anything without an IP-looking value.
    """
    items = payload.items() if isinstance(payload, dict) else payload
    if not isinstance(items, (list, tuple)) and not isinstance(payload, dict):
        return
    for item in items:
        name = ip = None
        if isinstance(item, dict):
            ip = item.get("ip") or item.get("IP") or item.get("address")
            name = item.get("name") or item.get("Name")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            first, second = item
            # Either (ip, name) pairs or dict.items() -> (ip, name).
            ip, name = (first, second) if _looks_like_ip(first) else (second, first)
        if _looks_like_ip(ip):
            yield (str(name) if name else None), str(ip)


def _looks_like_ip(value):
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts)


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
    boards = find_boards()
    if not boards:
        print("No boards found. Are you on the same network as the machines?")
        return

    boards = sorted(boards, key=lambda b: b[0].lower())
    print(f"\nFound {len(boards)} board(s):\n")
    for name, ip in boards:
        print(f"  {name:<20} {ip}")

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
