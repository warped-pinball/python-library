"""Optional typed views over common device payloads.

The firmware's exact JSON shapes vary by version, so ``Machine`` wrappers
return the parsed JSON as-is. These lenient dataclasses give autocomplete over
the common fields without hiding anything: every instance keeps the original
payload in ``.raw``, and unknown/missing fields simply come back ``None``.

    scores = [Score.from_raw(s) for s in m.leaderboard()]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def _pick(raw: Any, *keys: str) -> Any:
    """Case-insensitive lookup of the first present key."""
    if not isinstance(raw, dict):
        return None
    lowered = {str(k).lower(): v for k, v in raw.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


@dataclass
class Score:
    """A single leaderboard/tournament score. See :meth:`from_raw`."""

    initials: Optional[str] = None
    full_name: Optional[str] = None
    score: Optional[int] = None
    rank: Optional[int] = None
    date: Optional[str] = None
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> "Score":
        """Build a :class:`Score` from one raw device payload entry."""
        return cls(
            initials=_pick(raw, "initials"),
            full_name=_pick(raw, "full_name", "fullname", "name"),
            score=_pick(raw, "score"),
            rank=_pick(raw, "rank", "place"),
            date=_pick(raw, "date"),
            raw=raw,
        )


@dataclass
class Player:
    """A registered player record. See :meth:`from_raw`."""

    id: Optional[int] = None
    initials: Optional[str] = None
    full_name: Optional[str] = None
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, raw: Any, id: Optional[int] = None) -> "Player":
        """Build a :class:`Player` from one raw device payload entry.

        ``id`` is used as a fallback when the payload carries no id/index field.
        """
        return cls(
            id=_pick(raw, "id", "index") if _pick(raw, "id", "index") is not None else id,
            initials=_pick(raw, "initials"),
            full_name=_pick(raw, "full_name", "fullname", "name"),
            raw=raw,
        )


@dataclass
class GameStatus:
    """A snapshot of live gameplay state. See :meth:`from_raw`."""

    game_active: Optional[bool] = None
    ball_in_play: Optional[int] = None
    scores: Any = None
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> "GameStatus":
        """Build a :class:`GameStatus` from a ``/api/game/status`` payload."""
        return cls(
            game_active=_pick(raw, "game_active", "gameactive", "in_game", "active"),
            ball_in_play=_pick(raw, "ball_in_play", "ballinplay", "ball"),
            scores=_pick(raw, "scores", "score"),
            raw=raw,
        )


@dataclass
class UpdateInfo:
    """Firmware update availability. See :meth:`from_raw`."""

    current_version: Optional[str] = None
    available_version: Optional[str] = None
    url: Optional[str] = None
    update_available: Optional[bool] = None
    raw: Any = field(default=None, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> "UpdateInfo":
        """Build an :class:`UpdateInfo` from a ``/api/update/check`` payload."""
        return cls(
            current_version=_pick(raw, "current_version", "current", "version"),
            available_version=_pick(raw, "available_version", "latest", "new_version"),
            url=_pick(raw, "url", "update_url", "download_url"),
            update_available=_pick(raw, "update_available", "available"),
            raw=raw,
        )
