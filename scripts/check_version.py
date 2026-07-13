#!/usr/bin/env python3
"""Verify that a release tag matches the package version.

The single source of truth for the version is ``warpedpinball/__init__.py``
(``__version__``); ``pyproject.toml`` reads it dynamically via Hatch. This
script compares that version against a release tag so we never publish
``warpedpinball==0.1.0`` under a ``v0.2.0`` tag.

The tag is taken from ``--tag`` or, when running in GitHub Actions, from the
``GITHUB_REF``/``GITHUB_REF_NAME`` environment variables. A leading ``v`` and
a ``refs/tags/`` prefix are both accepted.

Exit status is 0 when the versions match (or no tag is supplied and
``--require-tag`` was not passed) and 1 otherwise, so this works as a CI gate.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_PY = REPO_ROOT / "warpedpinball" / "__init__.py"

_INIT_VERSION_RE = re.compile(
    r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE
)


def get_package_version() -> str:
    m = _INIT_VERSION_RE.search(INIT_PY.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"Could not find __version__ in {INIT_PY}")
    return m.group(1)


def normalize_tag(tag: str) -> str:
    """Turn a git ref/tag into a bare version string.

    Accepts ``refs/tags/v0.1.0``, ``v0.1.0`` and ``0.1.0`` and returns
    ``0.1.0`` for all of them.
    """
    tag = tag.strip()
    if tag.startswith("refs/tags/"):
        tag = tag[len("refs/tags/") :]
    if tag.startswith("refs/heads/"):
        tag = tag[len("refs/heads/") :]
    if tag[:1] in ("v", "V"):
        tag = tag[1:]
    return tag


def resolve_tag(explicit: str | None) -> str | None:
    """Determine the release tag from CLI arg or GitHub Actions env vars."""
    if explicit:
        return normalize_tag(explicit)
    ref_type = os.environ.get("GITHUB_REF_TYPE")
    ref_name = os.environ.get("GITHUB_REF_NAME")
    if ref_type == "tag" and ref_name:
        return normalize_tag(ref_name)
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/"):
        return normalize_tag(ref)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        help="Release tag to check against (e.g. v0.1.0). "
        "Defaults to GITHUB_REF/GITHUB_REF_NAME when run in CI.",
    )
    parser.add_argument(
        "--require-tag",
        action="store_true",
        help="Fail if no tag is supplied or discoverable from the environment.",
    )
    args = parser.parse_args(argv)

    package_version = get_package_version()
    tag = resolve_tag(args.tag)

    if tag is None:
        if args.require_tag:
            print(
                "Version check FAILED: no release tag supplied. Pass --tag or "
                "run inside a tag build (GITHUB_REF=refs/tags/...).",
                file=sys.stderr,
            )
            return 1
        print(f"Version check OK: package version is {package_version} (no tag given)")
        return 0

    if tag != package_version:
        print(
            "Version check FAILED: release tag does not match the package version:\n"
            f"    tag (normalized)         = {tag!r}\n"
            f"    warpedpinball.__version__ = {package_version!r}\n"
            "Update warpedpinball/__init__.py or retag the release so they agree.",
            file=sys.stderr,
        )
        return 1

    print(f"Version check OK: {package_version} (matches tag {tag})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
