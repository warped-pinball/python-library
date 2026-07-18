"""UDP peer discovery for Vector boards (port 37020).

Frame formats (first byte is the message type):

- ``HELLO = 1``: ``bytes([1, name_len]) + name_bytes``; name is UTF-8, max
  32 bytes. Boards broadcast this when they join so the registry adds them.
- ``FULL = 2``: ``bytes([2, peer_count])`` then, per peer: 4 raw IP bytes,
  1 name-length byte, name bytes. The board with the lowest IP acts as the
  registry and broadcasts a FULL frame listing all known boards.
- ``PING = 3`` / ``PONG = 4``: liveness. A board answering a PING sends the
  PONG *unicast* to the sender's IP on port 37020.
- ``OFFLINE = 5``: ``bytes([5]) + 4 IP bytes``. Announces that the given IP
  has left.

How the boards behave (firmware ``discovery.py`` + scheduler): every board
services its discovery socket every **1.5 s**. On any frame from a sender it
does not know, the registry broadcasts FULL and non-registry boards broadcast
HELLO; a PING additionally earns a unicast PONG back to the sender. A *lone*
board never broadcasts FULL on its own -- unprovoked it only says HELLO every
15 s -- so finding a single board depends on our probe actually reaching it.

Discovery strategy, built for awkward networks (Windows multi-homing, travel
routers, hotspots that filter broadcast one way but not the other):

- **Probe with PING + OFFLINE(self).** Either one provokes the registry into
  broadcasting FULL without registering us as a peer (only HELLO does that;
  we never send HELLO, so no pinball machine ever lists this client). PING is
  the important one: every board that hears it also PONGs us *unicast*, which
  gets through even when broadcasts toward us are dropped.
- **Send probes out every interface, to the limited broadcast and to each
  interface's /24 directed broadcast.** ``255.255.255.255`` leaves exactly one
  interface (the default route's), which on a multi-homed machine is often not
  the one the boards are on; a directed broadcast like ``192.168.8.255`` is
  routed by subnet and reaches the right network.
- **Listen for FULL, HELLO, and PONG.** FULL is the registry's complete list
  and ends discovery immediately. HELLO gives one board's IP and name straight
  from the source. PONG gives an IP. If boards were *heard* but no FULL arrives
  shortly after (its broadcast was filtered), the complete list is fetched from
  a heard board over unicast HTTP (``/api/network/peers``) instead.

Boards service discovery every 1.5 s, so the usual result is everything within
about two seconds; the (default 20 s) timeout is only a worst-case cap.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

DISCOVERY_PORT = 37020
BROADCAST_ADDR = "255.255.255.255"
MSG_HELLO = 1
MSG_FULL = 2
MSG_PING = 3
MSG_PONG = 4
MSG_OFFLINE = 5
MAX_NAME_LEN = 32
#: Boards service their discovery socket every 1.5 s; re-probing faster than
#: that only adds noise.
REBROADCAST_INTERVAL = 1.5
#: A board answers PONG and (registry) FULL in the same 1.5 s service tick, so
#: if a board was heard but no FULL followed within this window, the FULL
#: broadcast isn't reaching us and it's time to ask over HTTP instead.
SETTLE_AFTER_SIGHTING = 0.5
#: HTTP timeout for the /api/network/peers fallback query.
PEERS_HTTP_TIMEOUT = 5.0


@dataclass(frozen=True)
class DiscoveredMachine:
    """A Vector board seen on the LAN."""

    ip: str
    name: str


def _ip_to_bytes(ip: str) -> bytes:
    return bytes(int(part) for part in ip.split("."))


def _local_ip() -> str:
    """Best-effort local LAN IP (the source address for LAN traffic).

    Uses a connected UDP socket so no packets are actually sent; falls back to
    ``0.0.0.0`` if the host has no route (the OFFLINE frame still provokes a
    FULL reply, it just names a bogus IP).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        sock.close()


