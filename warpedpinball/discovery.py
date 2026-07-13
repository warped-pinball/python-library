"""UDP peer discovery for Vector boards (port 37020).

Frame formats (first byte is the message type):

- ``HELLO = 1``: ``bytes([1, name_len]) + name_bytes``; name is UTF-8, max
  32 bytes. Clients broadcast this to ``255.255.255.255:37020``.
- ``FULL = 2``: ``bytes([2, peer_count])`` then, per peer: 4 raw IP bytes,
  1 name-length byte, name bytes. The board with the lowest IP acts as the
  registry and answers HELLOs with a FULL frame listing all known boards.
- ``PING = 3`` / ``PONG = 4`` / ``OFFLINE = 5``: board-to-board liveness;
  clients just tolerate (skip) them.
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
MAX_NAME_LEN = 32
HELLO_INTERVAL = 2.0
DEFAULT_CLIENT_NAME = "python-client"


@dataclass(frozen=True)
class DiscoveredMachine:
    """A Vector board seen on the LAN."""

    ip: str
    name: str


def build_hello(name: str = DEFAULT_CLIENT_NAME) -> bytes:
    """Build a HELLO frame announcing ``name`` (UTF-8, truncated to 32 bytes)."""
    name_bytes = name.encode("utf-8")[:MAX_NAME_LEN]
    return bytes([MSG_HELLO, len(name_bytes)]) + name_bytes


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
    timeout: float = 5.0,
    name: Optional[str] = None,
    client_name: str = DEFAULT_CLIENT_NAME,
) -> List[DiscoveredMachine]:
    """Broadcast HELLO and collect boards from FULL replies.

    Listens for ``timeout`` seconds, re-broadcasting HELLO every ~2 s. When
    ``name`` is given, returns early as soon as a case-insensitive exact match
    is seen (used by ``connect()``). Results are deduplicated by IP.
    """
    sock = _open_socket()
    hello = build_hello(client_name)
    found: dict = {}  # ip -> DiscoveredMachine (dedup; registry may list itself)
    target = name.lower() if name else None
    deadline = time.monotonic() + timeout
    next_hello = 0.0
    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            if now >= next_hello:
                try:
                    sock.sendto(hello, (BROADCAST_ADDR, DISCOVERY_PORT))
                except OSError:
                    pass  # no broadcast route; FULL replies may still arrive
                next_hello = now + HELLO_INTERVAL
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
    finally:
        sock.close()
    return list(found.values())
