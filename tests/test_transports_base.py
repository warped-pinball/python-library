"""Transport helper functions and the abstract Transport base class."""

import pytest

from warpedpinball.exceptions import (
    AuthenticationError,
    CooldownError,
    UnsupportedFirmwareError,
    VectorServerError,
)
from warpedpinball.transports import (
    Transport,
    extract_error_detail,
    parse_body,
    raise_for_status,
    serialize_body,
)

# -- serialize_body -----------------------------------------------------------

def test_serialize_body_none():
    assert serialize_body(None) is None


def test_serialize_body_str_passthrough():
    assert serialize_body("already a string") == "already a string"


def test_serialize_body_dict_is_compact():
    assert serialize_body({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_serialize_body_list():
    assert serialize_body([1, 2, 3]) == "[1,2,3]"


# -- parse_body ---------------------------------------------------------------

def test_parse_body_non_str_returned_as_is():
    obj = {"already": "parsed"}
    assert parse_body(obj) is obj


def test_parse_body_empty_is_none():
    assert parse_body("") is None
    assert parse_body("   ") is None


def test_parse_body_json_object_and_array():
    assert parse_body('{"a": 1}') == {"a": 1}
    assert parse_body("[1, 2]") == [1, 2]


def test_parse_body_literals_and_numbers():
    assert parse_body("true") is True
    assert parse_body("false") is False
    assert parse_body("null") is None
    assert parse_body("42") == 42
    assert parse_body("3.14") == 3.14


def test_parse_body_looks_like_json_but_isnt_falls_back_to_text():
    # Leading brace triggers a json.loads attempt that fails -> raw text.
    assert parse_body("{not valid json") == "{not valid json"


def test_parse_body_plain_text():
    assert parse_body("hello world") == "hello world"


# -- extract_error_detail -----------------------------------------------------

def test_extract_error_detail_prefers_error_key():
    assert extract_error_detail('{"error": "boom", "message": "x"}') == "boom"


def test_extract_error_detail_message_and_detail_keys():
    assert extract_error_detail('{"message": "m"}') == "m"
    assert extract_error_detail('{"detail": "d"}') == "d"


def test_extract_error_detail_dict_without_known_keys():
    assert extract_error_detail('{"other": 1}') == "{'other': 1}"


def test_extract_error_detail_none_body():
    assert extract_error_detail("") == ""


def test_extract_error_detail_plain_text():
    assert extract_error_detail("just text") == "just text"


# -- raise_for_status ---------------------------------------------------------

def test_raise_for_status_2xx_is_noop():
    assert raise_for_status(200, "{}", "/api/x") is None
    assert raise_for_status(204, "", "/api/x") is None


def test_raise_for_status_401():
    with pytest.raises(AuthenticationError):
        raise_for_status(401, '{"error": "Bad Credentials"}', "/api/x")


def test_raise_for_status_404():
    with pytest.raises(UnsupportedFirmwareError):
        raise_for_status(404, "", "/api/x")


def test_raise_for_status_409_and_429_cooldown():
    with pytest.raises(CooldownError):
        raise_for_status(409, "", "/api/x")
    with pytest.raises(CooldownError):
        raise_for_status(429, "", "/api/x")


def test_raise_for_status_500():
    with pytest.raises(VectorServerError) as exc:
        raise_for_status(503, '{"error": "down"}', "/api/x")
    assert exc.value.status == 503


def test_raise_for_status_unexpected_4xx():
    # e.g. 418: not one of the special-cased codes, still a server error.
    with pytest.raises(VectorServerError) as exc:
        raise_for_status(418, "", "/api/x")
    assert "418" in str(exc.value)


# -- Transport base: context manager ------------------------------------------

class _DummyTransport(Transport):
    def __init__(self):
        self.closed = False

    def request(self, path, body=None, authenticated=False):
        return None

    def stream(self, path, body=None, authenticated=False):
        return iter(())

    def close(self):
        self.closed = True

    @property
    def description(self):
        return "dummy"


def test_transport_context_manager_closes():
    t = _DummyTransport()
    with t as entered:
        assert entered is t
        assert not t.closed
    assert t.closed
