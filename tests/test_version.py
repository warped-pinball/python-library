"""Guard that version strings stay consistent across the project.

These tests fail on a pull request the moment ``pyproject.toml`` and
``warpedpinball.__version__`` drift apart, long before a release is cut. The
release-time tag check lives in ``scripts/check_version.py`` and is exercised
here too so its normalization logic is covered.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import warpedpinball

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_version.py"


def _load_check_module():
    spec = importlib.util.spec_from_file_location("check_version", CHECK_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_version = _load_check_module()


def test_pyproject_matches_package_version():
    assert check_version.get_pyproject_version() == warpedpinball.__version__


def test_check_passes_without_tag():
    assert check_version.main([]) == 0


def test_check_passes_with_matching_tag():
    version = warpedpinball.__version__
    assert check_version.main(["--tag", version]) == 0
    assert check_version.main(["--tag", f"v{version}"]) == 0
    assert check_version.main(["--tag", f"refs/tags/v{version}"]) == 0


def test_check_fails_with_mismatched_tag():
    assert check_version.main(["--tag", "v99.99.99"]) == 1


def test_require_tag_without_tag_fails(monkeypatch):
    for var in ("GITHUB_REF", "GITHUB_REF_NAME", "GITHUB_REF_TYPE"):
        monkeypatch.delenv(var, raising=False)
    assert check_version.main(["--require-tag"]) == 1


def test_tag_resolved_from_github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", f"v{warpedpinball.__version__}")
    monkeypatch.delenv("GITHUB_REF", raising=False)
    assert check_version.main(["--require-tag"]) == 0


def test_normalize_tag_variants():
    assert check_version.normalize_tag("v1.2.3") == "1.2.3"
    assert check_version.normalize_tag("V1.2.3") == "1.2.3"
    assert check_version.normalize_tag("1.2.3") == "1.2.3"
    assert check_version.normalize_tag("refs/tags/v1.2.3") == "1.2.3"
