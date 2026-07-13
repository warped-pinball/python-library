"""The :class:`Machine` object — the single place users interact with a device.

Transport-agnostic (HTTP or USB), thread-safe (one lock per machine; the
firmware is single-threaded and auth challenges are single-use, so all traffic
is serialized), and usable as a context manager.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

from .addresses import AddressMap
from .exceptions import (
    AuthenticationRequiredError,
    TransportError,
    UnsupportedFirmwareError,
    VectorError,
)
from .transports import Transport

PASSWORD_ENV_VAR = "VECTOR_PASSWORD"
#: /api/address/read caps count at 256; reads/writes are chunked to this.
ADDRESS_CHUNK = 256


@dataclass
class GameEvent:
    """A change observed by :meth:`Machine.watch_game`.

    ``type`` is one of ``game_started``, ``game_ended``, ``ball_changed``,
    ``score_changed``, ``status_changed``. ``old``/``new`` carry the values
    that changed (full status payloads for ``status_changed``); ``status`` is
    the full new status payload.
    """

    type: str
    old: Any = None
    new: Any = None
    player: Optional[int] = None
    status: Any = None


class Machine:
    """A connected Vector board.

    Usually built via :func:`warpedpinball.connect` /
    :func:`warpedpinball.connect_usb` rather than directly.
    """

    def __init__(
        self,
        transport: Transport,
        password: Optional[str] = None,
        addresses: Optional[AddressMap] = None,
        name: Optional[str] = None,
    ):
        self.transport = transport
        self._password = password
        self.addresses = addresses if addresses is not None else AddressMap()
        self.name = name
        self._lock = threading.RLock()
        self._firmware_version: Optional[str] = None

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> "Machine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.transport.close()

    def __repr__(self) -> str:
        label = self.name or "?"
        return f"<Machine {label!r} via {self.transport.description}>"

    # -- credentials -----------------------------------------------------------

    @property
    def password(self) -> Optional[str]:
        """Password for HMAC auth; falls back to $VECTOR_PASSWORD."""
        return self._password or os.environ.get(PASSWORD_ENV_VAR)

    @password.setter
    def password(self, value: Optional[str]) -> None:
        self._password = value

    def verify_password(self) -> bool:
        """Validate credentials up front via ``/api/auth/password_check``."""
        from .exceptions import AuthenticationError

        try:
            self.call("/api/auth/password_check", authenticated=True)
            return True
        except AuthenticationError:
            return False

    # -- raw escape hatch ------------------------------------------------------

    def call(self, path: str, body: Any = None, authenticated: bool = False) -> Any:
        """Perform one request and return the parsed response.

        Handles auth signing, serialization, and error mapping. Every firmware
        route is reachable through this, including ones with no wrapper yet.
        """
        with self._lock:
            self._preflight_auth(path, authenticated)
            self.transport.password = self.password
            return self.transport.request(path, body=body, authenticated=authenticated)

    def call_stream(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Iterator[bytes]:
        """Like :meth:`call` but returns an iterator of raw bytes chunks.

        The device is fully consumed while iterating; the per-machine lock is
        held until the iterator is exhausted or closed.
        """
        self._preflight_auth(path, authenticated)

        def _locked_iter() -> Iterator[bytes]:
            with self._lock:
                self.transport.password = self.password
                for chunk in self.transport.stream(
                    path, body=body, authenticated=authenticated
                ):
                    yield chunk

        return _locked_iter()

    def _preflight_auth(self, path: str, authenticated: bool) -> None:
        if (
            authenticated
            and self.transport.requires_password
            and not self.password
        ):
            raise AuthenticationRequiredError(
                f"Route {path!r} requires authentication but no password is set; "
                f"pass password= to connect(), set machine.password, or set "
                f"${PASSWORD_ENV_VAR}"
            )

    # -- device info -----------------------------------------------------------

    def version(self) -> Any:
        result = self.call("/api/version")
        if isinstance(result, dict):
            self._firmware_version = str(
                result.get("version") or result.get("Version") or result
            )
        elif result is not None:
            self._firmware_version = str(result)
        return result

    def machine_id(self) -> Any:
        return self.call("/api/machine_id")

    def game_name(self) -> Any:
        return self.call("/api/game/name")

    def game_status(self) -> Any:
        return self.call("/api/game/status")

    def active_config(self) -> Any:
        return self.call("/api/game/active_config")

    def wifi_status(self) -> Any:
        return self.call("/api/wifi/status")

    def faults(self) -> Any:
        return self.call("/api/fault")

    def peers(self) -> Any:
        """Peer table from ``GET /api/network/peers`` — discovery without
        broadcast (useful across VLANs when you know one IP)."""
        return self.call("/api/network/peers")

    # -- power -----------------------------------------------------------------

    def reboot_game(self) -> Any:
        """Power-cycle the pinball machine itself."""
        return self._call_gated("/api/game/reboot", authenticated=True)

    def reboot(self) -> Any:
        """Reboot the Vector board."""
        return self._call_gated("/api/settings/reboot", authenticated=True)

    def wait_until_reachable(self, timeout: float = 120.0, interval: float = 2.0) -> Any:
        """Poll ``/api/version`` until the board answers (after reboot/update)."""
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                return self.version()
            except VectorError as exc:
                last_error = exc
                time.sleep(interval)
        raise TransportError(
            f"Machine did not become reachable within {timeout:g}s"
        ) from last_error

    # -- scores / players --------------------------------------------------------

    def leaderboard(self) -> Any:
        return self.call("/api/leaders")

    def tournament(self) -> Any:
        return self.call("/api/tournament")

    def reset_leaderboard(self) -> Any:
        return self._call_gated("/api/leaders/reset", authenticated=True)

    def reset_tournament(self) -> Any:
        return self._call_gated("/api/tournament/reset", authenticated=True)

    def claimable_scores(self) -> Any:
        return self.call("/api/scores/claimable")

    def claim_score(self, initials: str, player_index: int, score: int) -> Any:
        return self.call(
            "/api/scores/claim",
            body={"initials": initials, "player_index": player_index, "score": score},
        )

    def players(self) -> Any:
        return self.call("/api/players")

    def update_player(
        self, id: int, initials: str, full_name: Optional[str] = None
    ) -> Any:
        body: Dict[str, Any] = {"id": id, "initials": initials}
        if full_name is not None:
            body["full_name"] = full_name
        return self._call_gated("/api/player/update", body=body, authenticated=True)

    def export_scores(self) -> Any:
        return self.call("/api/export/scores")

    def import_scores(self, data: Any) -> Any:
        return self._call_gated("/api/import/scores", body=data, authenticated=True)

    # -- updates -----------------------------------------------------------------

    def check_for_updates(self) -> Any:
        """``/api/update/check`` — note the 10 s server-side cooldown."""
        return self.call("/api/update/check")

    def apply_update(
        self,
        url: Optional[str] = None,
        progress: Optional[Callable[[dict], None]] = None,
    ) -> List[dict]:
        """Apply a firmware update, streaming progress.

        When ``url`` is omitted it is taken from :meth:`check_for_updates`.
        ``progress`` receives each ``{"log": ..., "percent": ...}`` line as it
        streams. Returns the list of all progress records.
        """
        if url is None:
            info = self.check_for_updates()
            if isinstance(info, dict):
                url = info.get("url") or info.get("update_url")
            if not url:
                raise VectorError(
                    "check_for_updates() did not report an update URL; "
                    "pass url= explicitly"
                )
        stream = self.call_stream(
            "/api/update/apply", body={"url": url}, authenticated=True
        )
        records: List[dict] = []
        for line in _iter_lines(stream):
            try:
                record = json.loads(line)
            except ValueError:
                record = {"log": line}
            records.append(record)
            if progress is not None:
                progress(record)
        return records

    # -- clock --------------------------------------------------------------------

    def date(self) -> _dt.datetime:
        """Read the device RTC as a :class:`datetime.datetime`."""
        raw = self.call("/api/get_date")
        return _parse_device_date(raw)

    def set_date(self, when: Optional[_dt.datetime] = None) -> Any:
        """Set the device RTC (defaults to the local clock now).

        Converts to the MicroPython RTC 8-tuple
        ``(year, month, day, weekday, hour, minute, second, subseconds)``.
        """
        when = when or _dt.datetime.now()
        rtc_tuple = [
            when.year,
            when.month,
            when.day,
            when.weekday(),
            when.hour,
            when.minute,
            when.second,
            0,
        ]
        return self._call_gated(
            "/api/set_date", body={"date": rtc_tuple}, authenticated=True
        )

    # -- logs ------------------------------------------------------------------------

    def logs(self) -> Iterator[bytes]:
        """Stream the device log (authenticated; 10 s server-side cooldown)."""
        return self.call_stream("/api/logs", authenticated=True)

    # -- adjustments -------------------------------------------------------------------

    def adjustments(self) -> Any:
        return self.call("/api/adjustments/status")

    def capture_adjustments(self, index: int) -> Any:
        return self._call_gated(
            "/api/adjustments/capture", body={"index": index}, authenticated=True
        )

    def restore_adjustments(self, index: int) -> Any:
        """Restore a captured adjustment profile (5 s server-side cooldown)."""
        return self._call_gated(
            "/api/adjustments/restore", body={"index": index}, authenticated=True
        )

    def name_adjustment(self, index: int, name: str) -> Any:
        return self._call_gated(
            "/api/adjustments/name", body={"index": index, "name": name},
            authenticated=True,
        )

    # -- memory ------------------------------------------------------------------------

    def read_bytes(self, offset: int, count: int) -> bytes:
        """Bulk SRAM read, auto-chunked at 256 bytes per request."""
        out = bytearray()
        remaining = count
        pos = offset
        while remaining > 0:
            chunk = min(remaining, ADDRESS_CHUNK)
            result = self.call(
                "/api/address/read",
                body={"offset": pos, "count": chunk},
                authenticated=True,
            )
            values = result["values"] if isinstance(result, dict) else result
            out.extend(values)
            pos += chunk
            remaining -= chunk
        return bytes(out)

    def write_bytes(self, offset: int, data: Union[bytes, bytearray, List[int]]) -> None:
        """Bulk SRAM write, auto-chunked at 256 bytes per request."""
        data = bytes(data)
        pos = 0
        while pos < len(data):
            chunk = data[pos : pos + ADDRESS_CHUNK]
            self.call(
                "/api/address/write",
                body={"offset": offset + pos, "values": list(chunk)},
                authenticated=True,
            )
            pos += len(chunk)

    def read(self, target: Union[str, int], count: Optional[int] = None) -> Any:
        """Read a named address (decoded per its encoding) or a raw offset.

        For raw offsets, ``count`` (default 1) selects the byte count; a single
        byte comes back as an ``int``, longer reads as ``bytes``.
        """
        entry = self.addresses.resolve(target)
        length = count if (count is not None and isinstance(target, int)) else entry.length
        data = self.read_bytes(entry.offset, length)
        if count is not None and isinstance(target, int):
            return data[0] if length == 1 else data
        return entry.decode(data)

    def write(self, target: Union[str, int], value: Any) -> None:
        """Write a named address (encoded per its encoding) or a raw offset."""
        entry = self.addresses.resolve(target)
        self.write_bytes(entry.offset, entry.encode(value))

    def memory_snapshot(self) -> bytes:
        """Full SRAM dump via the streamed ``/api/memory-snapshot`` route."""
        return b"".join(self.call_stream("/api/memory-snapshot"))

    @staticmethod
    def diff_snapshots(a: bytes, b: bytes) -> List[Tuple[int, int, int]]:
        """Compare two snapshots; returns ``(offset, a_value, b_value)`` per
        changed byte (a length difference shows up as changes vs. -1)."""
        changes: List[Tuple[int, int, int]] = []
        for i in range(max(len(a), len(b))):
            va = a[i] if i < len(a) else -1
            vb = b[i] if i < len(b) else -1
            if va != vb:
                changes.append((i, va, vb))
        return changes

    # -- polling -----------------------------------------------------------------------

    def watch_game(self, interval: float = 1.0) -> Iterator[GameEvent]:
        """Poll ``/api/game/status`` and yield change events forever.

        Keep ``interval`` >= 0.5 s to be kind to the device (enforced).
        Change detection is heuristic over common status keys; anything else
        that changes yields a generic ``status_changed`` event.
        """
        interval = max(interval, 0.5)
        prev: Any = None
        while True:
            status = self.game_status()
            if prev is not None and status != prev:
                for event in _diff_status(prev, status):
                    yield event
            prev = status
            time.sleep(interval)

    # -- internals -----------------------------------------------------------------------

    def _call_gated(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Any:
        """call() that names the firmware version on 404 (route missing)."""
        try:
            return self.call(path, body=body, authenticated=authenticated)
        except UnsupportedFirmwareError as exc:
            raise UnsupportedFirmwareError(
                exc.path, firmware_version=self._firmware_version
            ) from None


def _iter_lines(chunks: Iterator[bytes]) -> Iterator[str]:
    """Split a byte-chunk stream into decoded, non-empty lines."""
    buffer = b""
    for chunk in chunks:
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                yield text
    tail = buffer.decode("utf-8", errors="replace").strip()
    if tail:
        yield tail


def _find_key(d: Any, *fragments: str) -> Optional[str]:
    """First dict key whose lowercase form contains any fragment."""
    if not isinstance(d, dict):
        return None
    for key in d:
        lowered = str(key).lower().replace(" ", "").replace("_", "")
        for fragment in fragments:
            if fragment in lowered:
                return key
    return None


def _diff_status(prev: Any, curr: Any) -> List[GameEvent]:
    events: List[GameEvent] = []
    if isinstance(prev, dict) and isinstance(curr, dict):
        active_key = _find_key(curr, "gameactive", "ingame", "active")
        ball_key = _find_key(curr, "ball")
        score_key = _find_key(curr, "score")

        emitted = False
        if active_key is not None:
            old_active = bool(prev.get(active_key))
            new_active = bool(curr.get(active_key))
            if old_active != new_active:
                events.append(
                    GameEvent(
                        type="game_started" if new_active else "game_ended",
                        old=old_active,
                        new=new_active,
                        status=curr,
                    )
                )
                emitted = True
        if ball_key is not None and prev.get(ball_key) != curr.get(ball_key):
            events.append(
                GameEvent(
                    type="ball_changed",
                    old=prev.get(ball_key),
                    new=curr.get(ball_key),
                    status=curr,
                )
            )
            emitted = True
        if score_key is not None and prev.get(score_key) != curr.get(score_key):
            old_scores = prev.get(score_key)
            new_scores = curr.get(score_key)
            if isinstance(old_scores, list) and isinstance(new_scores, list):
                for i, (o, n) in enumerate(zip(old_scores, new_scores)):
                    if o != n:
                        events.append(
                            GameEvent(
                                type="score_changed",
                                old=o,
                                new=n,
                                player=i,
                                status=curr,
                            )
                        )
                        emitted = True
            else:
                events.append(
                    GameEvent(
                        type="score_changed",
                        old=old_scores,
                        new=new_scores,
                        status=curr,
                    )
                )
                emitted = True
        if emitted:
            return events
    return [GameEvent(type="status_changed", old=prev, new=curr, status=curr)]


def _parse_device_date(raw: Any) -> _dt.datetime:
    """Accept either an RTC tuple/list or a date string from /api/get_date."""
    if isinstance(raw, dict):
        raw = raw.get("date", raw)
    if isinstance(raw, (list, tuple)) and len(raw) >= 6:
        # MicroPython RTC: (year, month, day, weekday, hour, minute, second, sub)
        if len(raw) >= 8:
            y, mo, d, _wd, h, mi, s = raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6]
        else:
            y, mo, d, h, mi, s = raw[0], raw[1], raw[2], raw[3], raw[4], raw[5]
        return _dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    if isinstance(raw, str):
        try:
            return _dt.datetime.fromisoformat(raw)
        except ValueError:
            pass
    raise VectorError(f"Unrecognized date payload from device: {raw!r}")
