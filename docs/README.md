# Documentation

Guides for the `warped-pinball-vector` Python library and the HTTP routes it
wraps. Start with the top-level [README](../README.md) for installation,
discovery, and connection basics.

| Document | Covers |
| --- | --- |
| [Reading & writing memory](memory.md) | The `/api/address/read` and `/api/address/write` routes, the `read_bytes()` / `write_bytes()` / `read()` / `write()` wrappers, chunking, snapshots, and the CLI equivalents |
| [Address maps](address-maps.md) | Naming memory locations with `AddressMap`, encodings (BCD, little/big-endian), sharing maps as JSON, and the registry convention |
| [HTTP API reference](http-api.md) | Request/response shapes for the address routes and how to reach any firmware route with `Machine.call()` |

## Quick orientation

A Vector board exposes the pinball machine's battery-backed SRAM over HTTP.
Everything in these guides operates on **offsets relative to the start of that
SRAM region** (`SRAM_DATA_BASE` in the firmware) — the same offsets you'd find
in game ROM manuals and memory maps, not absolute CPU addresses.

```python
import warpedpinball

with warpedpinball.connect("elvira", password="hunter2") as m:
    credits = m.read(0x2134)          # one byte -> int
    m.write(0x2134, 5)                # set it
```

Reads and writes of SRAM are **authenticated** routes: you need the machine's
password over WiFi (USB connections skip authentication entirely — the firmware
trusts physical access).
