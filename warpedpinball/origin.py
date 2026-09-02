"""Origin message framing: authenticated UDP from a board to a listener.

A Vector board pushes live game events (game state, end of game, reset) as
UDP datagrams to port 6809. Historically those went out as plain JSON to the
broadcast address; every board on the network shouted at every listener, which
is both noisy enough to jam the board's WiFi chip and trivially spoofable by
anything else on the LAN.

Now a listener *registers* itself with the board over authenticated HTTP
(:meth:`warpedpinball.Machine.set_origin_target`), handing over a shared
secret. From then on the board unicasts only to that one address, and signs
every datagram with the secret.

Frame layout::

    +--------------------------+-------------------------------+
    | 16 ASCII hex chars (MAC) | UTF-8 JSON body               |
    +--------------------------+-------------------------------+

The MAC is the first 8 bytes of ``HMAC-SHA256(secret, body)``, hex-encoded.
Truncation is deliberate: the board is a 150 MHz microcontroller sending one
of these several times a second, and 64 bits of tag is far past what a LAN
attacker will brute-force in the lifetime of a session secret.

The body is a JSON object::

    {"machine_id": "a1b2c3d4", "type": "game_state", "data": {...}, "n": 41}

``n`` is a counter that increments with every datagram the board sends and
resets to zero when a listener re-registers (which also rotates the secret).
Receivers should drop any datagram whose ``n`` is not greater than the last
one accepted from that board, which is what makes a captured packet useless
to replay.
"""

from __future__ import annotations

import hmac
import json
import secrets
from hashlib import sha256
from typing import Any, Dict

from .exceptions import VectorError

#: UDP port a board sends Origin messages to.
ORIGIN_UDP_PORT = 6809
#: Length of the hex-encoded MAC prefix on every datagram.
MAC_LEN = 16
#: Bytes of secret handed to the board (as hex, so 32 characters on the wire).
SECRET_BYTES = 16


class OriginAuthError(VectorError):
    """A datagram failed authentication: bad MAC, or a malformed frame."""


def new_secret() -> str:
    """Generate a fresh registration secret (32 hex characters)."""
    return secrets.token_hex(SECRET_BYTES)


def _mac(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()[:MAC_LEN]


def pack(secret: str, body: Dict[str, Any]) -> bytes:
    """Build a signed datagram carrying ``body``.

    Mirrors what the firmware sends; used by tests and simulators.
    """
    encoded = json.dumps(body).encode("utf-8")
    return _mac(secret, encoded).encode("ascii") + encoded


def _split(packet: bytes) -> tuple[bytes, bytes]:
    """Signature and body halves of a frame, or raise on a malformed one."""
    if len(packet) <= MAC_LEN:
        raise OriginAuthError("Origin datagram too short to carry a signature")
    return packet[:MAC_LEN], packet[MAC_LEN:]


def _decode(body: bytes) -> Dict[str, Any]:
    try:
        decoded = json.loads(body)
    except ValueError as exc:
        raise OriginAuthError(f"Origin datagram body is not valid JSON: {exc}") from None
    if not isinstance(decoded, dict):
        raise OriginAuthError("Origin datagram body is not a JSON object")
    return decoded


def peek(packet: bytes) -> Dict[str, Any]:
    """Decode a datagram's body **without verifying its signature**.

    A listener holding secrets for many boards has a chicken-and-egg problem:
    it must know which board is claiming to have sent a datagram before it can
    choose the secret to check it against. This answers that question, and
    nothing else -- everything it returns is unverified and, on an open
    network, attacker-controlled.

    Use it only to route::

        machine_id = origin.peek(packet).get("machine_id")
        body = origin.unpack(secrets[machine_id], packet)   # now it's trusted

    Nothing from :func:`peek` should reach storage, a decision, or a log line
    that implies it is true.
    """
    return _decode(_split(packet)[1])


def unpack(secret: str, packet: bytes) -> Dict[str, Any]:
    """Verify and decode a datagram; raises :class:`OriginAuthError` if it
    was not signed with ``secret`` or is not a well-formed frame."""
    received, body = _split(packet)
    if not hmac.compare_digest(received.decode("ascii", "replace"), _mac(secret, body)):
        raise OriginAuthError("Origin datagram signature does not match")
    return _decode(body)
