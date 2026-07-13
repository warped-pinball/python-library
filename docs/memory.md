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
wrappers at three levels of convenience:

1. [`read_bytes()` / `write_bytes()`](#bulk-bytes-read_bytes--write_bytes): bulk raw bytes, auto-chunked
2. [`read()` / `write()`](#named-or-single-address-read--write): one value at a named address or raw offset, with decoding
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

## Named or single address: `read()` / `write()`

`read(target)` and `write(target, value)` accept either a **name** defined in
the machine's [`AddressMap`](address-maps.md) or a **raw integer offset**.

### Raw offsets

```python
credits = m.read(0x2134)          # one byte -> int (e.g. 5)
raw = m.read(0x0200, count=4)     # multiple bytes -> bytes (e.g. b'\x12\x34\x56\x00')

m.write(0x2134, 5)                # write a single byte
```

With a raw offset, `count` defaults to 1; a one-byte read comes back as an
`int`, longer reads as `bytes`.

### Named addresses

Define names once (or [load a shared map](address-maps.md#sharing-maps-as-json))
and the values are decoded/encoded for you:

```python
m.addresses.define("credits", 0x2134)                            # raw byte
m.addresses.define("player1_score", 0x0200, length=4, encoding="bcd")

score = m.read("player1_score")   # -> 1234500 (decoded from packed BCD)
m.write("credits", 5)
m.write("player1_score", 50000)   # encoded back to BCD before writing
```

See [Address maps](address-maps.md) for the available encodings and how to
share maps between users.

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
one request at a time, but a tight polling loop over `read()` is still a
polling loop. Prefer reading a whole region with one `read_bytes()` call over
many single-byte `read()`s, and keep poll intervals at 0.5 s or more.

## Errors you may see

| Exception | Cause |
| --- | --- |
| `AuthenticationRequiredError` | Read/write attempted with no password configured (raised before any traffic) |
| `AuthenticationError` | The device rejected the credentials |
| `RateLimitedError` | Too many outstanding auth challenges; sleep briefly and retry |
| `UnsupportedFirmwareError` | The route doesn't exist on this firmware version |
| `TransportError` | Connection, timeout, or protocol-level failure |
