"""warpedpinball: Python client for Warped Pinball Vector boards.

Quickstart::

    import warpedpinball

    machines = warpedpinball.discover(timeout=5)
    m = warpedpinball.connect("elvira", password="hunter2")
    print(m.leaderboard())
"""

from __future__ import annotations

import ipaddress
from typing import List, Optional

from .discovery import DiscoveredMachine, discover
from .exceptions import (
    AmbiguousMachineError,
    AuthenticationError,
    AuthenticationRequiredError,
    CooldownError,
    DeviceTimeoutError,
    DeviceUnreachableError,
    MachineNotFoundError,
    RateLimitedError,
    TransportError,
    UnsupportedFirmwareError,
    VectorError,
    VectorServerError,
)
from .machine import GameEvent, Machine
from .transports.http import HttpTransport

__version__ = "0.1.1"

__all__ = [
    "connect",
    "connect_usb",
    "discover",
    "list_serial_ports",
    "Machine",
    "GameEvent",
    "DiscoveredMachine",
    "HttpTransport",
    "VectorError",
    "TransportError",
    "DeviceUnreachableError",
    "DeviceTimeoutError",
    "MachineNotFoundError",
    "AmbiguousMachineError",
    "AuthenticationRequiredError",
    "AuthenticationError",
    "RateLimitedError",
    "CooldownError",
    "VectorServerError",
    "UnsupportedFirmwareError",
    "__version__",
]


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _match_by_name(name: str, machines: List[DiscoveredMachine]) -> DiscoveredMachine:
    """Case-insensitive: exact match first, then unique prefix, then unique
    substring. Raises MachineNotFoundError / AmbiguousMachineError."""
    lowered = name.lower()
    exact = [m for m in machines if m.name.lower() == lowered]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousMachineError(name, [f"{m.name} ({m.ip})" for m in exact])

    prefix = [m for m in machines if m.name.lower().startswith(lowered)]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        raise AmbiguousMachineError(name, [f"{m.name} ({m.ip})" for m in prefix])

    substring = [m for m in machines if lowered in m.name.lower()]
    if len(substring) == 1:
        return substring[0]
    if len(substring) > 1:
        raise AmbiguousMachineError(name, [f"{m.name} ({m.ip})" for m in substring])

    raise MachineNotFoundError(name, seen_names=[m.name for m in machines])


def connect(
    name_or_ip: str,
    password: Optional[str] = None,
    timeout: float = 5.0,
    http_timeout: float = 10.0,
) -> Machine:
    """Connect to a machine by LAN name (via UDP discovery) or by IP address.

    Name matching is case-insensitive: exact match first, then unique
    prefix/substring. Raises :class:`MachineNotFoundError` (listing the names
    that *were* seen) or :class:`AmbiguousMachineError` (listing candidates).
    """
    machine_name: Optional[str] = None
    if _is_ip(name_or_ip):
        host = name_or_ip
    else:
        found = discover(timeout=timeout, name=name_or_ip)
        match = _match_by_name(name_or_ip, found)
        host = match.ip
        machine_name = match.name

    transport = HttpTransport(host, password=password, timeout=http_timeout)
    return Machine(transport, password=password, name=machine_name)


def connect_usb(
    port: Optional[str] = None,
    timeout: float = 10.0,
) -> Machine:
    """Connect to a USB-attached machine.

    With no ``port``, auto-picks when exactly one candidate serial port
    (Raspberry Pi VID) is present. Authenticated routes need no password over
    USB; the firmware trusts physical access.
    """
    from .transports.usb import UsbTransport
    from .transports.usb import list_serial_ports as _lsp

    if port is None:
        candidates = _lsp()
        if len(candidates) == 1:
            port = candidates[0]
        elif not candidates:
            raise MachineNotFoundError("usb", seen_names=[])
        else:
            raise AmbiguousMachineError("usb", candidates)

    return Machine(UsbTransport(port, timeout=timeout))


def list_serial_ports(all_ports: bool = False) -> List[str]:
    """List serial ports likely to be Vector boards (requires the usb extra)."""
    from .transports.usb import list_serial_ports as _lsp

    return _lsp(all_ports=all_ports)
