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

### Recommended: install into a virtual environment

A virtual environment keeps `warpedpinball` and its dependencies isolated from
your system Python, so nothing you install here can interfere with other
projects (or with packages your OS manages). This is the recommended way to
install.

```bash
# Create a virtual environment in a ".venv" folder
python3 -m venv .venv

# Activate it
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows (PowerShell / cmd)

# Install the library into the active environment
pip install warpedpinball

# Or, to also get USB (serial) support:
pip install "warpedpinball[usb]"
```

Once activated, `python`, `pip`, and the `vector` CLI all refer to the
environment. Run `deactivate` to leave it; re-run the `source` line above to
come back to it in a new shell.

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
- [HTTP API reference](https://github.com/warped-pinball/python-library/blob/main/docs/http-api.md):
  the raw firmware routes
- [CLI guide](https://github.com/warped-pinball/python-library/blob/main/docs/cli.md):
  the `vector` command
- [Examples](https://github.com/warped-pinball/python-library/blob/main/docs/examples.md):
  runnable scripts, including a live animated ELVIRA hurry-up display

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