def _local_ips() -> List[str]:
    """Every local IPv4 address worth probing from (all interfaces).

    The boards may sit on a different interface than the default route (e.g. a
    travel router on Wi-Fi while Ethernet carries the internet), so probes are
    sent from each. Best-effort: name resolution can fail on odd hosts, and the
    default-route IP from :func:`_local_ip` is always included when available.
    """
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    primary = _local_ip()
    if primary != "0.0.0.0":
        ips.add(primary)
    return sorted(ip for ip in ips if not ip.startswith("127."))


def _directed_broadcasts(ips: List[str]) -> List[str]:
    """/24 directed broadcast for each local IP (e.g. 192.168.8.7 -> .8.255).

    ``255.255.255.255`` leaves only the default-route interface on most OSes;
    a directed broadcast is routed by subnet and reaches the right network.
    Home/travel-router LANs are /24 in practice; on a wider subnet this still
    reaches the boards in the same /24 and the limited broadcast covers rest.
    """
    return sorted({ip.rsplit(".", 1)[0] + ".255" for ip in ips})


def build_offline(ip: str) -> bytes:
    """Build an OFFLINE frame declaring ``ip`` (dotted-quad) as gone."""
    return bytes([MSG_OFFLINE]) + _ip_to_bytes(ip)


def build_ping() -> bytes:
    """Build a PING frame; any board hearing it PONGs us back unicast."""
    return bytes([MSG_PING])


def parse_hello(data: bytes) -> Optional[str]:
    """Name from a HELLO frame, or None for any other/garbled frame."""
    if len(data) < 2 or data[0] != MSG_HELLO:
        return None
    name_len = data[1]
    return data[2 : 2 + name_len].decode("utf-8", errors="replace")


def parse_full(data: bytes) -> List[DiscoveredMachine]:
    """Parse a FULL frame into machines; returns [] for anything else.

    Tolerant by design: non-FULL types (HELLO/PING/PONG/OFFLINE), truncated
    frames, and garbage all yield [] or the peers parsed before truncation.
    """
    if len(data) < 2 or data[0] != MSG_FULL:
        return []
    count = data[1]
    machines: List[DiscoveredMachine] = []
    pos = 2
    for _ in range(count):
        if pos + 5 > len(data):
            break  # truncated frame; keep what we have
        ip = ".".join(str(b) for b in data[pos : pos + 4])
        name_len = data[pos + 4]
        pos += 5
        if pos + name_len > len(data):
            break
        try:
            name = data[pos : pos + name_len].decode("utf-8")
        except UnicodeDecodeError:
            name = data[pos : pos + name_len].decode("utf-8", errors="replace")
        pos += name_len
        machines.append(DiscoveredMachine(ip=ip, name=name))
    return machines


def _open_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("0.0.0.0", DISCOVERY_PORT))
    except OSError:
        # Port taken (another client running). Broadcast FULL frames and
        # unicast PONGs are both addressed to port 37020, so an ephemeral
        # port is deaf to them -- but with SO_REUSEADDR the bind above rarely
        # fails, and probing still provokes traffic other clients can use.
        sock.bind(("0.0.0.0", 0))
    return sock


def _probe_sockets(ips: List[str]) -> List[socket.socket]:
    """One broadcast-capable send socket bound to each local IP.

    Binding the source address forces the OS to send from that interface,
    which is what makes the limited broadcast leave *every* interface rather
    than just the default route's. Interfaces that refuse are skipped.
    """
    socks = []
    for ip in ips:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((ip, 0))
            socks.append(sock)
        except OSError:
            continue
    return socks


def _peers_over_http(ip: str) -> List[DiscoveredMachine]:
    """Fetch the complete board list from one board's ``/api/network/peers``.

    The payload maps IP -> ``{"name": ..., "self": ...}`` and includes the
    queried board itself, so one reachable board yields the whole network over
    plain unicast HTTP -- no broadcast involved. Raises TransportError family
    on failure; the caller decides how much that matters.
    """
    from .transports.http import HttpTransport

    transport = HttpTransport(ip, timeout=PEERS_HTTP_TIMEOUT)
    try:
        payload = transport.request("/api/network/peers")
    finally:
        transport.close()

    machines = []
    if isinstance(payload, dict):
        for peer_ip, info in payload.items():
            name = info.get("name", "") if isinstance(info, dict) else str(info)
            machines.append(DiscoveredMachine(ip=str(peer_ip), name=str(name)))
    return machines


