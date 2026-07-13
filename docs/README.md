# Documentation

Guides for the `warpedpinball` Python library and the HTTP routes it
wraps. Start with the top-level [README](../README.md) for installation and
a quickstart.

| Document | Covers |
| --- | --- |
| [Working with a machine](machine.md) | Connecting (WiFi, IP, USB), authentication, the wrapper methods, `Machine.call()`, live game events, cooldowns, and the error hierarchy |
| [Reading & writing memory](memory.md) | The `/api/address/read` and `/api/address/write` routes, the `read_bytes()` / `write_bytes()` wrappers, chunking, snapshots, and the CLI equivalents |
| [HTTP API reference](http-api.md) | Request/response shapes for the address routes and how to reach any firmware route with `Machine.call()` |
| [CLI guide](cli.md) | The `vector` command and its subcommands |

## Quick orientation

A Vector board exposes the pinball machine's battery-backed SRAM over HTTP.
Everything in these guides operates on **offsets relative to the start of that
SRAM region** (`SRAM_DATA_BASE` in the firmware), the same offsets you'd find
in game ROM manuals and memory maps, not absolute CPU addresses.

```python
import warpedpinball

with warpedpinball.connect("elvira", password="hunter2") as m:
    credits = m.read_bytes(0x2134, 1)   # one byte
    m.write_bytes(0x2134, [5])          # set it
```

Reads and writes of SRAM are **authenticated** routes: you need the machine's
password over WiFi. USB connections skip authentication entirely, since the
firmware trusts physical access.
