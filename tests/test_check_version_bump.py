"""Tests for scripts/check_version_bump.py version comparison logic."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_version_bump.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_version_bump", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cvb = _load()


@pytest.mark.parametrize(
    "base,head,expected",
    [
        ("0.2.1", "0.2.2", True),
        ("0.2.1", "0.3.0", True),
        ("0.2.1", "1.0.0", True),
        ("0.2.1", "0.2.1", False),  # unchanged: no bump
        ("0.2.2", "0.2.1", False),  # downgrade
        ("0.2.0rc1", "0.2.0", True),  # release supersedes its pre-release
        ("0.2.0", "0.2.0rc1", False),  # pre-release does not supersede release
    ],
)
def test_is_bump(base, head, expected):
    assert cvb.is_bump(base, head) is expected


def test_parse_version_text():
    assert cvb.parse_version_text('__version__ = "1.2.3"\n') == "1.2.3"
    assert cvb.parse_version_text("x = 1\n") is None
