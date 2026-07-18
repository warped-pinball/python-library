"""Frame encoding/decoding and the discover() probe/reply/fallback logic."""

import socket

import pytest

import warpedpinball.discovery as discovery
from warpedpinball.discovery import (
    DiscoveredMachine,
    build_offline,
    build_ping,
    parse_full,
    parse_hello,
)

# The real function, captured before the autouse fixture below patches it.
_real_local_ips = discovery._local_ips


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Keep discover() off the real network and make settle waits fast."""
    monkeypatch.setattr(discovery, "_local_ips", lambda: [])
    monkeypatch.setattr(discovery, "SETTLE_AFTER_SIGHTING", 0.05)


def peer(ip: str, name: str) -> bytes:
    name_bytes = name.encode()
    return bytes(int(o) for o in ip.split(".")) + bytes([len(name_bytes)]) + name_bytes


def full_frame(*peers: bytes) -> bytes:
    return bytes([2, len(peers)]) + b"".join(peers)


def hello_frame(name: str) -> bytes:
    name_bytes = name.encode()
    return bytes([1, len(name_bytes)]) + name_bytes


def test_parse_full_two_peers():
    frame = full_frame(peer("192.168.4.243", "Pinbot"), peer("192.168.4.7", "Elvira"))
    assert parse_full(frame) == [
        DiscoveredMachine(ip="192.168.4.243", name="Pinbot"),
        DiscoveredMachine(ip="192.168.4.7", name="Elvira"),
    ]


def test_parse_full_registry_lists_itself():
    frame = full_frame(peer("10.0.0.5", "Registry"), peer("10.0.0.5", "Registry"))
    machines = parse_full(frame)
    assert machines == [DiscoveredMachine("10.0.0.5", "Registry")] * 2  # dedup is discover()'s job


def test_parse_full_truncated_mid_peer_keeps_earlier_peers():
    frame = full_frame(peer("10.0.0.1", "One"), peer("10.0.0.2", "Two"))
    truncated = frame[:-3]  # cut inside the second peer's name
    assert parse_full(truncated) == [DiscoveredMachine("10.0.0.1", "One")]


def test_parse_full_truncated_header():
    assert parse_full(bytes([2])) == []
    assert parse_full(bytes([2, 3])) == []  # claims 3 peers, has none


def test_parse_full_ignores_other_message_types():
    for msg_type in (1, 3, 4, 5):  # HELLO, PING, PONG, OFFLINE
        assert parse_full(bytes([msg_type, 0, 1, 2, 3])) == []


def test_parse_full_garbage_and_empty():
    assert parse_full(b"") == []
    assert parse_full(b"\xff\xfe\xfd") == []
    assert parse_full(b"not a frame at all") == []


def test_parse_full_bad_utf8_name_does_not_crash():
    bad = bytes([2, 1]) + bytes([10, 0, 0, 9]) + bytes([2]) + b"\xff\xfe"
    machines = parse_full(bad)
    assert len(machines) == 1
    assert machines[0].ip == "10.0.0.9"


def test_parse_hello():
    assert parse_hello(hello_frame("Elvira")) == "Elvira"
    assert parse_hello(b"") is None
    assert parse_hello(bytes([2, 1, 65])) is None  # FULL, not HELLO
    assert parse_hello(bytes([1])) is None  # truncated header
    assert parse_hello(bytes([1, 2]) + b"\xff\xfe") == "��"  # bad UTF-8


def test_build_offline():
    frame = build_offline("192.168.4.7")
    assert frame[0] == 5  # MSG_OFFLINE
    assert frame[1:] == bytes([192, 168, 4, 7])
    assert len(frame) == 5


def test_build_ping():
    assert build_ping() == bytes([3])


def test_directed_broadcasts():
    assert discovery._directed_broadcasts(["192.168.8.7", "10.1.2.3"]) == [
        "10.1.2.255",
        "192.168.8.255",
    ]
    # Duplicate subnets collapse to one directed broadcast.
    assert discovery._directed_broadcasts(["192.168.8.7", "192.168.8.9"]) == [
        "192.168.8.255"
    ]


def test_local_ips_merges_interfaces_and_filters(monkeypatch):
    # getaddrinfo lists per-interface IPs; the default-route IP is merged in,
    # loopback is dropped, and the result is sorted and de-duplicated.
    infos = [
        (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.168.8.7", 0)),
        (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("127.0.1.1", 0)),
        (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("10.0.0.3", 0)),
    ]
    monkeypatch.setattr(discovery.socket, "getaddrinfo", lambda *a, **k: infos)
    monkeypatch.setattr(discovery, "_local_ip", lambda: "192.168.8.7")
    assert _real_local_ips() == ["10.0.0.3", "192.168.8.7"]


def test_local_ips_tolerates_getaddrinfo_failure(monkeypatch):
    # Odd hosts can't resolve their own hostname; the default-route IP still
    # comes back, and a routeless 0.0.0.0 fallback is not treated as an IP.
    def boom(*a, **k):
        raise OSError("resolution failed")

    monkeypatch.setattr(discovery.socket, "getaddrinfo", boom)
    monkeypatch.setattr(discovery, "_local_ip", lambda: "192.168.8.7")
    assert _real_local_ips() == ["192.168.8.7"]
    monkeypatch.setattr(discovery, "_local_ip", lambda: "0.0.0.0")
    assert _real_local_ips() == []


def test_local_ip_falls_back_when_no_route(monkeypatch):
    class NoRouteSock:
        def connect(self, *a):
            raise OSError("network unreachable")

        def getsockname(self):  # pragma: no cover - not reached on OSError
            return ("1.2.3.4", 0)

        def close(self):
            pass

    monkeypatch.setattr(discovery.socket, "socket", lambda *a: NoRouteSock())
    assert discovery._local_ip() == "0.0.0.0"


class FakeSocket:
    """Minimal socket stand-in: serves queued frames, then blocks (times out).

    Each queued item is either a frame (bytes) or a ``(frame, sender_ip)``
    pair; bare frames arrive "from" 10.0.0.1.
    """

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = 0

    def setsockopt(self, *a):
        pass

    def bind(self, *a):
        pass

    def settimeout(self, *a):
        pass

    def sendto(self, *a):
        self.sent += 1

    def recvfrom(self, _bufsize):
        if self._frames:
            item = self._frames.pop(0)
            if isinstance(item, tuple):
                return item[0], (item[1], 37020)
            return item, ("10.0.0.1", 37020)
        raise socket.timeout

    def close(self):
        pass


def test_discover_probes_with_ping_and_offline(monkeypatch):
    monkeypatch.setattr(discovery, "_local_ip", lambda: "192.168.4.7")
    monkeypatch.setattr(discovery, "_local_ips", lambda: ["192.168.4.7"])
    monkeypatch.setattr(discovery, "_probe_sockets", lambda ips: [])
    sent = []

    class RecordingSocket(FakeSocket):
        def sendto(self, data, addr):
            sent.append((data, addr))
            super().sendto(data, addr)

    monkeypatch.setattr(discovery, "_open_socket", lambda: RecordingSocket([]))
    discovery.discover(timeout=0.05)
    frames = {data for data, _addr in sent}
    # Both probe types: PING (unicast PONG comes back even through broadcast
    # filters) and OFFLINE (provokes the registry without registering us).
    assert bytes([3]) in frames
    assert bytes([5, 192, 168, 4, 7]) in frames
    # Probes go to the limited broadcast and the /24 directed broadcast.
    addrs = {addr[0] for _data, addr in sent}
    assert addrs == {"255.255.255.255", "192.168.4.255"}


def test_discover_returns_immediately_on_full_frame(monkeypatch):
    frame = full_frame(peer("10.0.0.1", "Elvira"), peer("10.0.0.2", "Pinbot"))
    monkeypatch.setattr(discovery, "_open_socket", lambda: FakeSocket([frame]))
    # A generous timeout would hang the test if the FULL frame didn't short-circuit.
    machines = discovery.discover(timeout=999)
    assert machines == [
        DiscoveredMachine("10.0.0.1", "Elvira"),
        DiscoveredMachine("10.0.0.2", "Pinbot"),
    ]


def test_discover_full_frame_dedups_by_ip(monkeypatch):
    frame = full_frame(peer("10.0.0.5", "Reg"), peer("10.0.0.5", "Reg"))
    monkeypatch.setattr(discovery, "_open_socket", lambda: FakeSocket([frame]))
    assert discovery.discover(timeout=999) == [DiscoveredMachine("10.0.0.5", "Reg")]


def test_discover_skips_non_full_frames_then_returns_on_full(monkeypatch):
    ping = bytes([3, 0])  # PING: not a board list, must be tolerated/skipped
    frame = full_frame(peer("10.0.0.7", "Elvira"))
    monkeypatch.setattr(discovery, "_open_socket", lambda: FakeSocket([ping, frame]))
    assert discovery.discover(timeout=999) == [DiscoveredMachine("10.0.0.7", "Elvira")]


def test_discover_returns_early_when_named_board_appears(monkeypatch):
    frame = full_frame(peer("10.0.0.1", "Elvira"), peer("10.0.0.2", "Pinbot"))
    monkeypatch.setattr(discovery, "_open_socket", lambda: FakeSocket([frame]))
    result = discovery.discover(timeout=999, name="pinbot")
    # Returns the moment the target appears; both accumulated peers are present.
    assert DiscoveredMachine("10.0.0.2", "Pinbot") in result


def test_discover_hello_resolves_remaining_boards_over_http(monkeypatch):
    # A lone board's HELLO is heard, but its FULL broadcast never arrives:
    # after the settle window the full list comes from /api/network/peers.
    monkeypatch.setattr(
        discovery, "_open_socket", lambda: FakeSocket([(hello_frame("Elvira"), "10.0.0.9")])
    )
    queried = []

    def fake_peers(ip):
        queried.append(ip)
        return [
            DiscoveredMachine("10.0.0.9", "Elvira"),
            DiscoveredMachine("10.0.0.4", "Pinbot"),
        ]

    monkeypatch.setattr(discovery, "_peers_over_http", fake_peers)
    machines = discovery.discover(timeout=999)
    assert queried == ["10.0.0.9"]  # asked the board we actually heard
    assert set(machines) == {
        DiscoveredMachine("10.0.0.9", "Elvira"),
        DiscoveredMachine("10.0.0.4", "Pinbot"),
    }


def test_discover_hello_returns_early_when_named_board_heard(monkeypatch):
    monkeypatch.setattr(
        discovery, "_open_socket", lambda: FakeSocket([(hello_frame("Elvira"), "10.0.0.9")])
    )
    machines = discovery.discover(timeout=999, name="elvira")
    assert machines == [DiscoveredMachine("10.0.0.9", "Elvira")]


def test_discover_pong_sighting_survives_http_failure(monkeypatch):
    # A PONG proves a board exists at that IP even when its name is unknown
    # and the HTTP fallback fails; the IP still comes back (empty name).
    monkeypatch.setattr(
        discovery, "_open_socket", lambda: FakeSocket([(bytes([4]), "10.0.0.9")])
    )

    def failing_peers(ip):
        raise OSError("unreachable")

    monkeypatch.setattr(discovery, "_peers_over_http", failing_peers)
    assert discovery.discover(timeout=999) == [DiscoveredMachine("10.0.0.9", "")]


def test_discover_ignores_own_looped_back_probes(monkeypatch):
    # Some stacks deliver our own broadcast back to us; frames from a local IP
    # must not count as board sightings.
    monkeypatch.setattr(discovery, "_local_ip", lambda: "192.168.4.7")
    monkeypatch.setattr(
        discovery, "_open_socket", lambda: FakeSocket([(bytes([3]), "192.168.4.7")])
    )
    assert discovery.discover(timeout=0.05) == []


def test_discover_times_out_with_no_replies(monkeypatch):
    # FakeSocket with no frames always raises socket.timeout; discover should
    # exhaust the (tiny) timeout and return whatever it has (nothing).
    monkeypatch.setattr(discovery, "_open_socket", lambda: FakeSocket([]))
    assert discovery.discover(timeout=0.05) == []


def test_discover_tolerates_sendto_oserror(monkeypatch):
    class NoRouteSocket(FakeSocket):
        def sendto(self, *a):
            raise OSError("no broadcast route")

    monkeypatch.setattr(discovery, "_open_socket", lambda: NoRouteSocket([]))
    # No broadcast route, no replies -> returns empty without crashing.
    assert discovery.discover(timeout=0.05) == []


def test_discover_survives_windows_connection_reset(monkeypatch):
    # Windows raises ConnectionResetError from recvfrom when an earlier *sent*
    # datagram bounced (WSAECONNRESET). That must not end discovery -- the
    # FULL frame queued behind it must still be received.
    class WindowsySocket(FakeSocket):
        def __init__(self, frames):
            super().__init__(frames)
            self._reset_once = True

        def recvfrom(self, bufsize):
            if self._reset_once:
                self._reset_once = False
                raise ConnectionResetError("bounced datagram")
            return super().recvfrom(bufsize)

    frame = full_frame(peer("10.0.0.7", "Elvira"))
    monkeypatch.setattr(discovery, "_open_socket", lambda: WindowsySocket([frame]))
    assert discovery.discover(timeout=999) == [DiscoveredMachine("10.0.0.7", "Elvira")]


def test_discover_breaks_on_recvfrom_oserror(monkeypatch):
    class BrokenSocket(FakeSocket):
        def recvfrom(self, _bufsize):
            raise OSError("socket closed")

    monkeypatch.setattr(discovery, "_open_socket", lambda: BrokenSocket([]))
    assert discovery.discover(timeout=999) == []  # OSError breaks the loop


def test_peers_over_http_parses_peer_map(monkeypatch):
    class FakeTransport:
        def __init__(self, host, timeout=None):
            assert host == "10.0.0.9"

        def request(self, path):
            assert path == "/api/network/peers"
            return {
                "10.0.0.9": {"name": "Elvira", "self": True},
                "10.0.0.4": {"name": "Pinbot", "self": False},
            }

        def close(self):
            pass

    import warpedpinball.transports.http as http

    monkeypatch.setattr(http, "HttpTransport", FakeTransport)
    machines = discovery._peers_over_http("10.0.0.9")
    assert set(machines) == {
        DiscoveredMachine("10.0.0.9", "Elvira"),
        DiscoveredMachine("10.0.0.4", "Pinbot"),
    }


def test_open_socket_binds_and_is_datagram():
    sock = discovery._open_socket()
    try:
        assert sock.family == socket.AF_INET
        assert sock.type == socket.SOCK_DGRAM
    finally:
        sock.close()


def test_probe_sockets_binds_local_ips():
    socks = discovery._probe_sockets(["127.0.0.1"])
    try:
        assert len(socks) == 1
        assert socks[0].getsockname()[0] == "127.0.0.1"
    finally:
        for s in socks:
            s.close()


def test_discover_uses_and_closes_probe_sockets(monkeypatch):
    # Per-interface probe sockets must carry probes and be closed on exit.
    monkeypatch.setattr(discovery, "_local_ip", lambda: "192.168.4.7")
    monkeypatch.setattr(discovery, "_local_ips", lambda: ["192.168.4.7"])
    probe_sock = FakeSocket([])
    probe_sock.closed = False
    probe_sock.close = lambda: setattr(probe_sock, "closed", True)
    monkeypatch.setattr(discovery, "_probe_sockets", lambda ips: [probe_sock])
    monkeypatch.setattr(discovery, "_open_socket", lambda: FakeSocket([]))
    discovery.discover(timeout=0.05)
    assert probe_sock.sent > 0
    assert probe_sock.closed


def test_discover_second_sighting_keeps_first_settle_clock(monkeypatch):
    # Two boards heard directly (PONGs from different IPs): both must come
    # back, and the settle window runs from the *first* sighting.
    monkeypatch.setattr(
        discovery,
        "_open_socket",
        lambda: FakeSocket([(bytes([4]), "10.0.0.9"), (bytes([4]), "10.0.0.4")]),
    )
    monkeypatch.setattr(discovery, "_peers_over_http", lambda ip: [])
    machines = discovery.discover(timeout=999)
    assert set(machines) == {
        DiscoveredMachine("10.0.0.9", ""),
        DiscoveredMachine("10.0.0.4", ""),
    }


def test_peers_over_http_tolerates_non_dict_payload(monkeypatch):
    class FakeTransport:
        def __init__(self, host, timeout=None):
            pass

        def request(self, path):
            return ["not", "a", "peer", "map"]

        def close(self):
            pass

    import warpedpinball.transports.http as http

    monkeypatch.setattr(http, "HttpTransport", FakeTransport)
    assert discovery._peers_over_http("10.0.0.9") == []


def test_probe_sockets_skips_unbindable_ips():
    # 203.0.113.1 (TEST-NET-3) is not a local address, so binding fails and
    # the helper must skip it rather than raise.
    socks = discovery._probe_sockets(["203.0.113.1"])
    for s in socks:  # pragma: no cover - defensive cleanup
        s.close()
    assert socks == []


def test_open_socket_falls_back_to_ephemeral_when_port_taken(monkeypatch):
    binds = []

    class FakeSock:
        family = socket.AF_INET
        type = socket.SOCK_DGRAM

        def setsockopt(self, *a):
            pass

        def bind(self, addr):
            binds.append(addr)
            if addr == ("0.0.0.0", discovery.DISCOVERY_PORT):
                raise OSError("port in use")  # first bind fails

        def close(self):
            pass

    monkeypatch.setattr(discovery.socket, "socket", lambda *a: FakeSock())
    discovery._open_socket()
    # Fell back to an ephemeral port after the fixed port was taken.
    assert binds == [("0.0.0.0", discovery.DISCOVERY_PORT), ("0.0.0.0", 0)]
