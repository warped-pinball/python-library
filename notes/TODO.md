# warped-pinball-vector — Implementation TODO

Tracking list for the Python client library implementation. Checked items are
complete; unchecked items are pending. See `notes/DECISIONS.md` for assumptions
made where the spec was ambiguous.

## 1. Project scaffolding
- [x] `pyproject.toml` (distribution `warped-pinball-vector`, package `warpedpinball`, Python 3.9+, `requests` dep, `pyserial` behind `[usb]` extra, `vector` console entry point)
- [x] `README.md` (install, quickstart, discovery, auth, USB, address maps, CLI)
- [x] `.gitignore`
- [x] License file — MIT (`LICENSE`, `pyproject.toml` `license = "MIT"`)

## 2. Core library (`warpedpinball/`)
- [x] `exceptions.py` — typed error hierarchy
  - [x] `VectorError` base
  - [x] `MachineNotFoundError` (carries names that *were* seen)
  - [x] `AmbiguousMachineError` (carries candidates)
  - [x] `AuthenticationRequiredError` (raised before any network traffic)
  - [x] `AuthenticationError` (401, carries device reason)
  - [x] `CooldownError` (409 "Already running" / cooldown 429s, carries retry hint)
  - [x] `RateLimitedError` (429 on challenge fetch)
  - [x] `VectorServerError` (5xx, carries handler error string)
  - [x] `UnsupportedFirmwareError` (404 on wrapper routes)
  - [x] `TransportError` (connection/timeout/protocol failures)
- [x] `auth.py` — HMAC-SHA256 challenge/response signing
  - [x] `sign(password, challenge, path, body)` — message = challenge + path-sans-query + exact body string
  - [x] retry-once policy on "Challenge expired"/"Invalid challenge"; never on "Bad Credentials"
- [x] `transports/__init__.py` — `Transport` ABC (`request`, `stream`, `close`, `requires_password`)
- [x] `transports/http.py` — HTTP transport
  - [x] serialize JSON once, sign that exact string, send it
  - [x] challenge fetch per request (single-use), 429 → short sleep + retry, then `RateLimitedError`
  - [x] `x-auth-challenge` / `x-auth-hmac` headers
  - [x] status → typed exception mapping (incl. per-route cooldown hints)
  - [x] streaming via `iter_content` for `/api/memory-snapshot`, `/api/logs`, `/api/update/apply`
  - [x] idempotent GET: one retry on connection error; no retries on mutating routes
- [x] `transports/usb.py` — USB serial transport
  - [x] `route|headers|body\n` framing with `\|` escaping
  - [x] skip console noise, find `USB API RESPONSE-->` line, decode JSON envelope, parse JSON-ish body
  - [x] no HMAC (firmware trusts physical access); `requires_password = False`
  - [x] 115200 baud, ~10 s read timeout, ~2 s settle sleep after open
  - [x] `list_serial_ports()` filtered to Raspberry Pi VID 0x2E8A
  - [x] streaming routes returned as one large chunk (documented)
- [x] `discovery.py` — UDP discovery client (port 37020)
  - [x] HELLO broadcast frame builder, re-broadcast every ~2 s
  - [x] FULL frame parser (tolerates PING/PONG/OFFLINE noise, truncated/garbage frames)
  - [x] bind 37020 with fallback to ephemeral port
  - [x] `DiscoveredMachine(ip, name)` dataclass, dedup by IP, early exit on name match
- [x] `addresses.py` — `AddressMap`
  - [x] `define(name, offset, length=1, encoding=None)`
  - [x] encodings: `"bcd"`, `"le_uint"`, `"be_uint"`, custom `(decode, encode)` pair
  - [x] `save(path)` / `AddressMap.load(path)` incl. `active_config`, mismatch warning
  - [x] registry convention: `~/.warpedpinball/addressmaps/<active_config>.json` auto-load
- [x] `machine.py` — `Machine`
  - [x] per-machine lock; all traffic serialized
  - [x] context manager
  - [x] password: ctor / attribute / `VECTOR_PASSWORD` env fallback; pre-flight `AuthenticationRequiredError`
  - [x] raw escape hatch: `call()`, `call_stream()`
  - [x] memory: `read`, `write`, `read_bytes`, `write_bytes` (auto-chunked at 256), `memory_snapshot()`, `diff_snapshots()`
  - [x] wrappers: version, machine_id, game_name, game_status, reboot_game, reboot, leaderboard, tournament, reset_leaderboard, reset_tournament, claimable_scores, claim_score, players, update_player, check_for_updates, apply_update(progress=), date, set_date, wifi_status, faults, logs, export_scores, import_scores, adjustments, capture_adjustments, restore_adjustments, name_adjustment, peers, verify_password
  - [x] `watch_game(interval=1.0)` polling generator (game start/end, ball change, score deltas)
  - [x] `wait_until_reachable(timeout)`
  - [x] firmware-version gating: 404 on wrapper → `UnsupportedFirmwareError`
- [x] `models.py` — typed dataclasses (`Score`, `Player`, `GameStatus`, `UpdateInfo`) with `.raw` preserved
- [x] `__init__.py` — `connect()`, `connect_usb()`, `discover()`, `list_serial_ports()`, re-exports
  - [x] `connect()` name matching: case-insensitive exact → unique prefix → unique substring; IP literal skips discovery
- [x] `cli.py` — `vector` entry point (`discover`, `status`, `read`, `write`, `snapshot`, `update`, `version`)

## 3. Tests (`tests/`)
- [x] HMAC signing fixture test (password `"test"`, known digest)
- [x] Fake transport + wrapper route/auth-flag golden tests
- [x] Discovery FULL-frame decoding (hand-built bytes, truncated/garbage, PING/PONG noise)
- [x] USB framing (`\|` escaping, interleaved log lines, JSON-in-string body)
- [x] HTTP transport auth flow (challenge retry, error mapping) with mocked session
- [x] AddressMap encodings, save/load, chunked read/write
- [x] CLI smoke tests

## 4. Infrastructure
- [x] `.github/workflows/ci.yml` — lint (ruff) + pytest matrix, Python 3.9–3.13
- [x] `.github/workflows/publish.yml` — build + PyPI trusted publishing on GitHub release
- [x] Package build check (`python -m build`) in CI

## 5. Deferred / needs input
- [ ] Exact JSON body shapes for `/api/set_date`, `/api/adjustments/*`, `/api/memory-snapshot` auth — implemented per best reading of spec; verify against firmware (`src/common/backend.py`) which is **not present in this repo** (see notes/DECISIONS.md)
- [ ] Async `AsyncMachine` variant (stretch goal, not in v1)
- [ ] AP-mode setup routes (`/api/settings/set_vector_config`, `/api/available_ssids`) — skipped in v1 per spec
- [ ] Live smoke test against https://vector.doze.dev (read-only routes) — not run from this environment
- [ ] PyPI trusted-publisher configuration for the release workflow (one-time setup on pypi.org)
