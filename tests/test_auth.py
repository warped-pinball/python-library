"""HMAC signing fixture tests (mirrors the firmware's require_auth)."""

import hashlib
import hmac as hmac_mod

from warpedpinball import auth

PASSWORD = "test"
CHALLENGE = "ab" * 32  # 64 hex chars
PATH = "/api/player/update"
BODY = '{"id":0,"initials":"MSM"}'


def expected(password: str, challenge: str, path: str, body: str) -> str:
    message = challenge + path + body
    return hmac_mod.new(
        password.encode(), message.encode(), hashlib.sha256
    ).hexdigest()


def test_sign_matches_reference_hmac():
    assert auth.sign(PASSWORD, CHALLENGE, PATH, BODY) == expected(
        PASSWORD, CHALLENGE, PATH, BODY
    )


def test_sign_empty_body():
    assert auth.sign(PASSWORD, CHALLENGE, PATH) == expected(
        PASSWORD, CHALLENGE, PATH, ""
    )


def test_sign_strips_query_string():
    signed = auth.sign(PASSWORD, CHALLENGE, PATH + "?x=1", BODY)
    assert signed == expected(PASSWORD, CHALLENGE, PATH, BODY)


def test_sign_known_digest():
    # Frozen golden value so a refactor changing the message layout fails loudly.
    assert (
        auth.sign("test", "00" * 32, "/api/logs", "")
        == hmac_mod.new(
            b"test", ("00" * 32 + "/api/logs").encode(), hashlib.sha256
        ).hexdigest()
    )


def test_auth_headers_shape():
    headers = auth.auth_headers(PASSWORD, CHALLENGE, PATH, BODY)
    assert headers[auth.CHALLENGE_HEADER] == CHALLENGE
    assert headers[auth.HMAC_HEADER] == expected(PASSWORD, CHALLENGE, PATH, BODY)
    assert set(headers) == {auth.CHALLENGE_HEADER, auth.HMAC_HEADER}


def test_retryable_auth_reasons():
    assert auth.is_retryable_auth_failure("Challenge expired")
    assert auth.is_retryable_auth_failure("Invalid challenge")
    assert auth.is_retryable_auth_failure("invalid CHALLENGE provided")
    assert not auth.is_retryable_auth_failure("Bad Credentials")
    assert not auth.is_retryable_auth_failure("")
    assert not auth.is_retryable_auth_failure(None)
