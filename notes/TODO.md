# warped-pinball-vector — Implementation TODO

Tracking list for the Python client library implementation. Checked items are
complete; unchecked items are pending. See `notes/DECISIONS.md` for assumptions
made where the spec was ambiguous.

## 1. Project scaffolding
- [ ] `pyproject.toml` (distribution `warped-pinball-vector`, package `warpedpinball`, Python 3.9+, `requests` dep, `pyserial` behind `[usb]` extra, `vector` console entry point)
- [ ] `README.md` (install, quickstart, discovery, auth, USB, address maps, CLI)
- [ ] `.gitignore`
- [ ] License file — **needs product-owner decision** (none committed yet)

## 2. Core library (`warpedpinball/`)
- [ ] `exceptions.py` — typed error hierarchy
  - [ ] `VectorError` base
  - [ ] `MachineNotFoundError` (carries names that *were* seen)
  - [ ] `AmbiguousMachineError` (carries candidates)
  - [ ] `AuthenticationRequiredError` (raised before any network traffic)
  - [ ] `AuthenticationError` (401, carries device reason)
  - [ ] `CooldownError` (409 "Already running" / cooldown 429s, carries retry hint)
  - [ ] `RateLimitedError` (429 on challenge fetch)
  - [ ] `VectorServerError` (5xx, carries handler error string)
  - [ ] `UnsupportedFirmwareError` (404 on wrapper routes)
  - [ ] `TransportError` (connection/timeout/protocol failures)
- [ ] `auth.py` — HMAC-SHA256 challenge/response signing
  - [ ] `sign(password, challenge, path, body)` — message = challenge + path-sans-query + exact body string
  - [ ] retry-once policy on "Challenge expired"/"Invalid challenge"; never on "Bad Credentials"
- [ ] `transports/__init__.py` — `Transport` ABC (`request`, `stream`, `close`, `requires_password`)
- [ ] `transports/http.py` — HTTP transport
  - [ ] serialize JSON once, sign that exact string, send it
  - [ ] challenge fetch per request (single-use), 429 → short sleep + retry, then `RateLimitedError`
  - [ ] `x-auth-challenge` / `x-auth-hmac` headers
  - [ ] status → typed exception mapping (incl. per-route cooldown hints)
  - [ ] streaming via `iter_content` for `/api/memory-snapshot`, `/api/logs`, `/api/update/apply`
  - [ ] idempotent GET: one retry on connection error; no retries on mutating routes
- [ ] `transports/usb.py` — USB serial transport
  - [ ] `route|headers|body\n` framing with `\|` escaping
  - [ ] skip console noise, find `USB API RESPONSE-->` line, decode JSON envelope, parse JSON-ish body
  - [ ] no HMAC (firmware trusts physical access); `requires_password = False`
  - [ ] 115200 baud, ~10 s read timeout, ~2 s settle sleep after open
  - [ ] `list_serial_ports()` filtered to Raspberry Pi VID 0x2E8A
  - [ ] streaming routes returned as one large chunk (documented)
- [ ] `discovery.py` — UDP discovery client (port 37020)
  - [ ] HELLO broadcast frame builder, re-broadcast every ~2 s
  - [ ] FULL frame parser (tolerates PING/PONG/OFFLINE noise, truncated/garbage frames)
  - [ ] bind 37020 with fallback to ephemeral port
  - [ ] `DiscoveredMachine(ip, name)` dataclass, dedup by IP, early exit on name match
- [ ] `addresses.py` — `AddressMap`
  - [ ] `define(name, offset, length=1, encoding=None)`
  - [ ] encodings: `"bcd"`, `"le_uint"`, `"be_uint"`, custom `(decode, encode)` pair
  - [ ] `save(path)` / `AddressMap.load(path)` incl. `active_config`, mismatch warning
  - [ ] registry convention: `~/.warpedpinball/addressmaps/<active_config>.json` auto-load
- [ ] `machine.py` — `Machine`
  - [ ] per-machine lock; all traffic serialized
  - [ ] context manager
  - [ ] password: ctor / attribute / `VECTOR_PASSWORD` env fallback; pre-flight `AuthenticationRequiredError`
  - [ ] raw escape hatch: `call()`, `call_stream()`
  - [ ] memory: `read`, `write`, `read_bytes`, `write_bytes` (auto-chunked at 256), `memory_snapshot()`, `diff_snapshots()`
  - [ ] wrappers: version, machine_id, game_name, game_status, reboot_game, reboot, leaderboard, tournament, reset_leaderboard, reset_tournament, claimable_scores, claim_score, players, update_player, check_for_updates, apply_update(progress=), date, set_date, wifi_status, faults, logs, export_scores, import_scores, adjustments, capture_adjustments, restore_adjustments, name_adjustment, peers, verify_password
  - [ ] `watch_game(interval=1.0)` polling generator (game start/end, ball change, score deltas)
  - [ ] `wait_until_reachable(timeout)`
  - [ ] firmware-version gating: 404 on wrapper → `UnsupportedFirmwareError`
- [ ] `models.py` — typed dataclasses (`Score`, `Player`, `GameStatus`, `UpdateInfo`) with `.raw` preserved
- [ ] `__init__.py` — `connect()`, `connect_usb()`, `discover()`, `list_serial_ports()`, re-exports
  - [ ] `connect()` name matching: case-insensitive exact → unique prefix → unique substring; IP literal skips discovery
- [ ] `cli.py` — `vector` entry point (`discover`, `status`, `read`, `write`, `snapshot`, `update`, `version`)

## 3. Tests (`tests/`)
- [ ] HMAC signing fixture test (password `"test"`, known digest)
- [ ] Fake transport + wrapper route/auth-flag golden tests
- [ ] Discovery FULL-frame decoding (hand-built bytes, truncated/garbage, PING/PONG noise)
- [ ] USB framing (`\|` escaping, interleaved log lines, JSON-in-string body)
- [ ] HTTP transport auth flow (challenge retry, error mapping) with mocked session
- [ ] AddressMap encodings, save/load, chunked read/write
- [ ] CLI smoke tests

## 4. Infrastructure
- [ ] `.github/workflows/ci.yml` — lint (ruff) + pytest matrix, Python 3.9–3.13
- [ ] `.github/workflows/publish.yml` — build + PyPI trusted publishing on GitHub release
- [ ] Package build check (`python -m build`) in CI

## 5. Deferred / needs input
- [ ] License choice (MIT assumed in pyproject metadata? — left unset pending decision)
- [ ] Exact JSON body shapes for `/api/set_date`, `/api/adjustments/*` — implemented per best reading of spec; verify against firmware (`src/common/backend.py`) which is **not present in this repo**
- [ ] Async `AsyncMachine` variant (stretch goal, not in v1)
- [ ] AP-mode setup routes (`/api/settings/set_vector_config`, `/api/available_ssids`) — skipped in v1 per spec
- [ ] Live smoke test against https://vector.doze.dev (read-only routes)
