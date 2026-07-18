#!/usr/bin/env python3
"""Ensure a pull request bumps the package version.

The single source of truth for the version is ``warpedpinball/__init__.py``
(``__version__``). This gate compares the version on the current checkout
("head") against the version on the base branch and fails unless head is
strictly greater, so no change ever merges without a version bump — which is
what keeps every release publishable straight from ``main``.

The base version is read from git (``--base-ref``, default ``origin/main``);
if the base has no ``__init__.py`` yet (a brand-new package) the check passes.
Exit status is 0 when head > base (or the base is unavailable), 1 otherwise, so
it works as a CI gate.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_REL = "warpedpinball/__init__.py"
INIT_PY = REPO_ROOT / INIT_REL

_INIT_VERSION_RE = re.compile(
    r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE
)


def parse_version_text(text: str) -> str | None:
    """Extract the ``__version__`` string from an ``__init__.py`` body."""
    m = _INIT_VERSION_RE.search(text)
    return m.group(1) if m else None


def version_key(version: str) -> tuple:
    """A comparable key for a simple ``X.Y.Z[...]`` version.

    Numeric release segments compare numerically; any trailing pre-release
    (e.g. ``rc1`` in ``0.3.0rc1``) sorts *before* the same release without it,
    matching PEP 440 ordering for the cases this project uses. Prefers
    ``packaging`` when available for full correctness.
    """
    try:
        from packaging.version import Version

        return (0, Version(version))
    except Exception:
        pass
    # Lightweight fallback: split the leading numeric release from any suffix.
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", version.strip())
    if not m:
        raise ValueError(f"Unrecognized version string: {version!r}")
    release = tuple(int(p) for p in m.group(1).split("."))
    suffix = m.group(2)
    # No suffix sorts after a pre-release suffix on the same release.
    return (1, release, 1 if suffix == "" else 0, suffix)


def is_bump(base: str, head: str) -> bool:
    """True when ``head`` is a strictly higher version than ``base``."""
    return version_key(head) > version_key(base)


def head_version() -> str:
    text = INIT_PY.read_text(encoding="utf-8")
    version = parse_version_text(text)
    if version is None:
        raise SystemExit(f"Could not find __version__ in {INIT_PY}")
    return version


def base_version(base_ref: str) -> str | None:
    """Read ``__version__`` from ``base_ref`` via git, or None if unavailable."""
    try:
        text = subprocess.check_output(
            ["git", "show", f"{base_ref}:{INIT_REL}"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None  # base branch has no package file yet (new package)
    return parse_version_text(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Git ref of the base branch to compare against (default origin/main).",
    )
    args = parser.parse_args(argv)

    head = head_version()
    base = base_version(args.base_ref)

    if base is None:
        print(
            f"Version bump check OK: no base version found at {args.base_ref}; "
            f"head is {head}."
        )
        return 0

    if not is_bump(base, head):
        print(
            "Version bump check FAILED: this branch must raise the package "
            "version.\n"
            f"    base ({args.base_ref}) = {base}\n"
            f"    head                  = {head}\n"
            "Bump __version__ in warpedpinball/__init__.py above the base "
            "version before merging.",
            file=sys.stderr,
        )
        return 1

    print(f"Version bump check OK: {base} -> {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
