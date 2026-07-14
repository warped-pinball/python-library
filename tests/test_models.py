"""Typed payload views: lenient, case-insensitive field extraction."""

from warpedpinball.models import GameStatus, Player, Score, UpdateInfo, _pick


def test_pick_case_insensitive_and_first_present():
    raw = {"FullName": "Alice", "name": "ignored-because-fullname-wins"}
    assert _pick(raw, "full_name", "fullname", "name") == "Alice"


def test_pick_non_dict_returns_none():
    assert _pick(None, "x") is None
    assert _pick([1, 2, 3], "x") is None
    assert _pick("string", "x") is None


def test_pick_missing_returns_none():
    assert _pick({"a": 1}, "b", "c") is None


def test_score_from_raw_full():
    s = Score.from_raw(
        {"initials": "MSM", "Name": "Max", "score": 123, "place": 1, "date": "2026-07-13"}
    )
    assert s.initials == "MSM"
    assert s.full_name == "Max"  # via "name"
    assert s.score == 123
    assert s.rank == 1  # via "place"
    assert s.date == "2026-07-13"
    assert s.raw is not None


def test_score_from_raw_missing_fields_are_none():
    s = Score.from_raw({})
    assert s.initials is None
    assert s.full_name is None
    assert s.score is None
    assert s.rank is None


def test_score_from_raw_non_dict():
    s = Score.from_raw("garbage")
    assert s.initials is None
    assert s.raw == "garbage"


def test_player_from_raw_prefers_payload_id_over_arg():
    p = Player.from_raw({"index": 7, "initials": "ABC"}, id=99)
    assert p.id == 7  # payload "index" wins over the passed-in id
    assert p.initials == "ABC"


def test_player_from_raw_falls_back_to_arg_id():
    p = Player.from_raw({"initials": "ABC", "fullname": "Al"}, id=42)
    assert p.id == 42
    assert p.full_name == "Al"


def test_player_from_raw_no_id_anywhere():
    p = Player.from_raw({"initials": "ABC"})
    assert p.id is None


def test_game_status_from_raw():
    g = GameStatus.from_raw({"GameActive": True, "ball": 2, "scores": [10, 20]})
    assert g.game_active is True
    assert g.ball_in_play == 2
    assert g.scores == [10, 20]


def test_game_status_alternate_keys():
    g = GameStatus.from_raw({"in_game": False, "BallInPlay": 3, "score": [1]})
    assert g.game_active is False
    assert g.ball_in_play == 3
    assert g.scores == [1]


def test_update_info_from_raw():
    u = UpdateInfo.from_raw(
        {
            "current": "1.0.0",
            "latest": "1.1.0",
            "download_url": "http://u/fw.bin",
            "available": True,
        }
    )
    assert u.current_version == "1.0.0"
    assert u.available_version == "1.1.0"
    assert u.url == "http://u/fw.bin"
    assert u.update_available is True


def test_update_info_empty():
    u = UpdateInfo.from_raw({})
    assert u.current_version is None
    assert u.url is None
    assert u.update_available is None
