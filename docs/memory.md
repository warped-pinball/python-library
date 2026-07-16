# Reading & writing memory

The firmware exposes the pinball machine's battery-backed SRAM through two
HTTP routes:

| Route | Purpose | Auth | Limit |
| --- | --- | --- | --- |
| `/api/address/read` | Read up to 256 bytes at an offset | required | `count` capped at 256 per request |
| `/api/address/write` | Write bytes at an offset | required | 256 values per request |

All offsets are **relative to the start of the SRAM data region**
(`SRAM_DATA_BASE`), matching the offsets found in game memory maps.

You will rarely call these routes directly, because the `Machine` object provides
wrappers at two levels of convenience:

1. [`read()`](#a-single-value-read): one small numeric value as an `int`
2. [`read_bytes()` / `write_bytes()`](#bulk-bytes-read_bytes--write_bytes): bulk raw bytes, auto-chunked
3. [`memory_snapshot()` / `diff_snapshots()`](#whole-memory-snapshots): the whole SRAM at once

## Setup

Reads and writes are authenticated, so connect with a password (or set
`$VECTOR_PASSWORD`, or assign `m.password`). Over USB no password is needed.

```python
import warpedpinball

m = warpedpinball.connect("elvira", password="hunter2")
# or: m = warpedpinball.connect_usb()      # no password needed over USB
```

Calling a read/write with no password configured raises
`AuthenticationRequiredError` *before* any network traffic; a wrong password
raises `AuthenticationError` when the device rejects the signature.

## A single value: `read()`

When you just want a number out of a known address, `read(offset, count=1)`
reads the bytes and decodes them as an unsigned integer, so you don't have to
index into a `bytes` object yourself:

```python
credits = m.read(0x2134)              # one byte -> int
timer = m.read(0x0175)               # e.g. a hurry-up countdown

# Multi-byte values decode big-endian by default; pass byteorder for little:
score = m.read(0x0300, 4)             # four bytes, big-endian
level = m.read(0x0400, 2, byteorder="little")
```

For anything larger, or when a region isn't a plain integer (packed BCD, a
struct, a block you want to diff), reach for `read_bytes()` below.

## Bulk bytes: `read_bytes()` / `write_bytes()`

`read_bytes(offset, count)` returns `bytes`; `write_bytes(offset, data)`
accepts `bytes`, `bytearray`, or a list of ints. Both transparently split the
work into 256-byte requests (the firmware's per-request cap), so you can ask
for any size:

```python
# Read 600 bytes starting at 0x0200, sent as three requests
# (256 + 256 + 88) behind the scenes:
data = m.read_bytes(0x0200, 600)
print(data.hex(" "))

# Write a block back
m.write_bytes(0x0200, data)

# A list of ints works too
m.write_bytes(0x2134, [0x05, 0x00, 0x12])
```

Reads return raw bytes; if a region holds an encoded value (packed BCD, a
little- or big-endian integer, ...) decode it in your own code. The library
deliberately doesn't try to name or decode addresses for you — those layouts
are game-specific and best kept alongside the code that knows about them.

## Whole-memory snapshots

`memory_snapshot()` streams the entire SRAM via `/api/memory-snapshot` and
returns it as one `bytes` object. Combined with `diff_snapshots()` it's the
main tool for *finding* an address in the first place:

```python
before = m.memory_snapshot()
input("Add one credit on the machine, then press Enter...")
after = m.memory_snapshot()

for offset, old, new in m.diff_snapshots(before, after):
    print(f"{offset:#06x}: {old} -> {new}")
```

Run that a few times while changing exactly one thing on the machine; the
offset that changes consistently is your address. (A length difference between
snapshots shows up as changes versus `-1`.)

## Live snapshot broadcasting: `set_memory_broadcast()`

Instead of polling snapshots, the firmware can *push* them:
`set_memory_broadcast(True)` makes the board broadcast the whole SRAM data
region as UDP packets to port 2040 on the local network, over and over, until
turned off. Each packet is a 4-byte big-endian offset header followed by up to
256 bytes of data. This is the stream that live viewers like Warped Pinball's
[Memory Mapper](https://github.com/warped-pinball/memory-mapper) listen to.

```python
m.set_memory_broadcast(True)                     # broadcast every 100 ms
m.set_memory_broadcast(True, frequency_ms=500)   # or at your own rate
...
m.set_memory_broadcast(False)                    # stop broadcasting
```

Enabling and disabling are authenticated. `frequency_ms` is clamped to the
firmware's 10-60000 ms bounds. Broadcasting costs the board work on every
tick, so turn it off when you're done watching.

## Calling the routes directly

If you need something the wrappers don't do, `Machine.call()` reaches the raw
routes (see the [HTTP API reference](http-api.md) for the exact shapes):

```python
result = m.call(
    "/api/address/read",
    body={"offset": 0x2134, "count": 16},
    authenticated=True,
)
print(result["values"])           # list of ints, one per byte

m.call(
    "/api/address/write",
    body={"offset": 0x2134, "values": [5]},
    authenticated=True,
)
```

Note that `call()` does **not** chunk for you: keep `count` and
`len(values)` at 256 or below per request.

## From the command line

The `vector` CLI exposes the same operations:

```bash
vector read elvira 0x2134                       # one byte, printed as decimal
vector read elvira 0x0200 --count 4             # multiple bytes, printed as hex
vector write elvira 0x2134 5 --password hunter2 # write byte value(s)
vector snapshot elvira -o dump.bin              # dump full SRAM to a file
```

Each command takes a machine name or IP, plus `--password/-p` (or
`$VECTOR_PASSWORD`) and `--usb [PORT]` to go over USB serial instead of WiFi.

## Being kind to the device

The board is a single-threaded microcontroller. The library serializes all
requests per `Machine` (one lock per machine), and chunked reads/writes send
one request at a time, but a tight polling loop is still a polling loop. Prefer
reading a whole region with one `read_bytes()` call over many single-byte
reads, and keep poll intervals at 0.5 s or more.

## Errors you may see

| Exception | Cause |
| --- | --- |
| `AuthenticationRequiredError` | Read/write attempted with no password configured (raised before any traffic) |
| `AuthenticationError` | The device rejected the credentials |
| `RateLimitedError` | Too many outstanding auth challenges; sleep briefly and retry |
| `UnsupportedFirmwareError` | The route doesn't exist on this firmware version |
| `TransportError` | Connection, timeout, or protocol-level failure |
