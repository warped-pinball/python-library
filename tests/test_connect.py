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