def discover(
    timeout: float = 20.0,
    name: Optional[str] = None,
) -> List[DiscoveredMachine]:
    """Find Vector boards on the LAN; returns a list of :class:`DiscoveredMachine`.

    Probes (PING + OFFLINE) go out every interface each ~1.5 s -- matching how
    often boards service discovery -- and the first FULL reply ends discovery
    immediately, since it is the registry's complete list. Boards heard only
    directly (a HELLO or a unicast PONG) mean broadcasts toward us are being
    filtered; after a short settle the complete list is fetched from a heard
    board over HTTP instead. The usual result is everything within about two
    seconds; ``timeout`` (default 20 s) is the worst-case cap for genuinely
    quiet networks. ``name`` makes discovery return the instant that exact
    board appears. Results are deduplicated by IP. Never registers this client
    in the boards' own peer lists (that would take a HELLO, which is not sent).
    """
    sock = _open_socket()
    local_ip = _local_ip()
    local_ips = _local_ips()
    probe_socks = _probe_sockets(local_ips)
    targets = [BROADCAST_ADDR] + _directed_broadcasts(local_ips)
    probes = [build_ping(), build_offline(local_ip)]

    found: Dict[str, DiscoveredMachine] = {}  # via FULL frames (dedup by IP)
    sightings: Dict[str, Optional[str]] = {}  # boards heard directly: ip -> name?
    first_sighting: Optional[float] = None
    target = name.lower() if name else None
    deadline = time.monotonic() + timeout
    next_broadcast = 0.0
    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            if first_sighting is not None and now - first_sighting >= SETTLE_AFTER_SIGHTING:
                break  # boards heard but their FULL isn't reaching us; go ask over HTTP
            if now >= next_broadcast:
                for frame in probes:
                    for out in [sock] + probe_socks:
                        for addr in targets:
                            try:
                                out.sendto(frame, (addr, DISCOVERY_PORT))
                            except OSError:
                                pass  # interface without a broadcast route
                next_broadcast = now + REBROADCAST_INTERVAL
            wait = min(0.5, deadline - now)
            if first_sighting is not None:
                wait = min(wait, first_sighting + SETTLE_AFTER_SIGHTING - now)
            sock.settimeout(max(wait, 0.01))
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Windows only: a previously *sent* datagram bounced with ICMP
                # port-unreachable, and Windows reports it on the next receive
                # (WSAECONNRESET). Not a socket failure; keep listening.
                continue
            except OSError:
                break

            for machine in parse_full(data):
                found[machine.ip] = machine
                if target and machine.name.lower() == target:
                    return list(found.values())
            # A FULL frame is the registry's complete list of known boards, so
            # once we have one there is nothing more to wait for -- return
            # instead of burning the rest of the (deliberately long) timeout.
            if len(data) >= 2 and data[0] == MSG_FULL:
                return list(found.values())

            src = addr[0]
            if src == local_ip or src in local_ips:
                continue  # our own probe looped back
            hello_name = parse_hello(data)
            if hello_name is not None:
                sightings[src] = hello_name
                if target and hello_name.lower() == target:
                    found[src] = DiscoveredMachine(ip=src, name=hello_name)
                    return list(found.values())
            elif data[:1] == bytes([MSG_PONG]):
                sightings.setdefault(src, None)
            else:
                continue
            if first_sighting is None:
                first_sighting = time.monotonic()
    finally:
        sock.close()
        for out in probe_socks:
            out.close()

    # Boards were heard directly but no FULL broadcast made it through: get the
    # complete list over unicast HTTP from the first heard board that answers.
    for ip in sightings:
        try:
            for machine in _peers_over_http(ip):
                found.setdefault(machine.ip, machine)
            break  # one board's peer table is the whole picture
        except Exception:
            continue  # that board wouldn't talk HTTP; try the next sighting
    for ip, seen_name in sightings.items():
        found.setdefault(ip, DiscoveredMachine(ip=ip, name=seen_name or ""))
    return list(found.values())
