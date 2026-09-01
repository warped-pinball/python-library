"""Machine: wrapper routes/auth flags, chunking, streaming, events, gating."""

import datetime
import json

import pytest
from conftest import FakeTransport

from warpedpinball.exceptions import (
    AuthenticationRequiredError,
    UnsupportedFirmwareError,
    VectorError,
)
from warpedpinball.machine import Machine


def make_machine(responses=None, streams=None, password="pw", requires_password=True):
    transport = FakeTransport(
        responses=responses, streams=streams, requires_password=requires_password
    )
    return Machine(transport, password=password), transport


# -- wrapper table: (call, route, authenticated) --------------------------------

WRAPPER_CASES = [
    (lambda m: m.version(), "/api/version", False),
    (lambda m: m.machine_id(), "/api/machine_id", False),
    (lambda m: m.game_name(), "/api/game/name", False),
    (lambda m: m.game_status(), "/api/game/status", False),
    (lambda m: m.active_config(), "/api/game/active_config", False),
    (lambda m: m.reboot_game(), "/api/game/reboot", True),
    (lambda m: m.reboot(), "/api/settings/reboot", True),
    (lambda m: m.leaderboard(), "/api/leaders", False),
    (lambda m: m.tournament(), "/api/tournament", False),
    (lambda m: m.reset_leaderboard(), "/api/leaders/reset", True),
    (lambda m: m.reset_tournament(), "/api/tournament/reset", True),
    (lambda m: m.claimable_scores(), "/api/scores/claimable", False),
    (lambda m: m.players(), "/api/players", False),
    (lambda m: m.update_player(0, "MSM"), "/api/player/update", True),
    (lambda m: m.check_for_updates(), "/api/update/check", False),
    (lambda m: m.wifi_status(), "/api/wifi/status", False),
    (lambda m: m.faults(), "/api/fault", False),
    (lambda m: m.export_scores(), "/api/export/scores", False),
    (lambda m: m.import_scores({"a": 1}), "/api/import/scores", True),
    (lambda m: m.adjustments(), "/api/adjustments/status", False),
    (lambda m: m.capture_adjustments(1), "/api/adjustments/capture", True),
    (lambda m: m.restore_adjustments(1), "/api/adjustments/restore", True),
    (lambda m: m.name_adjustment(1, "comp"), "/api/adjustments/name", True),
    (lambda m: m.peers(), "/api/network/peers", False),
    (lambda m: m.set_date(datetime.datetime(2026, 7, 13)), "/api/set_date", True),
    (
        lambda m: m.set_memory_broadcast(True),
        "/api/memory/toggle-broadcast",
        True,
    ),
]


@pytest.mark.parametrize(
    "invoke,route,authenticated",
    WRAPPER_CASES,
    ids=[route for _, route, _ in WRAPPER_CASES],
)
def test_wrapper_hits_route_with_auth_flag(invoke, route, authenticated):
    machine, transport = make_machine()
    invoke(machine)
    assert transport.calls == [(route, transport.calls[0][1], authenticated)]
    assert transport.calls[0][0] == route


def test_logs_is_authenticated_stream():
    machine, transport = make_machine(streams={"/api/logs": [b"log"]})
    assert list(machine.logs()) == [b"log"]
    assert transport.stream_calls == [("/api/logs", None, True)]


def test_claim_score_body():
    machine, transport = make_machine()
    machine.claim_score("MSM", 2, 1234500)
    path, body, authenticated = transport.calls[0]
    assert path == "/api/scores/claim"
    assert body == {"initials": "MSM", "player_index": 2, "score": 1234500}
    assert authenticated is False


def test_update_player_omits_full_name_when_none():
    machine, transport = make_machine()
    machine.update_player(0, "MSM")
    assert transport.calls[0][1] == {"id": 0, "initials": "MSM"}
    machine.update_player(1, "ABC", full_name="Alice B.")
    assert transport.calls[1][1] == {"id": 1, "initials": "ABC", "full_name": "Alice B."}


# -- auth preflight ----------------------------------------------------------------

def test_preflight_raises_without_password_before_any_traffic():
    machine, transport = make_machine(password=None)
    with pytest.raises(AuthenticationRequiredError):
        machine.reboot()
    assert transport.calls == []


