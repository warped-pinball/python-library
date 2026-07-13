"""AddressMap: encodings, resolution, persistence, registry lookup."""

import pytest

from warpedpinball.addresses import AddressMap


def test_define_and_resolve_by_name():
    amap = AddressMap()
    amap.define("mode_a_clock", 0x2134)
    entry = amap.resolve("mode_a_clock")
    assert (entry.offset, entry.length, entry.encoding) == (0x2134, 1, None)
    assert "mode_a_clock" in amap
    assert len(amap) == 1
    assert amap.names() == ["mode_a_clock"]


def test_resolve_raw_offset():
    entry = AddressMap().resolve(0x2000)
    assert (entry.offset, entry.length) == (0x2000, 1)


def test_unknown_name_raises_keyerror_listing_known():
    amap = AddressMap()
    amap.define("bonus", 0x2140)
    with pytest.raises(KeyError, match="bonus"):
        amap.get("nope")


def test_bad_length_rejected():
    with pytest.raises(ValueError):
        AddressMap().define("x", 0, length=0)


def test_raw_decode_single_vs_multi_byte():
    amap = AddressMap()
    amap.define("one", 0, length=1)
    amap.define("three", 0, length=3)
    assert amap.get("one").decode(b"\x05") == 5
    assert amap.get("three").decode(b"\x01\x02\x03") == b"\x01\x02\x03"


def test_bcd_roundtrip():
    amap = AddressMap()
    amap.define("score", 0x2140, length=3, encoding="bcd")
    entry = amap.get("score")
    assert entry.decode(bytes([0x12, 0x34, 0x56])) == 123456
    assert entry.encode(123456) == bytes([0x12, 0x34, 0x56])
    assert entry.encode(7) == bytes([0x00, 0x00, 0x07])


def test_bcd_overflow_rejected():
    amap = AddressMap()
    amap.define("score", 0, length=1, encoding="bcd")
    with pytest.raises(ValueError, match="does not fit"):
        amap.get("score").encode(100)


def test_le_and_be_uint():
    amap = AddressMap()
    amap.define("le", 0, length=2, encoding="le_uint")
    amap.define("be", 0, length=2, encoding="be_uint")
    assert amap.get("le").decode(b"\x01\x02") == 0x0201
    assert amap.get("le").encode(0x0201) == b"\x01\x02"
    assert amap.get("be").decode(b"\x01\x02") == 0x0102
    assert amap.get("be").encode(0x0102) == b"\x01\x02"


def test_custom_codec_pair():
    amap = AddressMap()
    amap.define(
        "custom",
        0,
        length=2,
        encoding=(lambda data: data.decode(), lambda value, length: value.encode()),
    )
    assert amap.get("custom").decode(b"hi") == "hi"
    assert amap.get("custom").encode("hi") == b"hi"


def test_unknown_string_encoding_rejected():
    amap = AddressMap()
    amap.define("x", 0, encoding="utf-99")
    with pytest.raises(ValueError, match="Unknown encoding"):
        amap.get("x").decode(b"\x00")


def test_encode_int_for_multibyte_without_encoding_rejected():
    amap = AddressMap()
    amap.define("wide", 0, length=3)
    with pytest.raises(ValueError, match="spans 3 bytes"):
        amap.get("wide").encode(5)


def test_encode_wrong_bytes_length_rejected():
    amap = AddressMap()
    amap.define("wide", 0, length=3)
    with pytest.raises(ValueError, match="3 bytes but got 2"):
        amap.get("wide").encode(b"\x01\x02")


def test_save_load_roundtrip(tmp_path):
    amap = AddressMap(active_config="elvira_l4")
    amap.define("credits", 0x2134)
    amap.define("score", 0x2140, length=3, encoding="bcd")
    path = tmp_path / "elvira.json"
    amap.save(str(path))

    loaded = AddressMap.load(str(path), active_config="elvira_l4")
    assert loaded.active_config == "elvira_l4"
    assert loaded.get("credits").offset == 0x2134
    score = loaded.get("score")
    assert (score.length, score.encoding) == (3, "bcd")


def test_load_warns_on_config_mismatch(tmp_path):
    amap = AddressMap(active_config="elvira_l4")
    amap.define("credits", 0x2134)
    path = tmp_path / "elvira.json"
    amap.save(str(path))
    with pytest.warns(UserWarning, match="offsets may be wrong"):
        AddressMap.load(str(path), active_config="pinbot_l2")


def test_save_rejects_custom_callable_encoding(tmp_path):
    amap = AddressMap()
    amap.define("custom", 0, length=1, encoding=(lambda d: d, lambda v, n: v))
    with pytest.raises(ValueError, match="cannot be serialized"):
        amap.save(str(tmp_path / "x.json"))


def test_load_registry_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "warpedpinball.addresses.REGISTRY_DIR", str(tmp_path / "addressmaps")
    )
    assert AddressMap.load_registry("no_such_config") is None


def test_load_registry_finds_map(tmp_path, monkeypatch):
    registry = tmp_path / "addressmaps"
    registry.mkdir()
    monkeypatch.setattr("warpedpinball.addresses.REGISTRY_DIR", str(registry))
    amap = AddressMap(active_config="pinbot_l2")
    amap.define("credits", 0x10)
    amap.save(str(registry / "pinbot_l2.json"))

    loaded = AddressMap.load_registry("pinbot_l2")
    assert loaded is not None
    assert loaded.get("credits").offset == 0x10
