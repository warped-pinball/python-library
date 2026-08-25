"""Origin datagram framing: signing, verification, and tamper rejection."""

import json

import pytest

from warpedpinball import origin


def test_pack_unpack_round_trip():
    secret = origin.new_secret()
    body = {"machine_id": "a1b2c3d4", "type": "game_state", "data": {"ball": 2}, "n": 7}
    assert origin.unpack(secret, origin.pack(secret, body)) == body


def test_new_secret_is_random_hex():
    assert len(origin.new_secret()) == origin.SECRET_BYTES * 2
    assert origin.new_secret() != origin.new_secret()


def test_wrong_secret_is_rejected():
    packet = origin.pack("right", {"type": "reset", "n": 1})
    with pytest.raises(origin.OriginAuthError):
        origin.unpack("wrong", packet)


def test_tampered_body_is_rejected():
    secret = origin.new_secret()
    packet = origin.pack(secret, {"type": "end_of_game", "n": 1})
    with pytest.raises(origin.OriginAuthError):
        origin.unpack(secret, packet[: origin.MAC_LEN] + b'{"type":"reset","n":1}')


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"short",
        b"0" * origin.MAC_LEN,  # signature but no body
        b"not-hex-at-all!!" + b'{"n":1}',
    ],
)
def test_malformed_frames_are_rejected(packet):
    with pytest.raises(origin.OriginAuthError):
        origin.unpack("secret", packet)


def test_non_json_and_non_object_bodies_are_rejected():
    secret = origin.new_secret()
    for body in (b"not json", json.dumps([1, 2]).encode()):
        packet = origin._mac(secret, body).encode() + body
        with pytest.raises(origin.OriginAuthError):
            origin.unpack(secret, packet)