def test_no_preflight_error_when_transport_needs_no_password():
    machine, transport = make_machine(password=None, requires_password=False)
    machine.reboot()  # USB-style transport: just works
    assert transport.calls == [("/api/settings/reboot", None, True)]


def test_empty_password_passes_preflight():
    # An empty string is a valid (empty) password, so authenticated routes work
    # rather than raising AuthenticationRequiredError.
    machine, transport = make_machine(password="")
    machine.reboot()
    assert transport.calls == [("/api/settings/reboot", None, True)]
    assert transport.password == ""


def test_empty_password_not_overridden_by_env(monkeypatch):
    # An explicit empty password wins over $VECTOR_PASSWORD; only an unset
    # (None) password falls back to the environment.
    monkeypatch.setenv("VECTOR_PASSWORD", "from-env")
    machine, _ = make_machine(password="")
    assert machine.password == ""


def test_env_var_password_fallback(monkeypatch):
    monkeypatch.setenv("VECTOR_PASSWORD", "from-env")
    machine, transport = make_machine(password=None)
    assert machine.password == "from-env"
    machine.reboot()
    assert transport.password == "from-env"


def test_password_settable_after_construction():
    machine, _ = make_machine(password=None)
    machine.password = "later"
    assert machine.password == "later"


def test_verify_password():
    from warpedpinball.exceptions import AuthenticationError

    machine, _ = make_machine(responses={"/api/auth/password_check": {"ok": True}})
    assert machine.verify_password() is True
    machine, _ = make_machine(
        responses={"/api/auth/password_check": AuthenticationError("Bad Credentials")}
    )
    assert machine.verify_password() is False


# -- memory --------------------------------------------------------------------------

def address_read_responder(memory: bytes):
    def respond(_path, body):
        offset, count = body["offset"], body["count"]
        return {"offset": offset, "values": list(memory[offset : offset + count])}

    return respond


def test_read_bytes_chunks_at_256():
    memory = bytes(range(256)) * 4
    machine, transport = make_machine(
        responses={"/api/address/read": address_read_responder(memory)}
    )
    data = machine.read_bytes(0x10, 600)
    assert data == memory[0x10 : 0x10 + 600]
    bodies = [body for _, body, _ in transport.calls]
    assert [b["count"] for b in bodies] == [256, 256, 88]
    assert [b["offset"] for b in bodies] == [0x10, 0x10 + 256, 0x10 + 512]
    assert all(authenticated for _, _, authenticated in transport.calls)


def test_write_bytes_chunks_at_256():
    machine, transport = make_machine()
    machine.write_bytes(0x20, bytes(300))
    bodies = [body for _, body, _ in transport.calls]
    assert [len(b["values"]) for b in bodies] == [256, 44]
    assert [b["offset"] for b in bodies] == [0x20, 0x20 + 256]


def test_read_bytes_single_and_range():
    memory = bytes([7] * 100)
    machine, _ = make_machine(
        responses={"/api/address/read": address_read_responder(memory)}
    )
    assert machine.read_bytes(0x10, 1) == b"\x07"
    assert machine.read_bytes(0x10, 4) == b"\x07\x07\x07\x07"


def test_read_decodes_int():
    memory = bytes(range(256))
    machine, _ = make_machine(
        responses={"/api/address/read": address_read_responder(memory)}
    )
    assert machine.read(0x05) == 5                       # single byte -> int
    assert machine.read(0x01, 2) == 0x0102               # big-endian by default
    assert machine.read(0x01, 2, byteorder="little") == 0x0201


def test_set_memory_broadcast_bodies():
    machine, transport = make_machine()
    machine.set_memory_broadcast(True, frequency_ms=250)
    machine.set_memory_broadcast(True, frequency_ms=1)  # below the firmware minimum
    machine.set_memory_broadcast(True, frequency_ms=10**6)  # above the maximum
    machine.set_memory_broadcast(True, ip="192.168.1.20")  # explicit target
    machine.set_memory_broadcast(False)
    assert [body for _, body, _ in transport.calls] == [
        {"enable": True, "frequency_ms": 250},
        {"enable": True, "frequency_ms": 10},
        {"enable": True, "frequency_ms": 60000},
        {"enable": True, "frequency_ms": 100, "ip": "192.168.1.20"},
        {"enable": False},
    ]


