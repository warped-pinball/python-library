"""Message formatting for the typed exception hierarchy."""

from warpedpinball.exceptions import (
    AmbiguousMachineError,
    CooldownError,
    DeviceTimeoutError,
    DeviceUnreachableError,
    MachineNotFoundError,
    UnsupportedFirmwareError,
    VectorServerError,
)


def test_device_unreachable_with_detail():
    exc = DeviceUnreachableError("10.0.0.1", detail="network down")
    assert "10.0.0.1" in str(exc)
    assert "network down" in str(exc)


def test_device_unreachable_without_detail():
    exc = DeviceUnreachableError("10.0.0.1")
    assert "10.0.0.1" in str(exc)
    assert exc.cause is None


def test_device_timeout_with_timeout_value():
    exc = DeviceTimeoutError("10.0.0.1", timeout=5.0)
    assert "5s" in str(exc)
    assert exc.timeout == 5.0


def test_device_timeout_without_timeout_value():
    exc = DeviceTimeoutError("10.0.0.1")
    assert "10.0.0.1" in str(exc)
    assert "did not respond in time" in str(exc)


def test_machine_not_found_lists_seen_names():
    exc = MachineNotFoundError("gorgar", seen_names=["Elvira", "Pinbot"])
    assert "gorgar" in str(exc)
    assert "Elvira" in str(exc)


def test_machine_not_found_none_seen():
    exc = MachineNotFoundError("gorgar")
    assert "none" in str(exc)
    assert exc.seen_names == []


def test_ambiguous_machine_lists_candidates():
    exc = AmbiguousMachineError("pin", ["Pin (1.1.1.1)", "Pinbot (1.1.1.2)"])
    assert "Pinbot" in str(exc)


def test_cooldown_with_retry_after():
    exc = CooldownError("/api/logs: busy", retry_after=10.0)
    assert "retry after ~10s" in str(exc)
    assert exc.retry_after == 10.0


def test_cooldown_without_retry_after():
    exc = CooldownError("/api/x: busy")
    assert exc.retry_after is None


def test_server_error_status_default():
    exc = VectorServerError("boom")
    assert exc.status == 500


def test_unsupported_firmware_with_version():
    exc = UnsupportedFirmwareError("/api/x", firmware_version="1.2.3")
    assert "1.2.3" in str(exc)
    assert "/api/x" in str(exc)
