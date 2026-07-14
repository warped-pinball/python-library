"""FULL/HELLO frame encoding and tolerant decoding."""

import socket

import warpedpinball.discovery as discovery
from warpedpinball.discovery import DiscoveredMachine, build_hello, parse_full


def peer(ip: str, name: str) -> bytes:
    name_bytes = name.encode()
    return bytes(int(o) for o in ip.split(".")) + bytes([len(name_bytes)]) + name_bytes


def full_frame(*peers: bytes) -> bytes:
    return bytes([2, len(peers)]) + b"".join(peers)


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


def test_build_hello():
    frame = build_hello("python-client")
    assert frame[0] == 1
    assert frame[1] == len(b"python-client")
    assert frame[2:] == b"python-client"


def test_build_hello_truncates_to_32_bytes():
    frame = build_hello("x" * 100)
    assert frame[1] == 32
    assert len(frame) == 34


class FakeSocket:
    """Minimal socket stand-in: serves queued frames, then blocks (times out)."""

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
            return self._frames.pop(0), ("10.0.0.1", 37020)
        raise socket.timeout

    def close(self):
        pass


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
