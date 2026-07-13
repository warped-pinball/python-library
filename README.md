# warpedpinball

[![CI](https://github.com/warped-pinball/python-library/actions/workflows/ci.yml/badge.svg)](https://github.com/warped-pinball/python-library/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/warpedpinball.svg)](https://pypi.org/project/warpedpinball/)

Control real pinball machines from Python.

If a machine has a [Warped Pinball](https://warpedpinball.com) Vector board
installed, this library lets you talk to it in a few lines of code: watch
scores change ball by ball, pull leaderboards, manage players, read and write
the game's memory, and push firmware updates. Build a tournament display, a
Discord bot that announces high scores, a stats dashboard for your basement, or
a game mod that reacts to what's happening on the playfield.

The library finds boards on your network by name, handles authentication for
you, and works the same whether you connect over WiFi or plug in with a USB
cable. You write `m.leaderboard()`; it takes care of the rest.

## Install

Requires Python 3.9+.

```bash
pip install warpedpinball
```

## Quickstart

Connect to a machine by name and see what's happening on it:

```python
import warpedpinball

with warpedpinball.connect("elvira") as m:
    print(m.leaderboard())

    for event in m.watch_game():
        if event.type == "score_changed":
            print(f"player {event.player}: {event.old} -> {event.new}")
```

That's a live feed of scores from a real pinball machine, in ten lines.
`connect()` finds the board on your LAN by name (partial names work), and
read-only calls like these need no password. When you're ready to change
things, pass `password=` to `connect()` and the same object can update
players, reset leaderboards, write memory, and more.

## What you can do

- **Follow games live.** `watch_game()` yields events as games start and end,
  balls drain, and scores change. See
  [working with a machine](https://github.com/warped-pinball/python-library/blob/main/docs/machine.md).
- **Manage scores and players.** Leaderboards, tournaments, player rosters,
  score claiming, import/export. Also covered in
  [working with a machine](https://github.com/warped-pinball/python-library/blob/main/docs/machine.md).
- **Read and write game memory.** Peek at credits, scores, and settings in the
  machine's battery-backed SRAM, or change them. See
  [reading and writing memory](https://github.com/warped-pinball/python-library/blob/main/docs/memory.md).
- **Ship mods with named addresses.** Define `"player1_score"` once in an
  `AddressMap`, share it as JSON, and other people's code gets the same names
  for the same ROM. See
  [address maps](https://github.com/warped-pinball/python-library/blob/main/docs/address-maps.md).
- **Reach any firmware route.** `m.call()` gives you the whole HTTP API, even
  routes that don't have a wrapper yet. See the
  [HTTP API reference](https://github.com/warped-pinball/python-library/blob/main/docs/http-api.md).
- **Skip the network entirely.** Plug in a USB cable and `connect_usb()` gives
  you the same interface with no WiFi and no password.
- **Script from the shell.** The `vector` CLI covers discovery, status,
  leaderboards, memory access, and firmware updates without writing any
  Python. See the [CLI guide](https://github.com/warped-pinball/python-library/blob/main/docs/cli.md).

## Documentation

Full guides live in the
[documentation index](https://github.com/warped-pinball/python-library/blob/main/docs/README.md):

- [Working with a machine](https://github.com/warped-pinball/python-library/blob/main/docs/machine.md):
  connecting, authentication, the wrapper methods, live game events, and error
  handling
- [Reading and writing memory](https://github.com/warped-pinball/python-library/blob/main/docs/memory.md):
  memory reads/writes, snapshots, and finding addresses
- [Address maps](https://github.com/warped-pinball/python-library/blob/main/docs/address-maps.md):
  naming memory locations and sharing maps for a game ROM
- [HTTP API reference](https://github.com/warped-pinball/python-library/blob/main/docs/http-api.md):
  the raw firmware routes
- [CLI guide](https://github.com/warped-pinball/python-library/blob/main/docs/cli.md):
  the `vector` command

Curious about the hardware itself? Vector boards and the machines they fit are
at [warpedpinball.com](https://warpedpinball.com).

## Development

```bash
git clone https://github.com/warped-pinball/python-library
cd python-library
pip install -e ".[dev,usb]"

pytest          # run the tests
ruff check .    # lint
```

## Releasing

The package version lives in two places that must always agree:

- `pyproject.toml` → `[project] version`
- `warpedpinball/__init__.py` → `__version__`

`scripts/check_version.py` enforces this and, when run against a git tag,
verifies the tag matches too. CI runs it on every pull request, so drift
between the two files fails fast. The publish workflow runs it again on the
release tag before anything is built, so a release whose tag doesn't match the
package version (e.g. tagging `v0.2.0` while `pyproject.toml` still says
`0.1.0`) fails before it can reach PyPI.

To cut a release:

1. Bump the version in **both** `pyproject.toml` and `warpedpinball/__init__.py`.
2. Verify locally: `python scripts/check_version.py --tag vX.Y.Z`
3. Merge, then create a GitHub release with the tag `vX.Y.Z` (the leading `v`
   is optional — both `vX.Y.Z` and `X.Y.Z` are accepted).

The `Publish` workflow validates the tag, builds the distributions, and
publishes to PyPI via Trusted Publishing.

