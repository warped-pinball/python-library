"""Transport layer: the abstract interface shared by HTTP and USB transports."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Iterator, Optional

from ..exceptions import (
    AuthenticationError,
    CooldownError,
    UnsupportedFirmwareError,
    VectorServerError,
)

#: Documented server-side cooldowns (seconds) used to enrich CooldownError.
ROUTE_COOLDOWNS = {
    "/api/logs": 10.0,
    "/api/update/check": 10.0,
    "/api/adjustments/restore": 5.0,
}


def serialize_body(body: Any) -> Optional[str]:
    """Serialize a request body to the exact string sent (and signed).

    Strings pass through untouched; dicts/lists are JSON-encoded compactly,
    exactly once — the same string must be both signed and transmitted.
    """
    if body is None:
        return None
    if isinstance(body, str):
        return body
    return json.dumps(body, separators=(",", ":"))


def parse_body(text: Any) -> Any:
    """Parse a response body: JSON when it looks like JSON, else the raw text."""
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped:
        return None
    if stripped[0] in "{[" or stripped in ("true", "false", "null") or _is_number(stripped):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    return text


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def extract_error_detail(body: Any) -> str:
    """Pull the device's error string out of a response body."""
    parsed = parse_body(body)
    if isinstance(parsed, dict):
        for key in ("error", "message", "detail"):
            if key in parsed:
                return str(parsed[key])
    if parsed is None:
        return ""
    return str(parsed)


def raise_for_status(status: int, body: Any, path: str) -> None:
    """Map a non-2xx device response to a typed exception.

    Note: 429 on the challenge route is handled separately by the HTTP
    transport (RateLimitedError with internal retry); a 429 that reaches here
    is a route cooldown.
    """
    if 200 <= status < 300:
        return
    detail = extract_error_detail(body)
    if status == 401:
        raise AuthenticationError(detail or "Unauthorized")
    if status == 404:
        raise UnsupportedFirmwareError(path)
    if status in (409, 429):
        hint = ROUTE_COOLDOWNS.get(path.split("?", 1)[0])
        msg = detail or ("Already running" if status == 409 else "Rate limited")
        raise CooldownError(f"{path}: {msg}", retry_after=hint)
    if status >= 500:
        raise VectorServerError(detail or f"Device error on {path}", status=status)
    raise VectorServerError(
        detail or f"Unexpected status {status} from {path}", status=status
    )


class Transport(ABC):
    """Abstract transport. HTTP and USB implement the same interface, so all
    ``Machine`` methods work identically over both."""

    #: True when authenticated routes need a password on this transport.
    #: (USB bypasses HMAC entirely — the firmware trusts physical access.)
    requires_password: bool = True

    #: Password used for HMAC signing (ignored by transports that don't sign).
    password: Optional[str] = None

    @abstractmethod
    def request(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Any:
        """Perform one request; return the parsed response body.

        Raises a typed exception from ``warpedpinball.exceptions`` on error.
        """

    @abstractmethod
    def stream(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Iterator[bytes]:
        """Perform a streaming request; yield raw body chunks as bytes."""

    @abstractmethod
    def close(self) -> None:
        """Release sockets / serial ports."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable target, e.g. ``http://192.168.1.42`` or ``/dev/ttyACM0``."""

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
