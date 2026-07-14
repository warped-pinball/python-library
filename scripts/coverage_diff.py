#!/usr/bin/env python3
"""Summarize coverage and flag pull requests that lower it.

The CI ``coverage`` job runs the test suite under coverage twice: once on the
pull request and once on its base branch. Each run produces a coverage JSON
report (``coverage.py``'s ``--cov-report=json`` / ``json`` format). This script
reads the PR report and, when a base report is supplied, compares the two.

It does three things:

* prints a human-readable summary to stdout;
* writes a Markdown comment (``--comment-file``) that CI posts on the PR;
* when running inside GitHub Actions, appends the same summary to the job
  summary (``$GITHUB_STEP_SUMMARY``) and writes machine-readable results to
  ``$GITHUB_OUTPUT`` -- notably ``decreased=true|false`` so a later workflow
  step can fail the check.

The script itself exits 0 even when coverage drops (so the comment still gets
posted); pass ``--fail-on-decrease`` to make it a hard gate when run locally.
Total coverage is compared with a small tolerance to ignore floating-point
noise; see ``--tolerance``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple


def _load_totals_and_files(path: Path) -> Tuple[Optional[float], Dict[str, float]]:
    """Return ``(total_percent, {file: percent})`` for a coverage JSON report.

    A missing or unparseable report yields ``(None, {})`` so the caller can
    treat "no base data" the same as "base branch had no coverage yet".
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}

    totals = data.get("totals") or {}
    total = totals.get("percent_covered")
    per_file = {
        name: info.get("summary", {}).get("percent_covered", 0.0)
        for name, info in (data.get("files") or {}).items()
    }
    return total, per_file


def _fmt(pct: Optional[float]) -> str:
    return "n/a" if pct is None else f"{pct:.2f}%"


def _fmt_delta(delta: float) -> str:
    arrow = "\N{UPWARDS BLACK ARROW}" if delta > 0 else "\N{DOWNWARDS BLACK ARROW}"
    if delta == 0:
        return "0.00%"
    return f"{arrow} {delta:+.2f}%"


def build_report(
    head: Path,
    base: Optional[Path],
    tolerance: float,
) -> Tuple[str, bool, Optional[float], Optional[float]]:
    """Build the Markdown report.

    Returns ``(markdown, decreased, head_total, base_total)`` where
    ``decreased`` is True only when a base report was supplied and total
    coverage dropped by more than ``tolerance`` percentage points.
    """
    head_total, head_files = _load_totals_and_files(head)
    if head_total is None:
        return (
            "## Coverage report\n\n"
            f":warning: Could not read coverage report `{head}`.\n",
            False,
            None,
            None,
        )

    lines = ["## Coverage report", ""]

    if base is None:
        lines.append(f"Total coverage: **{_fmt(head_total)}**")
        return "\n".join(lines) + "\n", False, head_total, None

    base_total, base_files = _load_totals_and_files(base)
    if base_total is None:
        # No comparable base data (e.g. first run on a new default branch).
        lines.append(f"Total coverage: **{_fmt(head_total)}** (no base coverage to compare)")
        return "\n".join(lines) + "\n", False, head_total, None

    delta = head_total - base_total
    decreased = delta < -tolerance

    banner = ":white_check_mark:"
    if decreased:
        banner = ":x: **Coverage decreased**"
    elif delta > tolerance:
        banner = ":tada: Coverage increased"

    lines.append(
        f"{banner}\n\n"
        f"Total coverage: **{_fmt(head_total)}** "
        f"({_fmt_delta(delta)} vs base `{_fmt(base_total)}`)"
    )

    # Per-file breakdown, limited to files whose coverage actually moved.
    changed = []
    for name in sorted(set(head_files) | set(base_files)):
        h = head_files.get(name)
        b = base_files.get(name)
        if h is None:  # file removed on the PR
            continue
        b_val = b if b is not None else 0.0
        file_delta = h - b_val
        if abs(file_delta) > tolerance:
            changed.append((name, b, h, file_delta))

    if changed:
        lines += [
            "",
            "<details><summary>Files with changed coverage</summary>",
            "",
            "| File | Base | Head | \N{GREEK CAPITAL LETTER DELTA} |",
            "| ---- | ---: | ---: | ---: |",
        ]
        for name, b, h, file_delta in changed:
            lines.append(f"| `{name}` | {_fmt(b)} | {_fmt(h)} | {_fmt_delta(file_delta)} |")
        lines += ["", "</details>"]

    return "\n".join(lines) + "\n", decreased, head_total, base_total


def _write_gha_outputs(decreased: bool, head: Optional[float], base: Optional[float]) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write(f"decreased={'true' if decreased else 'false'}\n")
        fh.write(f"head_total={'' if head is None else f'{head:.2f}'}\n")
        fh.write(f"base_total={'' if base is None else f'{base:.2f}'}\n")


def _write_job_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write(markdown)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "head", type=Path, help="Coverage JSON report for the PR/branch under test."
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="Coverage JSON report for the base branch to compare against.",
    )
    parser.add_argument(
        "--comment-file",
        type=Path,
        default=None,
        help="Write the Markdown report to this file (for posting as a PR comment).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="Ignore total coverage changes within this many percentage points (default 0.01).",
    )
    parser.add_argument(
        "--fail-on-decrease",
        action="store_true",
        help="Exit non-zero when coverage decreased (for local use; CI gates on the GHA output).",
    )
    args = parser.parse_args(argv)

    markdown, decreased, head_total, base_total = build_report(
        args.head, args.base, args.tolerance
    )

    print(markdown, end="")

    if args.comment_file:
        args.comment_file.write_text(markdown, encoding="utf-8")

    _write_job_summary(markdown)
    _write_gha_outputs(decreased, head_total, base_total)

    if args.fail_on_decrease and decreased:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
