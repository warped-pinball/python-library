"""End-to-end discovery tests against a fake board over real UDP sockets.

The unit tests in test_discovery.py exercise the frame logic with fake
sockets; these tests run :func:`warpedpinball.discover` against a real
datagram socket served by a thread that behaves like the firmware's
``discovery.py`` (branch behavior: on any frame from an unknown sender the
registry replies FULL, and a PING additionally earns a unicast PONG to the
sender's IP on the discovery port).

Everything runs on loopback: the fake board binds ``127.0.0.2:<port>``, the
client binds the wildcard address on the same port, and the "broadcast"
address is pointed at the board. Loopback UDP behaves the same across
platforms and is not subject to firewalls or routing, so a pass here means
the library's socket handling, framing, timing, and fallback logic work on
*this* OS -- and a failure in the field is the network (firewall, client
isolation, wrong interface), not the library. Run just these with::

    pytest tests/test_discovery_e2e.py -v
"""

import socket
import threading
import time

import pytest

import warpedpinball.discovery as discovery
from warpedpinball.discovery import DiscoveredMachine

BOARD_IP = "127.0.0.2"  # a second loopback address; distinct from the client's
CLIENT_IP = "127.0.0.1"


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class FakeBoard(threading.Thread):
    """A lone Vector board's discovery behavior, on a real UDP socket.

    Mirrors the firmware: a lone board is its own registry, so any frame from
    an unknown sender provokes a FULL reply (sent to the sender's IP on the
    discovery port, standing in for the firmware's broadcast), and a PING
    additionally earns a unicast PONG. ``respond_full=False`` models a network
    that eats the FULL broadcast but passes unicast -- the client then only
    ever sees the PONG.
    """

    def __init__(self, port, name="Elvira", respond_full=True):
        super().__init__(daemon=True)
        self.port = port
        self.name = name
        self.respond_full = respond_full
        self.frames_seen = []
        self._halt = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((BOARD_IP, port))  # may raise; see fixture skip
        self.sock.settimeout(0.05)

    def _full_frame(self) -> bytes:
        name_bytes = self.name.encode()
        ip_bytes = bytes(int(p) for p in BOARD_IP.split("."))
        return bytes([2, 1]) + ip_bytes + bytes([len(name_bytes)]) + name_bytes

    def run(self):
        while not self._halt.is_set():
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                return
            self.frames_seen.append(data)
            reply_to = (addr[0], self.port)
            if self.respond_full:
                self.sock.sendto(self._full_frame(), reply_to)
            if data[:1] == bytes([discovery.MSG_PING]):
                self.sock.sendto(bytes([discovery.MSG_PONG]), reply_to)

    def stop(self):
        self._halt.set()
        self.join(timeout=2)
        self.sock.close()


@pytest.fixture
def loopback_net(monkeypatch):
    """Point discover() at a loopback 'network' with a free port."""
    port = _free_udp_port()
    monkeypatch.setattr(discovery, "DISCOVERY_PORT", port)
    monkeypatch.setattr(discovery, "BROADCAST_ADDR", BOARD_IP)
    monkeypatch.setattr(discovery, "_local_ip", lambda: CLIENT_IP)
    monkeypatch.setattr(discovery, "_local_ips", lambda: [])
    return port


def _start_board(port, **kwargs) -> FakeBoard:
    try:
        board = FakeBoard(port, **kwargs)
    except OSError:  # pragma: no cover - host without a full 127/8 loopback
        pytest.skip("host cannot bind a second loopback address (127.0.0.2)")
    board.start()
    return board


def test_e2e_lone_board_is_found_quickly(loopback_net):
    board = _start_board(loopback_net)
    try:
        start = time.monotonic()
        machines = discovery.discover(timeout=10.0)
        elapsed = time.monotonic() - start
        time.sleep(0.2)  # let the board drain probes still in its buffer
    finally:
        board.stop()
    assert machines == [DiscoveredMachine(BOARD_IP, "Elvira")]
    # The board answers the first probe, so this must not burn the timeout.
    assert elapsed < 3.0
    # The board actually received our probes over the wire.
    types = {frame[0] for frame in board.frames_seen}
    assert discovery.MSG_PING in types
    assert discovery.MSG_OFFLINE in types


def test_e2e_named_lookup_matches(loopback_net):
    board = _start_board(loopback_net)
    try:
        machines = discovery.discover(timeout=10.0, name="elvira")
    finally:
        board.stop()
    assert DiscoveredMachine(BOARD_IP, "Elvira") in machines


def test_e2e_pong_only_board_found_via_http_fallback(loopback_net, monkeypatch):
    # The network eats the FULL reply; only the unicast PONG gets through.
    # The client must still find the board: PONG -> sighting -> HTTP peers.
    queried = []

    def fake_peers(ip):
        queried.append(ip)
        return [DiscoveredMachine(BOARD_IP, "Elvira")]

    monkeypatch.setattr(discovery, "_peers_over_http", fake_peers)
    board = _start_board(loopback_net, respond_full=False)
    try:
        start = time.monotonic()
        machines = discovery.discover(timeout=10.0)
        elapsed = time.monotonic() - start
    finally:
        board.stop()
    assert machines == [DiscoveredMachine(BOARD_IP, "Elvira")]
    assert queried == [BOARD_IP]
    assert elapsed < 4.0  # PONG + settle window + fallback, not the timeout


def test_e2e_silent_network_times_out_empty(loopback_net):
    # Nothing answering: discover returns [] after (a small) timeout instead
    # of hanging or crashing -- the "no boards" path over real sockets.
    machines = discovery.discover(timeout=0.5)
    assert machines == []
