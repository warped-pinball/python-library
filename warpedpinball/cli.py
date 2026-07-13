"""``vector`` console entry point — a thin layer over the library.

    vector discover
    vector status elvira
    vector read elvira 0x2134 [--count N]
    vector write elvira 0x2134 5 --password ...
    vector snapshot elvira -o dump.bin
    vector update elvira --password ...
    vector version elvira
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

import warpedpinball
from warpedpinball.exceptions import VectorError


def _print_json(data: Any) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(data)


def _connect(args: argparse.Namespace) -> warpedpinball.Machine:
    if getattr(args, "usb", None):
        return warpedpinball.connect_usb(args.usb if args.usb is not True else None)
    return warpedpinball.connect(
        args.machine, password=getattr(args, "password", None), timeout=args.timeout
    )


def _parse_int(text: str) -> int:
    return int(text, 0)  # accepts 0x..., 0o..., decimal


def cmd_discover(args: argparse.Namespace) -> int:
    machines = warpedpinball.discover(timeout=args.timeout)
    if not machines:
        print("No machines found", file=sys.stderr)
        return 1
    for m in sorted(machines, key=lambda m: m.name.lower()):
        print(f"{m.name}\t{m.ip}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        _print_json(m.game_status())
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        _print_json(m.version())
    return 0


def cmd_leaders(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        _print_json(m.leaderboard())
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        offset = _parse_int(args.offset)
        data = m.read_bytes(offset, args.count)
        if args.count == 1:
            print(data[0])
        else:
            print(data.hex(" "))
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        offset = _parse_int(args.offset)
        values = [_parse_int(v) for v in args.values]
        m.write_bytes(offset, values)
        print(f"Wrote {len(values)} byte(s) at {hex(offset)}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        data = m.memory_snapshot()
    if args.output:
        with open(args.output, "wb") as fh:
            fh.write(data)
        print(f"Wrote {len(data)} bytes to {args.output}")
    else:
        sys.stdout.buffer.write(data)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    with _connect(args) as m:
        info = m.check_for_updates()
        _print_json(info)
        url: Optional[str] = args.url
        if url is None and isinstance(info, dict):
            url = info.get("url") or info.get("update_url")
        if not url:
            print("No update URL available", file=sys.stderr)
            return 1
        if not args.yes:
            answer = input(f"Apply update from {url}? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Aborted")
                return 1

        def show(record: dict) -> None:
            percent = record.get("percent")
            log = record.get("log", "")
            prefix = f"[{percent:>3}%] " if percent is not None else ""
            print(f"{prefix}{log}")

        m.apply_update(url=url, progress=show)
        print("Update applied; waiting for the board to come back...")
        m.wait_until_reachable()
        _print_json(m.version())
    return 0


def _add_target_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("machine", help="machine name (LAN discovery) or IP address")
    p.add_argument("--password", "-p", help="device password (or $VECTOR_PASSWORD)")
    p.add_argument("--timeout", type=float, default=5.0, help="discovery timeout (s)")
    p.add_argument(
        "--usb",
        nargs="?",
        const=True,
        default=None,
        metavar="PORT",
        help="use USB serial instead of the network (optionally give a port)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vector", description="Warped Pinball Vector command-line client"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {warpedpinball.__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="find Vector boards on the LAN")
    p.add_argument("--timeout", type=float, default=5.0)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("status", help="show live game status")
    _add_target_args(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("version", help="show firmware version")
    _add_target_args(p)
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("leaders", help="show the leaderboard")
    _add_target_args(p)
    p.set_defaults(func=cmd_leaders)

    p = sub.add_parser("read", help="read SRAM bytes")
    _add_target_args(p)
    p.add_argument("offset", help="offset (0x-prefixed hex or decimal)")
    p.add_argument("--count", "-c", type=int, default=1)
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("write", help="write SRAM bytes")
    _add_target_args(p)
    p.add_argument("offset", help="offset (0x-prefixed hex or decimal)")
    p.add_argument("values", nargs="+", help="byte value(s), hex or decimal")
    p.set_defaults(func=cmd_write)

    p = sub.add_parser("snapshot", help="dump full SRAM to a file or stdout")
    _add_target_args(p)
    p.add_argument("--output", "-o", help="output file (default: stdout)")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("update", help="check for and apply a firmware update")
    _add_target_args(p)
    p.add_argument("--url", help="explicit update URL")
    p.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    p.set_defaults(func=cmd_update)

    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except VectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
