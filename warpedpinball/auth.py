"""HMAC-SHA256 challenge/response signing for the Vector HTTP API.

Protocol (mirrors ``require_auth`` in the firmware):

1. ``GET /api/auth/challenge`` -> ``{"challenge": "<64 hex chars>"}``.
   Challenges expire after 60 seconds and are single-use.
2. ``message = challenge + path + raw_body`` where ``path`` excludes any query
   string and ``raw_body`` is the exact byte-for-byte body string sent (empty
   string if none).
3. ``signature = HMAC-SHA256(password, message)`` hex digest.
4. Send headers ``x-auth-challenge`` and ``x-auth-hmac`` with the request.
"""

from __future__ import annotations

import hashlib
import hmac

CHALLENGE_HEADER = "x-auth-challenge"
HMAC_HEADER = "x-auth-hmac"
CHALLENGE_PATH = "/api/auth/challenge"

#: 401 reasons that indicate a stale/consumed challenge and are safe to retry
#: exactly once with a fresh challenge. "Bad Credentials" is never retried.
RETRYABLE_AUTH_REASONS = ("challenge expired", "invalid challenge")


def strip_query(path: str) -> str:
    """Return the URL path without its query string.

    The firmware's HTTP server (phew) strips the query before storing
    ``request.path``, so the signature must be computed on the bare path.
    """
    return path.split("?", 1)[0]


def sign(password: str, challenge: str, path: str, body: str = "") -> str:
    """Compute the HMAC-SHA256 hex signature for a request.

    ``body`` must be the *exact* string that will be sent on the wire (the
    caller serializes JSON once, signs that string, and sends that string).
    """
    message = challenge + strip_query(path) + (body or "")
    return hmac.new(
        password.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def auth_headers(password: str, challenge: str, path: str, body: str = "") -> dict:
    """Build the two auth headers for a signed request."""
    return {
        CHALLENGE_HEADER: challenge,
        HMAC_HEADER: sign(password, challenge, path, body),
    }


def is_retryable_auth_failure(reason: str) -> bool:
    """True when a 401 reason means the challenge went stale (retry once)."""
    reason = (reason or "").lower()
    return any(r in reason for r in RETRYABLE_AUTH_REASONS)