def test_memory_snapshot_joins_stream():
    machine, transport = make_machine(streams={"/api/memory-snapshot": [b"abc", b"def"]})
    assert machine.memory_snapshot() == b"abcdef"
    assert transport.stream_calls == [("/api/memory-snapshot", None, False)]


def test_diff_snapshots_exact():
    assert Machine.diff_snapshots(b"\x00\x01\x02", b"\x00\xff\x02") == [(1, 1, 255)]
    assert Machine.diff_snapshots(b"\x00", b"\x00\x05") == [(1, -1, 5)]
    assert Machine.diff_snapshots(b"", b"") == []


# -- updates ------------------------------------------------------------------------

def test_apply_update_streams_progress_and_uses_check_url():
    lines = [
        json.dumps({"log": "downloading", "percent": 10}).encode() + b"\n",
        json.dumps({"log": "flashing", "percent": 90}).encode(),
    ]
    machine, transport = make_machine(
        responses={"/api/update/check": {"update_available": True, "url": "http://u/fw.bin"}},
        streams={"/api/update/apply": lines},
    )
    seen = []
    records = machine.apply_update(progress=seen.append)
    assert transport.stream_calls == [
        ("/api/update/apply", {"url": "http://u/fw.bin"}, True)
    ]
    assert [r["percent"] for r in records] == [10, 90]
    assert seen == records


def test_apply_update_without_url_and_no_update_raises():
    machine, _ = make_machine(responses={"/api/update/check": {"update_available": False}})
    with pytest.raises(VectorError, match="update URL"):
        machine.apply_update()


# -- clock --------------------------------------------------------------------------

def test_set_date_sends_date_list():
    machine, transport = make_machine()
    when = datetime.datetime(2026, 7, 13, 17, 30, 45)
    machine.set_date(when)
    body = transport.calls[0][1]
    assert body == {"date": [2026, 7, 13, 17, 30, 45]}


def test_date_parses_rtc_tuple_and_iso():
    machine, _ = make_machine(
        responses={"/api/get_date": {"date": [2026, 7, 13, 0, 17, 30, 45, 0]}}
    )
    assert machine.date() == datetime.datetime(2026, 7, 13, 17, 30, 45)

    machine, _ = make_machine(responses={"/api/get_date": "2026-07-13T17:30:45"})
    assert machine.date() == datetime.datetime(2026, 7, 13, 17, 30, 45)


def test_date_unrecognized_payload_raises():
    machine, _ = make_machine(responses={"/api/get_date": {"weird": True}})
    with pytest.raises(VectorError, match="Unrecognized date"):
        machine.date()


# -- watch_game ------------------------------------------------------------------------

def test_watch_game_events(monkeypatch):
    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    statuses = [
        {"GameActive": False, "BallInPlay": 0, "Scores": [0, 0]},
        {"GameActive": True, "BallInPlay": 1, "Scores": [0, 0]},
        {"GameActive": True, "BallInPlay": 1, "Scores": [1500, 0]},
        {"GameActive": True, "BallInPlay": 2, "Scores": [1500, 0]},
        {"GameActive": False, "BallInPlay": 0, "Scores": [1500, 0]},
    ]
    it = iter(statuses)
    machine, _ = make_machine(responses={"/api/game/status": lambda _p, _b: next(it)})

    events = []
    gen = machine.watch_game(interval=0)
    while True:
        try:
            events.append(next(gen))
        except (RuntimeError, StopIteration):
            break
        if len(events) >= 5:
            break

    types = [e.type for e in events]
    assert types[0] == "game_started"
    assert "ball_changed" in types
    score_events = [e for e in events if e.type == "score_changed"]
    assert score_events and score_events[0].player == 0
    assert score_events[0].old == 0 and score_events[0].new == 1500
    assert "game_ended" in types


def test_watch_game_generic_change_falls_back():
    from warpedpinball.machine import _diff_status

    events = _diff_status({"weird": 1}, {"weird": 2})
    assert [e.type for e in events] == ["status_changed"]


# -- firmware gating / lifecycle ---------------------------------------------------------

