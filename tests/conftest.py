"""Shared fakes for the warpedpinball test suite."""

from __future__ import annotations

import json
from typing import Any, Iterator, List, Optional

from warpedpinball.transports import Transport


class FakeTransport(Transport):
    """In-memory Transport that records calls and returns canned responses.

    ``responses`` maps path -> value. A value may be:
      - a plain object (returned as-is),
      - an Exception instance (raised),
      - a callable ``f(path, body)`` (its return value is used; if it returns
        an Exception instance, that is raised).
    ``streams`` maps path -> list of byte chunks for ``stream()``.
    """

    def __init__(
        self,
        responses: Optional[dict] = None,
        streams: Optional[dict] = None,
        requires_password: bool = True,
    ):
        self.responses = responses or {}
        self.streams = streams or {}
        self.requires_password = requires_password
        self.calls: List[tuple] = []  # (path, body, authenticated)
        self.stream_calls: List[tuple] = []
        self.closed = False

    def request(self, path: str, body: Any = None, authenticated: bool = False) -> Any:
        self.calls.append((path, body, authenticated))
        result = self.responses.get(path, {})
        if callable(result):
            result = result(path, body)
        if isinstance(result, Exception):
            raise result
        return result

    def stream(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Iterator[bytes]:
        self.stream_calls.append((path, body, authenticated))
        chunks = self.streams.get(path, [])
        return iter(list(chunks))

    def close(self) -> None:
        self.closed = True

    @property
    def description(self) -> str:
        return "fake:transport"


class FakeSerial:
    """Fake pyserial object for injecting into UsbTransport via ``_serial``."""

    def __init__(self, lines: Optional[List[bytes]] = None):
        self.lines = list(lines or [])
        self.written: List[bytes] = []
        self.closed = False
        self.resets = 0

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def readline(self) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        return b""  # emulates a read-timeout tick

    def reset_input_buffer(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True


class FakeResponse:
    """Stub of the requests.Response surface HttpTransport touches."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        json_data: Any = None,
        chunks: Optional[List[bytes]] = None,
    ):
        self.status_code = status_code
        if json_data is not None and not text:
            text = json.dumps(json_data)
        self.text = text
        self._json_data = json_data
        self.chunks = chunks or []
        self.closed = False

    def json(self) -> Any:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text)

    def iter_content(self, chunk_size: int = 4096) -> Iterator[bytes]:
        return iter(list(self.chunks))

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Stub of requests.Session for injecting into HttpTransport.

    ``.get`` serves the challenge route: pops from ``challenge_responses`` if
    queued, else answers 200 with ``next_challenges`` (popping when several are
    queued so retries can observe distinct challenges).
    ``.request`` pops from ``responses`` (defaults to an empty 200).
    """

    def __init__(self, challenge: str = "a1" * 32):
        self.next_challenges: List[str] = [challenge]
        self.challenge_responses: List[FakeResponse] = []
        self.responses: List[FakeResponse] = []
        self.get_calls: List[str] = []
        self.requests: List[dict] = []
        self.closed = False

    def get(self, url: str, timeout: Any = None) -> FakeResponse:
        self.get_calls.append(url)
        if self.challenge_responses:
            return self.challenge_responses.pop(0)
        challenge = (
            self.next_challenges.pop(0)
            if len(self.next_challenges) > 1
            else self.next_challenges[0]
        )
        return FakeResponse(200, json_data={"challenge": challenge})

    def request(
        self,
        method: str,
        url: str,
        data: Any = None,
        headers: Any = None,
        timeout: Any = None,
        stream: bool = False,
    ) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "data": data,
                "headers": dict(headers or {}),
                "stream": stream,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(200, text="{}")

    def close(self) -> None:
        self.closed = True
