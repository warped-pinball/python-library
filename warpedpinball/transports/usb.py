"""USB serial transport for Vector boards.

The firmware tunnels the same HTTP routes over a pipe-delimited line protocol
at 115200 baud:

- Request: one line ``route|header_text|body\\n``. ``header_text`` is
  HTTP-style ``Name: value`` lines separated by ``\\n``; literal ``|`` in
  headers/body is escaped as ``\\|``.
- Response: a line prefixed ``USB API RESPONSE-->`` followed by JSON:
  ``{"route": ..., "status": int, "headers": {...}, "body": "<string>"}``.
  The firmware prints console logs to the same port, so unrelated lines must
  be skipped.

Requests over USB bypass HMAC entirely (the firmware trusts physical access),
so this transport never signs and needs no password.

Streaming responses arrive fully rendered in the ``body`` field (the firmware
joins generators before sending), so a USB "stream" is one large chunk; large
transfers like ``/api/memory-snapshot`` are buffered in memory on both ends.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator, List, Optional

from ..exceptions import TransportError
from . import Transport, parse_body, raise_for_status, serialize_body

BAUD_RATE = 115200
READ_TIMEOUT = 10.0
#: The device may reset when the port opens; give it time to come back.
SETTLE_SECONDS = 2.0
RESPONSE_PREFIX = "USB API RESPONSE-->"
#: Raspberry Pi USB vendor ID (the Pico 2W on the Vector board).
RASPBERRY_PI_VID = 0x2E8A


def _require_pyserial():
    try:
        import serial  # noqa: F401
        import serial.tools.list_ports  # noqa: F401
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "pyserial is required for USB support; "
            "install with: pip install warpedpinball[usb]"
        ) from exc
    return serial


def list_serial_ports(all_ports: bool = False) -> List[str]:
    """List serial ports likely to be Vector boards.

    Filters to the Raspberry Pi USB vendor ID (0x2E8A) unless ``all_ports``
    is true or no port carries VID information.
    """
    _require_pyserial()
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    if all_ports:
        return [p.device for p in ports]
    matches = [p.device for p in ports if getattr(p, "vid", None) == RASPBERRY_PI_VID]
    return matches


def escape_field(text: str) -> str:
    """Escape literal ``|`` as ``\\|`` for the request frame."""
    return text.replace("|", "\\|")


def build_frame(route: str, headers: Optional[dict] = None, body: str = "") -> bytes:
    """Build one request line: ``route|header_text|body\\n``."""
    header_text = "\n".join(f"{k}: {v}" for k, v in (headers or {}).items())
    line = "|".join(
        (escape_field(route), escape_field(header_text), escape_field(body or ""))
    )
    return (line + "\n").encode("utf-8")


def parse_response_line(line: str) -> dict:
    """Decode the JSON envelope after the ``USB API RESPONSE-->`` prefix."""
    payload = line.split(RESPONSE_PREFIX, 1)[1].strip()
    try:
        envelope = json.loads(payload)
    except ValueError as exc:
        raise TransportError(f"Malformed USB response: {payload[:200]!r}") from exc
    if not isinstance(envelope, dict) or "status" not in envelope:
        raise TransportError(f"Unexpected USB response envelope: {payload[:200]!r}")
    return envelope


class UsbTransport(Transport):
    """Talks to a USB-attached Vector over its serial console."""

    requires_password = False  # firmware trusts physical access; no HMAC

    def __init__(
        self,
        port: str,
        timeout: float = READ_TIMEOUT,
        settle: float = SETTLE_SECONDS,
        _serial: Any = None,
    ):
        self.port = port
        self.timeout = timeout
        if _serial is not None:
            self._serial = _serial  # injected fake for tests
        else:
            serial = _require_pyserial()
            try:
                self._serial = serial.Serial(port, BAUD_RATE, timeout=timeout)
            except serial.SerialException as exc:
                raise TransportError(f"Failed to open {port}: {exc}") from exc
            if settle:
                time.sleep(settle)

    @property
    def description(self) -> str:
        return f"usb:{self.port}"

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:  # noqa: BLE001 - closing best-effort
            pass

    # -- internals ---------------------------------------------------------

    def _exchange(self, path: str, body_str: Optional[str]) -> dict:
        headers = {}
        if body_str is not None:
            # On-device body parsing requires this header for JSON bodies.
            headers["Content-Type"] = "application/json"
        frame = build_frame(path, headers, body_str or "")
        try:
            self._serial.reset_input_buffer()
        except Exception:  # noqa: BLE001 - not all fakes/ports support it
            pass
        try:
            self._serial.write(frame)
        except Exception as exc:  # noqa: BLE001
            raise TransportError(f"USB write to {self.port} failed: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                raw = self._serial.readline()
            except Exception as exc:  # noqa: BLE001
                raise TransportError(f"USB read from {self.port} failed: {exc}") from exc
            if not raw:
                continue  # read timeout tick; keep waiting until deadline
            line = raw.decode("utf-8", errors="replace")
            if RESPONSE_PREFIX in line:
                return parse_response_line(line)
            # otherwise: firmware console noise on the shared port, so skip it
        raise TransportError(
            f"Timed out waiting for USB response to {path} on {self.port}"
        )

    # -- Transport interface -------------------------------------------------

    def request(self, path: str, body: Any = None, authenticated: bool = False) -> Any:
        # ``authenticated`` is accepted for interface parity but ignored:
        # the firmware skips HMAC for requests arriving over USB.
        body_str = serialize_body(body)
        envelope = self._exchange(path, body_str)
        raise_for_status(int(envelope.get("status", 500)), envelope.get("body", ""), path)
        return parse_body(envelope.get("body", ""))

    def stream(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Iterator[bytes]:
        # Streams arrive fully rendered in the body field over USB; yield the
        # whole thing as a single chunk (memory implication documented above).
        body_str = serialize_body(body)
        envelope = self._exchange(path, body_str)
        raise_for_status(int(envelope.get("status", 500)), envelope.get("body", ""), path)
        raw = envelope.get("body", "")
        if isinstance(raw, str):
            raw = raw.encode("utf-8")

        def _iter() -> Iterator[bytes]:
            if raw:
                yield raw

        return _iter()
