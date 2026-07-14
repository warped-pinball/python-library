"""HTTP transport: methods, auth flow, retries, error mapping, streaming."""

import json

import pytest
import requests
from conftest import FakeResponse, FakeSession

from warpedpinball import auth
from warpedpinball.exceptions import (
    AuthenticationError,
    AuthenticationRequiredError,
    CooldownError,
    DeviceTimeoutError,
    DeviceUnreachableError,
    RateLimitedError,
    TransportError,
    UnsupportedFirmwareError,
    VectorServerError,
)
from warpedpinball.transports import http as http_mod
from warpedpinball.transports.http import HttpTransport

CHALLENGE = "a1" * 32


def make_transport(session=None, password=None) -> HttpTransport:
    return HttpTransport("192.168.1.42", password=password, session=session or FakeSession())


def test_base_url_normalization():
    assert make_transport().base_url == "http://192.168.1.42"
    assert HttpTransport("http://10.0.0.1/", session=FakeSession()).base_url == "http://10.0.0.1"


def test_get_when_no_body_post_when_body():
    session = FakeSession()
    t = make_transport(session)
    t.request("/api/version")
    t.request("/api/scores/claim", body={"initials": "MSM"})
    assert session.requests[0]["method"] == "GET"
    assert session.requests[0]["data"] is None
    assert session.requests[1]["method"] == "POST"


def test_body_serialized_compactly_and_sent():
    session = FakeSession()
    t = make_transport(session)
    t.request("/api/x", body={"id": 0, "initials": "MSM"})
    req = session.requests[0]
    assert req["data"] == b'{"id":0,"initials":"MSM"}'
    assert req["headers"]["Content-Type"] == "application/json"


def test_auth_flow_signs_the_exact_body_string():
    session = FakeSession(challenge=CHALLENGE)
    t = make_transport(session, password="test")
    body = {"id": 0, "initials": "MSM"}
    t.request("/api/player/update", body=body, authenticated=True)

    assert session.get_calls == ["http://192.168.1.42" + auth.CHALLENGE_PATH]
    req = session.requests[0]
    body_str = json.dumps(body, separators=(",", ":"))
    assert req["data"] == body_str.encode()
    assert req["headers"][auth.CHALLENGE_HEADER] == CHALLENGE
    assert req["headers"][auth.HMAC_HEADER] == auth.sign(
        "test", CHALLENGE, "/api/player/update", body_str
    )


def test_no_password_raises_before_any_request():
    session = FakeSession()
    t = make_transport(session)  # no password
    with pytest.raises(AuthenticationRequiredError):
        t.request("/api/settings/reboot", body={}, authenticated=True)
    assert session.requests == []
    assert session.get_calls == []  # not even a challenge fetch


def test_expired_challenge_retried_once_with_fresh_challenge():
    session = FakeSession()
    session.next_challenges = ["11" * 32, "22" * 32]
    session.responses = [
        FakeResponse(401, json_data={"error": "Challenge expired"}),
        FakeResponse(200, text="{}"),
    ]
    t = make_transport(session, password="test")
    assert t.request("/api/logs", body={}, authenticated=True) == {}
    assert len(session.requests) == 2
    first = session.requests[0]["headers"][auth.CHALLENGE_HEADER]
    second = session.requests[1]["headers"][auth.CHALLENGE_HEADER]
    assert first != second  # a fresh challenge was fetched for the retry


def test_bad_credentials_not_retried():
    session = FakeSession()
    session.responses = [FakeResponse(401, json_data={"error": "Bad Credentials"})]
    t = make_transport(session, password="wrong")
    with pytest.raises(AuthenticationError, match="Bad Credentials"):
        t.request("/api/settings/reboot", body={}, authenticated=True)
    assert len(session.requests) == 1


def test_challenge_429_retried_then_rate_limited(monkeypatch):
    sleeps = []
    monkeypatch.setattr(http_mod.time, "sleep", sleeps.append)
    session = FakeSession()
    session.challenge_responses = [
        FakeResponse(429, text="Too many challenges")
    ] * (http_mod.CHALLENGE_RETRIES + 1)
    t = make_transport(session, password="test")
    with pytest.raises(RateLimitedError):
        t.request("/api/settings/reboot", body={}, authenticated=True)
    assert len(sleeps) == http_mod.CHALLENGE_RETRIES


def test_challenge_429_recovers(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)
    session = FakeSession(challenge=CHALLENGE)
    session.challenge_responses = [FakeResponse(429, text="Too many challenges")]
    t = make_transport(session, password="test")
    assert t.request("/api/settings/reboot", body={}, authenticated=True) == {}


@pytest.mark.parametrize(
    "status,body,exc",
    [
        (409, '{"error":"Already running"}', CooldownError),
        (429, '{"error":"cooldown"}', CooldownError),
        (404, "", UnsupportedFirmwareError),
        (500, '{"error":"handler blew up"}', VectorServerError),
    ],
)
def test_error_mapping(status, body, exc):
    session = FakeSession()
    session.responses = [FakeResponse(status, text=body)]
    with pytest.raises(exc):
        make_transport(session).request("/api/x")


