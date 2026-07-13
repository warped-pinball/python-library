#!/usr/bin/env python3
"""Verify that version strings stay in sync across the project.

There are (up to) three sources of version truth for this package:

1. ``pyproject.toml``            -> ``[project] version``
2. ``warpedpinball/__init__.py`` -> ``__version__``
3. A git release tag            -> e.g. ``v0.1.0`` or ``0.1.0``

Sources 1 and 2 must always agree, otherwise the installed package reports
a different version than the built distribution. When a release tag is
supplied (via ``--tag`` or the ``GITHUB_REF``/``GITHUB_REF_NAME`` environment
variables produced by GitHub Actions), it must also agree with the package
version so we never publish ``warpedpinball==0.1.0`` under a ``v0.2.0`` tag.

Exit status is 0 when everything matches and 1 otherwise, which makes this
usable as a CI gate.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "warpedpinball" / "__init__.py"

_INIT_VERSION_RE = re.compile(
    r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE
)


def _load_toml(path: Path) -> dict:
    """Parse a TOML file using whatever parser is available.

    ``tomllib`` ships with Python 3.11+. On 3.9/3.10 we fall back to the
    third-party ``tomli`` if installed, and finally to a tiny regex that only
    understands the ``[project] version = "..."`` line we care about.
    """
    try:
        import tomllib  # type: ignore[import-not-found]

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        pass

    try:
        import tomli  # type: ignore[import-not-found]

        return tomli.loads(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        pass

    # Minimal fallback: find the version under the [project] table.
    text = path.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if in_project:
            m = re.match(r"""version\s*=\s*["']([^"']+)["']""", stripped)
            if m:
                return {"project": {"version": m.group(1)}}
    return {}


def get_pyproject_version() -> str:
    data = _load_toml(PYPROJECT)
    try:
        return str(data["project"]["version"])
    except (KeyError, TypeError):
        raise SystemExit(f"Could not find [project].version in {PYPROJECT}") from None


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

    pyproject_version = get_pyproject_version()
    package_version = get_package_version()

    errors: list[str] = []

    if pyproject_version != package_version:
        errors.append(
            "Version mismatch between pyproject.toml and the package:\n"
            f"    pyproject.toml [project].version = {pyproject_version!r}\n"
            f"    warpedpinball.__version__         = {package_version!r}"
        )

    tag = resolve_tag(args.tag)
    if tag is None:
        if args.require_tag:
            errors.append(
                "No release tag supplied. Pass --tag or run inside a tag "
                "build (GITHUB_REF=refs/tags/...)."
            )
    elif tag != pyproject_version:
        errors.append(
            "Release tag does not match the package version:\n"
            f"    tag (normalized) = {tag!r}\n"
            f"    package version  = {pyproject_version!r}\n"
            "Update pyproject.toml and warpedpinball/__init__.py, or retag the "
            "release so they agree."
        )

    if errors:
        print("Version check FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}\n", file=sys.stderr)
        return 1

    summary = f"Version check OK: {pyproject_version}"
    if tag is not None:
        summary += f" (matches tag {tag})"
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
