"""HTTP transport: methods, auth flow, retries, error mapping, streaming."""

import json

import pytest
from conftest import FakeResponse, FakeSession

from warpedpinball import auth
from warpedpinball.exceptions import (
    AuthenticationError,
    AuthenticationRequiredError,
    CooldownError,
    RateLimitedError,
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
