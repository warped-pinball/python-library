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


def test_version_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        warpedpinball, "connect", fake_connect({"/api/version": {"version": "1.2.3"}})
    )
    assert main(["version", "elvira"]) == 0
    assert '"version": "1.2.3"' in capsys.readouterr().out


def test_leaders_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        warpedpinball, "connect", fake_connect({"/api/leaders": [{"score": 5}]})
    )
    assert main(["leaders", "elvira"]) == 0
    assert '"score": 5' in capsys.readouterr().out


def test_print_json_non_container_prints_scalar(monkeypatch, capsys):
    # read a single byte returns a plain int -> printed directly, not JSON.
    responses = {
        "/api/game/name": "Elvira and the Party Monsters",
    }
    monkeypatch.setattr(warpedpinball, "connect", fake_connect(responses))
    # status prints game_status; use a scalar response there instead.
    monkeypatch.setattr(
        warpedpinball, "connect", fake_connect({"/api/game/status": "idle"})
    )
    assert main(["status", "elvira"]) == 0
    assert capsys.readouterr().out.strip() == "idle"


def test_write_reports_bytes_written(monkeypatch, capsys):
    written = {}

    def responder(_p, body):
        written["offset"] = body["offset"]
        written["values"] = body["values"]
        return {}

    monkeypatch.setattr(
        warpedpinball, "connect", fake_connect({"/api/address/write": responder})
    )
    assert main(["write", "elvira", "0x10", "5", "0xff"]) == 0
    out = capsys.readouterr().out
    assert "Wrote 2 byte(s) at 0x10" in out
    assert written["values"] == [5, 255]


def test_snapshot_to_file(monkeypatch, tmp_path, capsys):
    machine = Machine(FakeTransport(streams={"/api/memory-snapshot": [b"abc", b"def"]}))
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    out_file = tmp_path / "dump.bin"
    assert main(["snapshot", "elvira", "-o", str(out_file)]) == 0
    assert out_file.read_bytes() == b"abcdef"
    assert "Wrote 6 bytes" in capsys.readouterr().out


def test_snapshot_to_stdout(monkeypatch, capsys):
    machine = Machine(FakeTransport(streams={"/api/memory-snapshot": [b"\x00\x01"]}))
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    assert main(["snapshot", "elvira"]) == 0
    assert capsys.readouterr().out == "\x00\x01"


def test_usb_connects_via_connect_usb(monkeypatch, capsys):
    captured = {}

    def fake_connect_usb(port):
        captured["port"] = port
        return Machine(FakeTransport(responses={"/api/version": {"version": "9"}}))

    monkeypatch.setattr(warpedpinball, "connect_usb", fake_connect_usb)
    assert main(["version", "--usb"]) == 0
    assert captured["port"] is None  # --usb with no port -> auto-select

    monkeypatch.setattr(warpedpinball, "connect_usb", fake_connect_usb)
    assert main(["version", "--usb", "/dev/ttyACM0"]) == 0
    assert captured["port"] == "/dev/ttyACM0"


def test_update_applies_and_confirms(monkeypatch, capsys):
    stream = [
        b'{"log": "downloading", "percent": 10}\n',
        b'{"log": "done", "percent": 100}\n',
    ]
    machine = Machine(
        FakeTransport(
            responses={
                "/api/update/check": {"update_available": True, "url": "http://u/fw.bin"},
                "/api/version": {"version": "2.0.0"},
            },
            streams={"/api/update/apply": stream},
        ),
        password="pw",
    )
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    assert main(["update", "elvira", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "[ 10%] downloading" in out
    assert "Update applied" in out
    assert '"version": "2.0.0"' in out


def test_update_uses_update_url_key_when_url_absent(monkeypatch, capsys):
    machine = Machine(
        FakeTransport(
            responses={
                "/api/update/check": {"update_available": True, "update_url": "http://u/fw"},
                "/api/version": {"version": "4.0"},
            },
            streams={"/api/update/apply": [b'{"log": "ok", "percent": 100}\n']},
        ),
        password="pw",
    )
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    assert main(["update", "elvira", "--yes"]) == 0
    assert "Update applied" in capsys.readouterr().out


def test_update_explicit_url_skips_check_url_lookup(monkeypatch, capsys):
    machine = Machine(
        FakeTransport(
            responses={
                "/api/update/check": {"update_available": True},  # no url in payload
                "/api/version": {"version": "5.0"},
            },
            streams={"/api/update/apply": [b'{"log": "ok", "percent": 100}\n']},
        ),
        password="pw",
    )
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    assert main(["update", "elvira", "--yes", "--url", "http://explicit/fw"]) == 0
    assert "Update applied" in capsys.readouterr().out


def test_update_no_url_available_exits_1(monkeypatch, capsys):
    machine = Machine(
        FakeTransport(responses={"/api/update/check": {"update_available": False}})
    )
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    assert main(["update", "elvira", "--yes"]) == 1
    assert "No update URL available" in capsys.readouterr().err


def test_update_aborts_when_declined(monkeypatch, capsys):
    machine = Machine(
        FakeTransport(
            responses={"/api/update/check": {"update_available": True, "url": "http://u/fw"}}
        )
    )
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert main(["update", "elvira"]) == 1
    assert "Aborted" in capsys.readouterr().out


def test_update_confirmed_interactively(monkeypatch, capsys):
    machine = Machine(
        FakeTransport(
            responses={
                "/api/update/check": {"update_available": True, "url": "http://u/fw"},
                "/api/version": {"version": "3.0"},
            },
            streams={"/api/update/apply": [b'{"log": "ok", "percent": 100}\n']},
        ),
        password="pw",
    )
    monkeypatch.setattr(warpedpinball, "connect", lambda *_a, **_k: machine)
    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    assert main(["update", "elvira"]) == 0
    assert "Update applied" in capsys.readouterr().out


def test_keyboard_interrupt_returns_130(monkeypatch):
    def raising(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(warpedpinball, "connect", raising)
    assert main(["status", "elvira"]) == 130
