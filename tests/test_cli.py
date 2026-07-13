"""CLI smoke tests over monkeypatched connect/discover."""

from conftest import FakeTransport

import warpedpinball
from warpedpinball.cli import main
from warpedpinball.discovery import DiscoveredMachine
from warpedpinball.exceptions import MachineNotFoundError
from warpedpinball.machine import Machine


def fake_connect(responses=None):
    def _connect(*_a, **_k):
        return Machine(FakeTransport(responses=responses or {}), password="pw")

    return _connect


def test_discover_prints_machines(monkeypatch, capsys):
    monkeypatch.setattr(
        warpedpinball,
        "discover",
        lambda timeout: [
            DiscoveredMachine("10.0.0.2", "Pinbot"),
            DiscoveredMachine("10.0.0.1", "Elvira"),
        ],
    )
    assert main(["discover"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == ["Elvira\t10.0.0.1", "Pinbot\t10.0.0.2"]


def test_discover_empty_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(warpedpinball, "discover", lambda timeout: [])
    assert main(["discover"]) == 1
    assert "No machines" in capsys.readouterr().err


def test_status_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        warpedpinball,
        "connect",
        fake_connect({"/api/game/status": {"GameActive": True}}),
    )
    assert main(["status", "elvira"]) == 0
    assert '"GameActive": true' in capsys.readouterr().out


def test_read_prints_byte(monkeypatch, capsys):
    responses = {
        "/api/address/read": lambda _p, body: {
            "offset": body["offset"],
            "values": [42] * body["count"],
        }
    }
    monkeypatch.setattr(warpedpinball, "connect", fake_connect(responses))
    assert main(["read", "elvira", "0x2134"]) == 0
    assert capsys.readouterr().out.strip() == "42"


def test_read_multiple_prints_hex(monkeypatch, capsys):
    responses = {
        "/api/address/read": lambda _p, body: {
            "offset": body["offset"],
            "values": [0xAB] * body["count"],
        }
    }
    monkeypatch.setattr(warpedpinball, "connect", fake_connect(responses))
    assert main(["read", "elvira", "0x10", "--count", "3"]) == 0
    assert capsys.readouterr().out.strip() == "ab ab ab"


def test_vector_error_exits_1_with_message(monkeypatch, capsys):
    def raising_connect(*_a, **_k):
        raise MachineNotFoundError("elvira", seen_names=["Pinbot"])

    monkeypatch.setattr(warpedpinball, "connect", raising_connect)
    assert main(["status", "elvira"]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and "Pinbot" in err


def test_machine_required_without_usb(monkeypatch, capsys):
    assert main(["status"]) == 1
    assert "machine name/IP is required" in capsys.readouterr().err
