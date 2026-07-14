"""Typed exceptions for the Warped Pinball Vector client."""

from __future__ import annotations

from typing import List, Optional


class VectorError(Exception):
    """Base class for all errors raised by this library."""


class TransportError(VectorError):
    """A connection, timeout, or protocol-level failure talking to the device."""


class DeviceUnreachableError(TransportError):
    """Could not open a connection to the device.

    The address refused the connection, could not be resolved, or is not on
    the network at all (device powered off, wrong IP, different subnet). A
    subclass of :class:`TransportError`, so ``except TransportError`` still
    catches it. ``target`` is the host that was tried; ``cause`` is the
    underlying networking exception, if you want the gory details.
    """

    def __init__(
        self,
        target: str,
        detail: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ):
        self.target = target
        self.cause = cause
        message = (
            f"Could not reach the machine at {target} "
            f"(is it powered on and connected to the network?)"
        )
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class DeviceTimeoutError(TransportError):
    """The device accepted the connection but did not answer in time.

    Usually the board is busy (mid-game, applying an update) or the link is
    flaky. A subclass of :class:`TransportError`. ``target`` is the host,
    ``timeout`` the seconds waited, and ``cause`` the underlying exception.
    """

    def __init__(
        self,
        target: str,
        timeout: Optional[float] = None,
        cause: Optional[BaseException] = None,
    ):
        self.target = target
        self.timeout = timeout
        self.cause = cause
        if timeout is not None:
            message = (
                f"The machine at {target} did not respond within {timeout:g}s "
                f"(it may be busy or the connection is unstable)"
            )
        else:
            message = f"The machine at {target} did not respond in time"
        super().__init__(message)


class MachineNotFoundError(VectorError):
    """No machine matching the requested name was found during discovery.

    ``seen_names`` lists the machine names that *were* discovered, so callers
    (and error messages) can show what is actually on the network.
    """

    def __init__(self, name: str, seen_names: Optional[List[str]] = None):
        self.name = name
        self.seen_names = seen_names or []
        seen = ", ".join(self.seen_names) if self.seen_names else "none"
        super().__init__(
            f"No machine named {name!r} found on the network (machines seen: {seen})"
        )


class AmbiguousMachineError(VectorError):
    """More than one discovered machine matched the requested name."""

    def __init__(self, name: str, candidates: List[str]):
        self.name = name
        self.candidates = candidates
        super().__init__(
            f"Machine name {name!r} is ambiguous; candidates: {', '.join(candidates)}"
        )


class AuthenticationRequiredError(VectorError):
    """An authenticated route was called with no password configured.

    Raised before any network traffic. Set ``machine.password``, pass
    ``password=`` to ``connect()``, or set the ``VECTOR_PASSWORD`` env var.
    """


class AuthenticationError(VectorError):
    """The device rejected the request's credentials (HTTP 401).

    ``reason`` carries the device's ``{"error": ...}`` detail, e.g.
    ``"Bad Credentials"`` or ``"Challenge expired"``.
    """

    def __init__(self, reason: str = "authentication failed"):
        self.reason = reason
        super().__init__(reason)


class RateLimitedError(VectorError):
    """The device returned 429 while fetching an auth challenge.

    The device holds at most ~10 outstanding challenges; expired ones are
    purged on each challenge request, so retrying after a short sleep is safe.
    """


class CooldownError(VectorError):
    """The route is locked or in cooldown (HTTP 409 "Already running" / 429).

    ``retry_after`` is a best-effort hint in seconds based on the route's
    documented server-side cooldown (``/api/logs`` 10 s, ``/api/update/check``
    10 s, ``/api/adjustments/restore`` 5 s), or ``None`` when unknown.
    """

    def __init__(self, message: str, retry_after: Optional[float] = None):
        self.retry_after = retry_after
        if retry_after is not None:
            message = f"{message} (retry after ~{retry_after:g}s)"
        super().__init__(message)


class VectorServerError(VectorError):
    """The device handler raised an error (HTTP 5xx). Body carries the detail."""

    def __init__(self, message: str, status: int = 500):
        self.status = status
        super().__init__(message)


class UnsupportedFirmwareError(VectorError):
    """The route does not exist on this firmware version (HTTP 404)."""

    def __init__(self, path: str, firmware_version: Optional[str] = None):
        self.path = path
        self.firmware_version = firmware_version
        detail = f" (device firmware: {firmware_version})" if firmware_version else ""
        super().__init__(
            f"Route {path!r} is not supported by this firmware{detail}; "
            "a firmware update may be required"
        )
