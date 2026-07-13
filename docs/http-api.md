# HTTP API reference: address routes

This page documents the raw firmware routes for SRAM access and how to call
them from the library. Most users should prefer the higher-level wrappers in
[Reading & writing memory](memory.md), which handle chunking, decoding, and
authentication for you.

## Conventions

- The firmware answers on **port 80** over WiFi, and the same routes are
  tunneled over **USB serial**.
- Routes accept POST with a JSON body (routes without a body work as GET).
- Offsets are relative to the start of the SRAM data region
  (`SRAM_DATA_BASE`), not absolute CPU addresses.
- Authenticated routes use an **HMAC-SHA256 challenge/response** scheme: the
  client fetches a single-use challenge, then signs the exact request body
  string. The library does all of this for you whenever you pass
  `authenticated=True`; over USB the firmware skips authentication entirely.

## `/api/address/read`

Read up to 256 bytes of SRAM. **Authenticated.**

Request body:

```json
{"offset": 8500, "count": 16}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `offset` | int | Start offset into the SRAM data region |
| `count` | int | Number of bytes to read, **max 256 per request** |

Response:

```json
{"offset": 8500, "values": [5, 0, 18, 52, 86, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}
```

`values` is a list of ints (0-255), one per byte, starting at `offset`.

From the library:

```python
result = m.call(
    "/api/address/read",
    body={"offset": 0x2134, "count": 16},
    authenticated=True,
)
data = bytes(result["values"])
```

For reads larger than 256 bytes, use `m.read_bytes(offset, count)`, which issues
as many requests as needed and concatenates the results.

## `/api/address/write`

Write bytes to SRAM. **Authenticated.**

Request body:

```json
{"offset": 8500, "values": [5]}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `offset` | int | Start offset into the SRAM data region |
| `values` | list of int | Byte values (0-255) written consecutively from `offset`; keep to 256 per request |

From the library:

```python
m.call(
    "/api/address/write",
    body={"offset": 0x2134, "values": [5]},
    authenticated=True,
)
```

For larger writes, use `m.write_bytes(offset, data)`, which chunks at 256 bytes
per request automatically.

> **Careful:** writes go straight into the game's live memory. Writing the
> wrong offset can corrupt scores, settings, or crash the game in progress.
> Verify offsets against a known-good memory map for the exact ROM the machine
> is running.

## `/api/memory-snapshot`

Stream the entire SRAM data region as raw bytes.

```python
data = m.memory_snapshot()                       # joined into one bytes object

# or stream it yourself:
with open("dump.bin", "wb") as fh:
    for chunk in m.call_stream("/api/memory-snapshot"):
        fh.write(chunk)
```

## Calling any route: the escape hatch

Every firmware route, including ones without a wrapper, is reachable through
`Machine.call()` / `Machine.call_stream()`:

```python
m.call("/api/game/name")
m.call("/api/address/read", body={"offset": 0, "count": 4}, authenticated=True)

for chunk in m.call_stream("/api/logs", authenticated=True):
    ...
```

Bodies are serialized to JSON exactly once; the identical string is signed and
transmitted, so authenticated calls work for any route. Requests are
serialized per machine (one lock per `Machine`) because the firmware is
single-threaded and auth challenges are single-use.

## Error mapping

HTTP-level failures surface as typed exceptions rather than status codes:

| HTTP status | Exception |
| --- | --- |
| 401 | `AuthenticationError` |
| 404 | `UnsupportedFirmwareError` (route missing on this firmware) |
| 409 / 429 on a cooldown route | `CooldownError` (`.retry_after` hint in seconds) |
| 429 on the challenge route | `RateLimitedError` |
| 5xx | `VectorServerError` (`.status`) |
| connection / timeout | `TransportError` |
