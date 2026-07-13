# Address maps

The firmware reads and writes raw SRAM bytes but can't store names for them.
An `AddressMap` maps friendly names to `(offset, length, encoding)` so your
code can say `m.read("player1_score")` instead of remembering that scores live
at `0x0200` as 4 bytes of packed BCD — and so mod makers can **ship an address
map for a specific game ROM** alongside their code.

## Defining addresses

```python
import warpedpinball
from warpedpinball import AddressMap

amap = AddressMap(active_config="elvira_l4")   # the game ROM this map is for
amap.define("credits", 0x2134)                             # raw single byte
amap.define("player1_score", 0x0200, length=4, encoding="bcd")
amap.define("high_score", 0x0210, length=4, encoding="bcd")
amap.define("play_counter", 0x0300, length=2, encoding="le_uint")

m = warpedpinball.connect("elvira", password="hunter2")
m.addresses = amap

print(m.read("player1_score"))    # -> decoded int, e.g. 1234500
m.write("credits", 5)
```

`define(name, offset, length=1, encoding=None)`:

- **offset** — relative to the start of the SRAM data region, same as the
  offsets used by [`read_bytes()`](memory.md).
- **length** — bytes occupied (default 1).
- **encoding** — how bytes map to Python values (below). With no encoding, a
  1-byte entry reads as an `int` and longer entries read as `bytes`.

## Encodings

| Encoding | Decodes to | Notes |
| --- | --- | --- |
| `"bcd"` | `int` | Packed BCD, most-significant byte first, two decimal digits per byte — the classic Williams/Bally score format. `b'\x12\x34\x56'` ⇄ `123456`. |
| `"le_uint"` | `int` | Little-endian unsigned integer |
| `"be_uint"` | `int` | Big-endian unsigned integer |
| `None` (default) | `int` (1 byte) or `bytes` | Raw |
| `(decode, encode)` pair | anything | Custom callables (below) |

Writes go through the matching encoder, so `m.write("player1_score", 50000)`
turns the int back into BCD bytes before sending. Values that don't fit the
declared length raise `ValueError` locally — nothing is sent to the device.

### Custom encodings

Pass a `(decode, encode)` pair: `decode(data: bytes) -> value` and
`encode(value, length: int) -> bytes`.

```python
def decode_initials(data: bytes) -> str:
    return data.decode("ascii").rstrip("\x00")

def encode_initials(value: str, length: int) -> bytes:
    return value.encode("ascii").ljust(length, b"\x00")

amap.define("champion_initials", 0x0220, length=3,
            encoding=(decode_initials, encode_initials))

m.read("champion_initials")            # -> "MAX"
m.write("champion_initials", "ABC")
```

Custom callable encodings can't be serialized, so entries using them are
excluded from `save()` — use the built-in string encodings for maps you intend
to share.

## Sharing maps as JSON

```python
amap.save("elvira_l4.json")

amap = AddressMap.load("elvira_l4.json")
```

The file is plain JSON, easy to hand-edit or check into a mod's repository:

```json
{
  "active_config": "elvira_l4",
  "addresses": {
    "credits": {"offset": 8500, "length": 1, "encoding": null},
    "player1_score": {"offset": 512, "length": 4, "encoding": "bcd"}
  }
}
```

`AddressMap.load(path, active_config=...)` warns when the map was built for a
different game config than the machine currently reports — offsets from the
wrong ROM will read garbage (and writing through them can corrupt game state),
so don't ignore that warning.

## The registry convention

Drop a map at `~/.warpedpinball/addressmaps/<active_config>.json` and
`connect()` / `connect_usb()` will auto-load it based on the machine's
`/api/game/active_config` value:

```bash
mkdir -p ~/.warpedpinball/addressmaps
cp elvira_l4.json ~/.warpedpinball/addressmaps/
```

```python
m = warpedpinball.connect("elvira", password="hunter2")
m.read("player1_score")     # names available with no explicit setup
```

Auto-loading only happens when that directory exists and you didn't pass
`addresses=` to `connect()` yourself. To do the lookup explicitly:

```python
amap = AddressMap.load_registry("elvira_l4")   # None if no file exists
```

## Finding addresses in the first place

Use full-memory snapshots and diff them while changing exactly one thing on
the machine — see [Whole-memory snapshots](memory.md#whole-memory-snapshots).
Once an offset behaves consistently, `define()` it, verify with a few reads,
and share the JSON.

## Utility methods

```python
"credits" in amap        # membership test
len(amap)                # number of entries
amap.names()             # sorted list of defined names
amap.get("credits")      # the AddressEntry (offset/length/encoding)
```
