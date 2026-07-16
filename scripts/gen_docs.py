#!/usr/bin/env python3
"""Generate the API-reference website for warpedpinball with pdoc.

pdoc's automatic submodule discovery honours a package's ``__all__``. Ours
lists the public *API* (``connect``, ``Machine``, the exception classes, ...)
rather than submodule names, so ``pdoc warpedpinball`` on its own would only
render the top-level package page. This script walks the package and hands
pdoc an explicit module list so every submodule (``machine``, ``models``,
``cli``, the transports, ...) gets its own page. New modules are picked up
automatically, so the docs stay in sync with the source.

Usage::

    python scripts/gen_docs.py [--output site]
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys

PACKAGE = "warpedpinball"


def module_names(package: str) -> list[str]:
    """Return the module specs pdoc needs to document the whole package.

    pdoc recurses into a package's submodules on its own, but skips any that a
    package's ``__all__`` hides (ours lists API names, not submodules). So we
    walk the tree and explicitly list only the modules a parent's ``__all__``
    would exclude; pdoc reaches everything else itself, which keeps the spec
    list minimal and avoids duplicate-module warnings.
    """
    specs = [package]
    _collect(importlib.import_module(package), specs)
    return specs


def _collect(pkg: object, specs: list[str]) -> None:
    pkg_all = getattr(pkg, "__all__", None)
    for info in pkgutil.iter_modules(pkg.__path__, prefix=f"{pkg.__name__}."):
        child = info.name.rpartition(".")[2]
        hidden = pkg_all is not None and child not in pkg_all
        if hidden:
            # pdoc won't reach this one via its parent; list it explicitly.
            specs.append(info.name)
        if info.ispkg:
            _collect(importlib.import_module(info.name), specs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        default="site",
        help="output directory for the generated HTML (default: site)",
    )
    parser.add_argument(
        "--docformat",
        default="restructuredtext",
        help="docstring format passed to pdoc (default: restructuredtext)",
    )
    args = parser.parse_args(argv)

    try:
        import pdoc.__main__
    except ImportError:  # pragma: no cover - surfaced to the user directly
        print(
            "pdoc is not installed. Install the docs extra:\n"
            '    pip install -e ".[docs]"',
            file=sys.stderr,
        )
        return 1

    modules = module_names(PACKAGE)
    pdoc_argv = [
        *modules,
        "--output-directory",
        args.output,
        "--docformat",
        args.docformat,
    ]
    print(f"pdoc {' '.join(pdoc_argv)}")
    sys.argv = ["pdoc", *pdoc_argv]
    pdoc.__main__.cli()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
