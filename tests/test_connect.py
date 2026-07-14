"""connect() name matching and IP handling."""

import pytest

import warpedpinball
from warpedpinball import _is_ip, _match_by_name
from warpedpinball.discovery import DiscoveredMachine
from warpedpinball.exceptions import AmbiguousMachineError, MachineNotFoundError

MACHINES = [
    DiscoveredMachine("10.0.0.1", "Elvira"),
    DiscoveredMachine("10.0.0.2", "Pinbot"),
    DiscoveredMachine("10.0.0.3", "Pinball Wizard"),
]


def test_exact_match_case_insensitive():
    assert _match_by_name("ELVIRA", MACHINES).ip == "10.0.0.1"


def test_exact_match_beats_prefix():
    machines = [DiscoveredMachine("1.1.1.1", "Pin"), DiscoveredMachine("1.1.1.2", "Pinbot")]
    assert _match_by_name("pin", machines).ip == "1.1.1.1"


def test_unique_prefix_match():
    assert _match_by_name("elv", MACHINES).ip == "10.0.0.1"


def test_ambiguous_prefix_raises_with_candidates():
    with pytest.raises(AmbiguousMachineError) as exc_info:
        _match_by_name("pin", MACHINES)
    assert len(exc_info.value.candidates) == 2


def test_unique_substring_match():
    assert _match_by_name("wizard", MACHINES).ip == "10.0.0.3"


def test_not_found_carries_seen_names():
    with pytest.raises(MachineNotFoundError) as exc_info:
        _match_by_name("gorgar", MACHINES)
    assert exc_info.value.seen_names == ["Elvira", "Pinbot", "Pinball Wizard"]


def test_is_ip():
    assert _is_ip("192.168.1.42")
    assert _is_ip("::1")
    assert not _is_ip("elvira")
    assert not _is_ip("192.168.1")


def test_connect_by_ip_skips_discovery(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("discovery must not run for an IP")

    monkeypatch.setattr(warpedpinball, "discover", boom)
    m = warpedpinball.connect("192.168.1.42", password="pw")
    assert m.transport.base_url == "http://192.168.1.42"
    assert m.password == "pw"
    m.close()


def test_connect_by_name_uses_discovery(monkeypatch):
    monkeypatch.setattr(
        warpedpinball, "discover", lambda timeout, name=None: MACHINES
    )
    m = warpedpinball.connect("elvira")
    assert m.transport.base_url == "http://10.0.0.1"
    assert m.name == "Elvira"
    m.close()


def test_ambiguous_exact_match_raises():
    machines = [
        DiscoveredMachine("1.1.1.1", "Twin"),
        DiscoveredMachine("1.1.1.2", "twin"),  # same name, different case
    ]
    with pytest.raises(AmbiguousMachineError) as exc_info:
        _match_by_name("twin", machines)
    assert len(exc_info.value.candidates) == 2


def test_ambiguous_substring_match_raises():
    machines = [
        DiscoveredMachine("1.1.1.1", "The Addams Family"),
        DiscoveredMachine("1.1.1.2", "My Family Guy"),
    ]
    # "family" is a substring of both but a prefix of neither.
    with pytest.raises(AmbiguousMachineError) as exc_info:
        _match_by_name("family", machines)
    assert len(exc_info.value.candidates) == 2


# -- connect_usb / list_serial_ports -----------------------------------------

def test_connect_usb_auto_selects_single_port(monkeypatch):
    import warpedpinball.transports.usb as usb_mod

    captured = {}

    class FakeUsbTransport:
        def __init__(self, port, timeout=10.0):
            captured["port"] = port
            captured["timeout"] = timeout

    monkeypatch.setattr(usb_mod, "list_serial_ports", lambda: ["/dev/ttyACM0"])
    monkeypatch.setattr(usb_mod, "UsbTransport", FakeUsbTransport)
    m = warpedpinball.connect_usb()
    assert captured["port"] == "/dev/ttyACM0"
    assert m.transport is not None


def test_connect_usb_explicit_port(monkeypatch):
    import warpedpinball.transports.usb as usb_mod

    captured = {}

    class FakeUsbTransport:
        def __init__(self, port, timeout=10.0):
            captured["port"] = port

    monkeypatch.setattr(usb_mod, "UsbTransport", FakeUsbTransport)
    warpedpinball.connect_usb("/dev/ttyUSB1")
    assert captured["port"] == "/dev/ttyUSB1"


def test_connect_usb_no_ports_raises(monkeypatch):
    import warpedpinball.transports.usb as usb_mod

    monkeypatch.setattr(usb_mod, "list_serial_ports", lambda: [])
    with pytest.raises(MachineNotFoundError):
        warpedpinball.connect_usb()


def test_connect_usb_multiple_ports_raises(monkeypatch):
    import warpedpinball.transports.usb as usb_mod

    monkeypatch.setattr(
        usb_mod, "list_serial_ports", lambda: ["/dev/ttyACM0", "/dev/ttyACM1"]
    )
    with pytest.raises(AmbiguousMachineError):
        warpedpinball.connect_usb()


def test_list_serial_ports_delegates(monkeypatch):
    import warpedpinball.transports.usb as usb_mod

    monkeypatch.setattr(
        usb_mod, "list_serial_ports", lambda all_ports=False: ["/dev/ttyACM0"]
    )
    assert warpedpinball.list_serial_ports() == ["/dev/ttyACM0"]