def test_gated_404_names_firmware_version():
    machine, _ = make_machine(
        responses={
            "/api/version": {"version": "1.2.3"},
            "/api/adjustments/capture": UnsupportedFirmwareError("/api/adjustments/capture"),
        }
    )
    machine.version()
    with pytest.raises(UnsupportedFirmwareError, match="1.2.3"):
        machine.capture_adjustments(0)


def test_context_manager_closes_transport():
    machine, transport = make_machine()
    with machine:
        pass
    assert transport.closed


def test_wait_until_reachable_retries(monkeypatch):
    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    from warpedpinball.exceptions import TransportError

    attempts = []

    def flaky(_path, _body):
        attempts.append(1)
        if len(attempts) < 3:
            return TransportError("down")
        return {"version": "9"}

    machine, _ = make_machine(responses={"/api/version": flaky})
    assert machine.wait_until_reachable(timeout=5) == {"version": "9"}
    assert len(attempts) == 3


def test_repr_mentions_name_and_transport():
    machine, _ = make_machine()
    machine.name = "Elvira"
    assert "Elvira" in repr(machine)
    assert "fake:transport" in repr(machine)


def test_version_records_scalar_firmware_string():
    # Non-dict, non-None result path: firmware version stored as str(result).
    machine, _ = make_machine(responses={"/api/version": "1.9.0"})
    assert machine.version() == "1.9.0"
    assert machine._firmware_version == "1.9.0"


def test_wait_until_reachable_times_out(monkeypatch):
    from warpedpinball.exceptions import TransportError

    monkeypatch.setattr("warpedpinball.machine.time.sleep", lambda _s: None)
    # monotonic advances past the deadline immediately after first attempt.
    ticks = iter([0.0, 0.0, 100.0, 200.0])
    monkeypatch.setattr(
        "warpedpinball.machine.time.monotonic", lambda: next(ticks, 300.0)
    )
    machine, _ = make_machine(
        responses={"/api/version": TransportError("still down")}
    )
    with pytest.raises(TransportError, match="did not become reachable"):
        machine.wait_until_reachable(timeout=1)


def test_apply_update_wraps_non_json_lines_as_log():
    machine, _ = make_machine(
        responses={"/api/update/check": {"url": "http://u/fw.bin"}},
        streams={"/api/update/apply": [b"plain progress text\n"]},
        password="pw",
    )
    records = machine.apply_update()
    assert records == [{"log": "plain progress text"}]


def test_diff_status_non_list_scores_emits_single_event():
    from warpedpinball.machine import _diff_status

    events = _diff_status({"score": 100}, {"score": 250})
    score_events = [e for e in events if e.type == "score_changed"]
    assert len(score_events) == 1
    assert score_events[0].old == 100
    assert score_events[0].new == 250


def test_find_key_non_dict_returns_none():
    from warpedpinball.machine import _find_key

    assert _find_key(["not", "a", "dict"], "score") is None
    assert _find_key(None, "score") is None


def test_parse_device_date_short_rtc_list():
    from warpedpinball.machine import _parse_device_date

    # 6-element list (no weekday/sub): year, month, day, hour, minute, second.
    dt = _parse_device_date([2026, 7, 13, 17, 30, 45])
    assert dt == datetime.datetime(2026, 7, 13, 17, 30, 45)


def test_parse_device_date_bad_iso_string_raises():
    from warpedpinball.machine import _parse_device_date

    with pytest.raises(VectorError, match="Unrecognized date"):
        _parse_device_date("not-a-date")


def test_version_none_result_leaves_firmware_unset():
    machine, _ = make_machine(responses={"/api/version": None})
    assert machine.version() is None
    assert machine._firmware_version is None


def test_apply_update_non_dict_check_result_raises():
    machine, _ = make_machine(
        responses={"/api/update/check": "no structured update info"},
        password="pw",
    )
    with pytest.raises(VectorError, match="update URL"):
        machine.apply_update()


def test_iter_lines_skips_blank_lines():
    from warpedpinball.machine import _iter_lines

    lines = list(_iter_lines(iter([b"a\n\n\nb\n"])))
    assert lines == ["a", "b"]  # blank lines between newlines dropped


def test_diff_status_non_dict_inputs_yield_status_changed():
    from warpedpinball.machine import _diff_status

    events = _diff_status([1, 2], [3, 4])
    assert [e.type for e in events] == ["status_changed"]
