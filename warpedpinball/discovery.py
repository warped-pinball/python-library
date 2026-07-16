"""UDP peer discovery for Vector boards (port 37020).

Frame formats (first byte is the message type):

- ``HELLO = 1``: ``bytes([1, name_len]) + name_bytes``; name is UTF-8, max
  32 bytes. Boards broadcast this when they join so the registry adds them.
- ``FULL = 2``: ``bytes([2, peer_count])`` then, per peer: 4 raw IP bytes,
  1 name-length byte, name bytes. The board with the lowest IP acts as the
  registry and broadcasts a FULL frame listing all known boards.
- ``OFFLINE = 5``: ``bytes([5]) + 4 IP bytes``. Announces that the given IP
  has left. A board hearing OFFLINE for *another* IP re-broadcasts the FULL
  list (the registry does the actual broadcast), which is exactly the reply
  we want.
- ``PING = 3`` / ``PONG = 4``: board-to-board liveness; clients just tolerate
  (skip) them.

Discovery strategy: rather than sending HELLO -- which would add this client
to the boards' peer registry (we only want *pinball machines* on that list) --
we broadcast an OFFLINE frame naming our own IP. Declaring ourselves offline
provokes the registry into re-broadcasting the full peer list (within ~2 s;
boards service discovery about every 1.5 s) without ever registering us.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import List, Optional

DISCOVERY_PORT = 37020
BROADCAST_ADDR = "255.255.255.255"
MSG_HELLO = 1
MSG_FULL = 2
MSG_OFFLINE = 5
MAX_NAME_LEN = 32
REBROADCAST_INTERVAL = 2.0


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


def build_offline(ip: str) -> bytes:
    """Build an OFFLINE frame declaring ``ip`` (dotted-quad) as gone."""
    return bytes([MSG_OFFLINE]) + _ip_to_bytes(ip)


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
        # Port taken (another client running). The FULL reply is addressed to
        # the sender's source port, so an ephemeral port still works.
        sock.bind(("0.0.0.0", 0))
    return sock


def discover(
    timeout: float = 20.0,
    name: Optional[str] = None,
) -> List[DiscoveredMachine]:
    """Broadcast OFFLINE (self) and collect boards from the registry's FULL reply.

    Declaring ourselves offline nudges the registry into re-broadcasting its
    complete peer list without adding this client to it. Boards service
    discovery infrequently, so getting a reply can take a while -- ``timeout``
    (default 20 s) is how long to wait, re-broadcasting every ~2 s. But a FULL
    frame is the registry's *complete* list of known boards, so discovery
    returns the moment one arrives rather than burning the whole timeout.
    ``name`` lets it also return the instant that exact board appears in a
    reply. Results are deduplicated by IP.
    """
    sock = _open_socket()
    offline = build_offline(_local_ip())
    found: dict = {}  # ip -> DiscoveredMachine (dedup; registry may list itself)
    target = name.lower() if name else None
    deadline = time.monotonic() + timeout
    next_broadcast = 0.0
    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_broadcast:
                try:
                    sock.sendto(offline, (BROADCAST_ADDR, DISCOVERY_PORT))
                except OSError:
                    pass  # no broadcast route; FULL replies may still arrive
                next_broadcast = now + REBROADCAST_INTERVAL
            sock.settimeout(min(0.5, deadline - now))
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
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
    finally:
        sock.close()
    return list(found.values())