def test_cooldown_hint_for_known_routes():
    session = FakeSession()
    session.responses = [FakeResponse(429, text='{"error":"cooldown"}')]
    session.challenge_responses = []
    t = make_transport(session, password="test")
    with pytest.raises(CooldownError) as exc_info:
        t.request("/api/logs", authenticated=True)
    assert exc_info.value.retry_after == 10.0


def test_server_error_carries_device_detail():
    session = FakeSession()
    session.responses = [FakeResponse(500, text='{"error":"handler blew up"}')]
    with pytest.raises(VectorServerError, match="handler blew up"):
        make_transport(session).request("/api/x")


def test_stream_yields_chunks():
    session = FakeSession()
    session.responses = [FakeResponse(200, chunks=[b"abc", b"def"])]
    chunks = list(make_transport(session).stream("/api/memory-snapshot"))
    assert chunks == [b"abc", b"def"]
    assert session.requests[0]["stream"] is True


def test_non_json_response_returned_as_text():
    session = FakeSession()
    session.responses = [FakeResponse(200, text="plain text")]
    assert make_transport(session).request("/api/x") == "plain text"


def test_close_closes_session():
    session = FakeSession()
    make_transport(session).close()
    assert session.closed


class RaisingSession(FakeSession):
    """FakeSession whose POST always raises the given requests exception."""

    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def request(self, *args, **kwargs):
        raise self._exc


@pytest.mark.parametrize(
    "exc,expected",
    [
        (requests.exceptions.ReadTimeout("read timed out"), DeviceTimeoutError),
        (requests.exceptions.ConnectTimeout("connect timed out"), DeviceTimeoutError),
        (requests.exceptions.ConnectionError("refused"), DeviceUnreachableError),
    ],
)
def test_timeout_and_connection_errors_are_typed(exc, expected):
    t = make_transport(RaisingSession(exc))
    with pytest.raises(expected) as exc_info:
        t.request("/api/x", body={})  # POST: no GET-retry, surfaces immediately
    err = exc_info.value
    assert isinstance(err, TransportError)  # subclass, old handlers still catch it
    assert err.cause is exc  # original preserved for debugging
    assert "192.168.1.42" in str(err)


def test_transport_error_message_is_clean_without_urllib3_noise():
    exc = requests.exceptions.ReadTimeout(
        "HTTPConnectionPool(host='192.168.1.42', port=80): Read timed out."
    )
    t = make_transport(RaisingSession(exc))
    with pytest.raises(DeviceTimeoutError) as exc_info:
        t.request("/api/x", body={})
    assert "HTTPConnectionPool" not in str(exc_info.value)


def test_transport_error_suppresses_chained_traceback():
    exc = requests.exceptions.ConnectionError("refused")
    t = make_transport(RaisingSession(exc))
    with pytest.raises(DeviceUnreachableError) as exc_info:
        t.request("/api/x", body={})
    # raised `from None`, so an uncaught error prints one short traceback
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_other_request_exception_stays_generic_transport_error():
    exc = requests.exceptions.TooManyRedirects("loop")
    t = make_transport(RaisingSession(exc))
    with pytest.raises(TransportError) as exc_info:
        t.request("/api/x", body={})
    assert not isinstance(exc_info.value, (DeviceTimeoutError, DeviceUnreachableError))
    assert "/api/x" in str(exc_info.value)


def test_description_is_base_url():
    assert make_transport().description == "http://192.168.1.42"


def test_challenge_fetch_connection_error_is_typed():
    class BadGetSession(FakeSession):
        def get(self, url, timeout=None):
            raise requests.exceptions.ConnectionError("refused")

    t = make_transport(BadGetSession(), password="pw")
    with pytest.raises(DeviceUnreachableError):
        t.request("/api/settings/reboot", body={}, authenticated=True)


def test_get_retries_once_on_connection_error_then_succeeds():
    class FlakyGetSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def request(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise requests.exceptions.ConnectionError("blip")
            return FakeResponse(200, text='{"ok": true}')

    session = FlakyGetSession()
    t = make_transport(session)
    assert t.request("/api/version") == {"ok": True}  # unauthenticated GET
    assert session.attempts == 2  # first failed, retried, second succeeded


def test_get_retry_exhausted_raises():
    exc = requests.exceptions.ConnectionError("down")
    t = make_transport(RaisingSession(exc))
    with pytest.raises(DeviceUnreachableError):
        t.request("/api/version")  # GET: one retry, then surfaces


def test_stream_error_status_raises_before_iterating():
    session = FakeSession()
    session.responses = [FakeResponse(404, text="")]
    with pytest.raises(UnsupportedFirmwareError):
        list(make_transport(session).stream("/api/memory-snapshot"))


def test_stream_skips_empty_chunks():
    session = FakeSession()
    session.responses = [FakeResponse(200, chunks=[b"", b"data", b""])]
    chunks = list(make_transport(session).stream("/api/memory-snapshot"))
    assert chunks == [b"data"]  # empty chunks filtered out


def test_stream_iter_content_error_is_typed():
    class ErroringResponse(FakeResponse):
        def iter_content(self, chunk_size=4096):
            def _gen():
                yield b"partial"
                raise requests.exceptions.ConnectionError("dropped mid-stream")

            return _gen()

    session = FakeSession()
    session.responses = [ErroringResponse(200)]
    stream = make_transport(session).stream("/api/memory-snapshot")
    with pytest.raises(DeviceUnreachableError):
        list(stream)
