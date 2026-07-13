"""USB serial transport: framing, escaping, noise skipping, error mapping."""

import json

import pytest
from conftest import FakeSerial

from warpedpinball.exceptions import (
    AuthenticationError,
    CooldownError,
    TransportError,
    UnsupportedFirmwareError,
    VectorServerError,
)
from warpedpinball.transports.usb import (
    RESPONSE_PREFIX,
    UsbTransport,
    build_frame,
    escape_field,
)


def usb_response(status=200, body="", headers=None, route="/x") -> bytes:
    envelope = {"route": route, "status": status, "headers": headers or {}, "body": body}
    return (RESPONSE_PREFIX + json.dumps(envelope) + "\n").encode()


def make_transport(lines) -> UsbTransport:
    return UsbTransport("/dev/fake", timeout=0.5, _serial=FakeSerial(lines))


def test_escape_field():
    assert escape_field("a|b|c") == "a\\|b\\|c"
    assert escape_field("plain") == "plain"


def test_build_frame_no_body():
    assert build_frame("/api/version") == b"/api/version||\n"


def test_build_frame_with_body_and_headers():
    frame = build_frame(
        "/api/x", {"Content-Type": "application/json"}, '{"a":"p|q"}'
    )
    assert frame == b'/api/x|Content-Type: application/json|{"a":"p\\|q"}\n'


def test_request_sends_content_type_only_with_body():
    t = make_transport([usb_response(body="{}")])
    t.request("/api/version")
    assert t._serial.written == [b"/api/version||\n"]

    t = make_transport([usb_response(body="{}")])
    t.request("/api/player/update", body={"id": 0})
    written = t._serial.written[0].decode()
    assert "Content-Type: application/json" in written
    assert '{"id":0}' in written


def test_skips_console_noise_before_response():
    t = make_transport(
        [
            b"boot: starting up\n",
            b"log line with | pipes\n",
            usb_response(body='{"version":"1.2.3"}'),
        ]
    )
    assert t.request("/api/version") == {"version": "1.2.3"}


def test_json_in_string_body_is_parsed():
    t = make_transport([usb_response(body='{"a": [1, 2]}')])
    assert t.request("/api/x") == {"a": [1, 2]}


def test_non_json_body_returned_as_text():
    t = make_transport([usb_response(body="hello world")])
    assert t.request("/api/x") == "hello world"


@pytest.mark.parametrize(
    "status,body,exc",
    [
        (401, '{"error":"Bad Credentials"}', AuthenticationError),
        (409, '{"error":"Already running"}', CooldownError),
        (404, "", UnsupportedFirmwareError),
        (500, '{"error":"boom"}', VectorServerError),
    ],
)
def test_error_status_mapping(status, body, exc):
    t = make_transport([usb_response(status=status, body=body)])
    with pytest.raises(exc):
        t.request("/api/x")


def test_authenticated_flag_is_ignored_no_signing():
    t = make_transport([usb_response(body="{}")])
    assert t.requires_password is False
    t.request("/api/settings/reboot", authenticated=True)
    written = t._serial.written[0].decode()
    assert "x-auth" not in written.lower()


def test_stream_yields_single_chunk():
    t = make_transport([usb_response(body="abcdef")])
    chunks = list(t.stream("/api/memory-snapshot"))
    assert chunks == [b"abcdef"]


def test_timeout_raises_transport_error():
    t = make_transport([])  # FakeSerial returns b"" forever (timeout ticks)
    with pytest.raises(TransportError, match="Timed out"):
        t.request("/api/version")


def test_malformed_response_line_raises():
    t = make_transport([(RESPONSE_PREFIX + "not json\n").encode()])
    with pytest.raises(TransportError, match="Malformed"):
        t.request("/api/version")


def test_close_closes_port():
    t = make_transport([])
    t.close()
    assert t._serial.closed
