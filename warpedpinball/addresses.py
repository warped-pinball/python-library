"""Named memory addresses (:class:`AddressMap`).

The firmware exposes raw SRAM access relative to ``SRAM_DATA_BASE`` but cannot
store names. An ``AddressMap`` maps friendly names to ``(offset, length,
encoding)`` and can be saved/loaded as JSON so mod makers can ship an address
map for a specific game ROM alongside their code.
"""

from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple, Union

Encoding = Union[str, Tuple[Callable[[bytes], Any], Callable[[Any, int], bytes]], None]

#: Directory convention for community address maps, looked up by the game's
#: ``/api/game/active_config`` value: ``~/.warpedpinball/addressmaps/<config>.json``
REGISTRY_DIR = os.path.join("~", ".warpedpinball", "addressmaps")


def _bcd_decode(data: bytes) -> int:
    """Packed BCD, most-significant byte first (two decimal digits per byte)."""
    value = 0
    for byte in data:
        value = value * 100 + ((byte >> 4) * 10) + (byte & 0x0F)
    return value


def _bcd_encode(value: int, length: int) -> bytes:
    digits = str(int(value)).rjust(length * 2, "0")
    if len(digits) > length * 2:
        raise ValueError(f"{value} does not fit in {length} BCD bytes")
    return bytes(
        (int(digits[i]) << 4) | int(digits[i + 1]) for i in range(0, len(digits), 2)
    )


def _le_decode(data: bytes) -> int:
    return int.from_bytes(data, "little")


def _le_encode(value: int, length: int) -> bytes:
    return int(value).to_bytes(length, "little")


def _be_decode(data: bytes) -> int:
    return int.from_bytes(data, "big")


def _be_encode(value: int, length: int) -> bytes:
    return int(value).to_bytes(length, "big")


BUILTIN_ENCODINGS: Dict[str, Tuple[Callable, Callable]] = {
    "bcd": (_bcd_decode, _bcd_encode),
    "le_uint": (_le_decode, _le_encode),
    "be_uint": (_be_decode, _be_encode),
}


@dataclass
class AddressEntry:
    name: str
    offset: int
    length: int = 1
    encoding: Encoding = None

    def codecs(self) -> Optional[Tuple[Callable, Callable]]:
        """Resolve to a ``(decode, encode)`` pair, or None for raw."""
        if self.encoding is None:
            return None
        if isinstance(self.encoding, str):
            try:
                return BUILTIN_ENCODINGS[self.encoding]
            except KeyError:
                raise ValueError(
                    f"Unknown encoding {self.encoding!r}; "
                    f"expected one of {sorted(BUILTIN_ENCODINGS)}"
                ) from None
        return self.encoding  # (decode, encode) callable pair

    def decode(self, data: bytes) -> Any:
        codecs = self.codecs()
        if codecs is None:
            return data[0] if self.length == 1 else bytes(data)
        return codecs[0](bytes(data))

    def encode(self, value: Any) -> bytes:
        codecs = self.codecs()
        if codecs is not None and not isinstance(value, (bytes, bytearray)):
            return codecs[1](value, self.length)
        if isinstance(value, int):
            if self.length == 1:
                return bytes([value])
            raise ValueError(
                f"{self.name!r} spans {self.length} bytes; pass bytes or set an encoding"
            )
        data = bytes(value)
        if len(data) != self.length:
            raise ValueError(
                f"{self.name!r} is {self.length} bytes but got {len(data)}"
            )
        return data


class AddressMap:
    """Mapping of friendly names to SRAM offsets (relative to SRAM_DATA_BASE)."""

    def __init__(self, active_config: Optional[str] = None):
        self.active_config = active_config
        self._entries: Dict[str, AddressEntry] = {}

    def define(
        self,
        name: str,
        offset: int,
        length: int = 1,
        encoding: Encoding = None,
    ) -> None:
        """Register ``name`` -> ``(offset, length, encoding)``.

        ``encoding`` may be ``"bcd"``, ``"le_uint"``, ``"be_uint"``, or a
        ``(decode, encode)`` callable pair; default is raw (int for a single
        byte, ``bytes`` for longer regions).
        """
        if length < 1:
            raise ValueError("length must be >= 1")
        self._entries[name] = AddressEntry(name, offset, length, encoding)

    def get(self, name: str) -> AddressEntry:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(
                f"Unknown address name {name!r}; defined: {sorted(self._entries)}"
            ) from None

    def resolve(self, target: Union[str, int]) -> AddressEntry:
        """Resolve a name or a raw offset to an :class:`AddressEntry`."""
        if isinstance(target, str):
            return self.get(target)
        return AddressEntry(name=hex(target), offset=int(target))

    def names(self):
        return sorted(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    # -- persistence ---------------------------------------------------------

    def to_dict(self) -> dict:
        entries = {}
        for entry in self._entries.values():
            if entry.encoding is not None and not isinstance(entry.encoding, str):
                raise ValueError(
                    f"{entry.name!r} uses a custom callable encoding, "
                    "which cannot be serialized to JSON"
                )
            entries[entry.name] = {
                "offset": entry.offset,
                "length": entry.length,
                "encoding": entry.encoding,
            }
        return {"active_config": self.active_config, "addresses": entries}

    def save(self, path: str) -> None:
        with open(os.path.expanduser(path), "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")

    @classmethod
    def from_dict(cls, data: dict) -> "AddressMap":
        amap = cls(active_config=data.get("active_config"))
        for name, spec in (data.get("addresses") or {}).items():
            amap.define(
                name,
                int(spec["offset"]),
                length=int(spec.get("length", 1)),
                encoding=spec.get("encoding"),
            )
        return amap

    @classmethod
    def load(cls, path: str, active_config: Optional[str] = None) -> "AddressMap":
        """Load a saved map. Warns when ``active_config`` (the machine's
        current ``/api/game/active_config``) doesn't match the saved one."""
        with open(os.path.expanduser(path), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        amap = cls.from_dict(data)
        if (
            active_config
            and amap.active_config
            and active_config != amap.active_config
        ):
            warnings.warn(
                f"Address map {path!r} was built for game config "
                f"{amap.active_config!r} but the machine reports "
                f"{active_config!r}; offsets may be wrong",
                stacklevel=2,
            )
        return amap

    @classmethod
    def load_registry(cls, active_config: str) -> Optional["AddressMap"]:
        """Look up ``~/.warpedpinball/addressmaps/<active_config>.json``."""
        path = os.path.expanduser(os.path.join(REGISTRY_DIR, f"{active_config}.json"))
        if not os.path.exists(path):
            return None
        return cls.load(path, active_config=active_config)
