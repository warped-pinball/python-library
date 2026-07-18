"""HTTP transport for Vector boards (plain HTTP on port 80)."""

from __future__ import annotations

import time
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit

import requests

from .. import auth
from ..exceptions import (
    AuthenticationError,
    AuthenticationRequiredError,
    DeviceTimeoutError,
    DeviceUnreachableError,
    RateLimitedError,
    TransportError,
)
from . import Transport, parse_body, raise_for_status, serialize_body

DEFAULT_TIMEOUT = 10.0


def _is_lan_address(host: str) -> bool:
    """True for private/link-local/loopback IPs (boards always live on these)."""
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # a hostname; leave proxy behavior alone
    return ip.is_private or ip.is_link_local or ip.is_loopback
#: Retries when the device says "429 Too many challenges" (expired challenges
#: are purged on each challenge request, so a short sleep usually clears it).
CHALLENGE_RETRIES = 3
CHALLENGE_RETRY_SLEEP = 1.0


class HttpTransport(Transport):
    """Talks to a Vector at ``http://<host>`` and handles HMAC auth signing."""

    requires_password = True

    def __init__(
        self,
        host: str,
        password: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        host = host.rstrip("/")
        if not host.startswith("http://") and not host.startswith("https://"):
            host = "http://" + host
        self.base_url = host
        #: Bare host[:port] for error messages (no scheme/path noise).
        self._host_label = urlsplit(self.base_url).netloc or self.base_url
        self.password = password
        self.timeout = timeout
        if session is None:
            session = requests.Session()
            if _is_lan_address(urlsplit(self.base_url).hostname or ""):
                # Never route LAN traffic through a system/environment proxy.
                # Windows machines often have one configured (corporate, VPN,
                # WPAD auto-detect), and requests would otherwise send this
                # board's traffic to a proxy that cannot reach it.
                session.trust_env = False
        self._session = session

    @property
    def description(self) -> str:
        return self.base_url

    def close(self) -> None:
        self._session.close()

    # -- internals ---------------------------------------------------------

    def _wrap_request_exc(
        self, exc: requests.RequestException, path: str
    ) -> TransportError:
        """Turn a raw requests/urllib3 error into a clean, typed TransportError.

        Timeouts and connection failures are the common, user-facing cases and
        get their own friendly subclasses; anything else keeps a compact
        message. The original exception is preserved on ``.cause`` (and these
        are raised ``from None`` so an uncaught error prints one short
        traceback, not the full urllib3/requests stack)."""
        if isinstance(exc, requests.exceptions.Timeout):
            return DeviceTimeoutError(self._host_label, timeout=self.timeout, cause=exc)
        if isinstance(exc, requests.exceptions.ConnectionError):
            return DeviceUnreachableError(self._host_label, cause=exc)
        return TransportError(f"Request to {self._host_label}{path} failed: {exc}")

    def _fetch_challenge(self) -> str:
        """Fetch a fresh single-use challenge (never cached)."""
        for attempt in range(CHALLENGE_RETRIES + 1):
            try:
                resp = self._session.get(
                    self.base_url + auth.CHALLENGE_PATH, timeout=self.timeout
                )
            except requests.RequestException as exc:
                raise self._wrap_request_exc(exc, auth.CHALLENGE_PATH) from None
            if resp.status_code == 429:
                if attempt < CHALLENGE_RETRIES:
                    time.sleep(CHALLENGE_RETRY_SLEEP)
                    continue
                raise RateLimitedError(
                    "Device has too many outstanding auth challenges; "
                    "retry after a short wait"
                )
            raise_for_status(resp.status_code, resp.text, auth.CHALLENGE_PATH)
            data = resp.json()
            return data["challenge"]
        # Defensive: the loop above always returns or raises within the retry
        # budget, so this is unreachable in practice.
        raise RateLimitedError(  # pragma: no cover
            "Device has too many outstanding auth challenges"
        )

    def _send(
        self,
        path: str,
        body_str: Optional[str],
        authenticated: bool,
        stream: bool = False,
    ) -> requests.Response:
        headers = {}
        if body_str is not None:
            headers["Content-Type"] = "application/json"
        if authenticated:
            if not self.password:
                raise AuthenticationRequiredError(
                    f"Route {path!r} requires authentication but no password is set"
                )
            headers.update(
                auth.auth_headers(self.password, self._fetch_challenge(), path, body_str or "")
            )

        method = "GET" if body_str is None else "POST"
        url = self.base_url + path
        retries = 1 if (method == "GET" and not authenticated) else 0
        while True:
            try:
                return self._session.request(
                    method,
                    url,
                    data=body_str.encode("utf-8") if body_str is not None else None,
                    headers=headers,
                    timeout=self.timeout,
                    stream=stream,
                )
            except requests.RequestException as exc:
                if retries > 0:
                    retries -= 1
                    continue
                raise self._wrap_request_exc(exc, path) from None

    def _request_with_auth_retry(
        self, path: str, body_str: Optional[str], authenticated: bool, stream: bool
    ) -> requests.Response:
        resp = self._send(path, body_str, authenticated, stream=stream)
        if authenticated and resp.status_code == 401:
            # Challenges are single-use and expire after 60 s; a stale/consumed
            # challenge earns exactly one retry. "Bad Credentials" never does.
            try:
                raise_for_status(resp.status_code, resp.text, path)
            except AuthenticationError as exc:
                if not auth.is_retryable_auth_failure(exc.reason):
                    raise
            resp = self._send(path, body_str, authenticated, stream=stream)
        return resp

    # -- Transport interface -------------------------------------------------

    def request(self, path: str, body: Any = None, authenticated: bool = False) -> Any:
        body_str = serialize_body(body)
        resp = self._request_with_auth_retry(path, body_str, authenticated, stream=False)
        raise_for_status(resp.status_code, resp.text, path)
        return parse_body(resp.text)

    def stream(
        self, path: str, body: Any = None, authenticated: bool = False
    ) -> Iterator[bytes]:
        body_str = serialize_body(body)
        resp = self._request_with_auth_retry(path, body_str, authenticated, stream=True)
        if resp.status_code >= 300:
            text = resp.text  # small error body; safe to read
            raise_for_status(resp.status_code, text, path)

        def _iter() -> Iterator[bytes]:
            try:
                for chunk in resp.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except requests.RequestException as exc:
                raise self._wrap_request_exc(exc, path) from None
            finally:
                resp.close()

        return _iter()
