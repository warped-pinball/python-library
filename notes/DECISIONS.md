# Implementation decisions & assumptions

The spec references firmware sources (`src/common/backend.py`, `docs/routes.md`,
etc.) that are **not present in this repository** — the repo was empty at
implementation time. All protocol behavior was implemented from the spec text
alone. Where the spec left a gap, the choice made is recorded here so it can be
corrected against the real firmware later.

1. **HTTP client**: `requests` (spec allowed `requests` or `httpx`). The async
   variant is a stretch goal; if/when it lands, migrating to `httpx` for both
   is the path.
2. **HTTP method**: GET when there is no body, POST when there is one. The spec
   confirms phew routes ignore the method and POST-with-JSON works everywhere.
3. **JSON serialization**: `json.dumps(body, separators=(",", ":"))` — compact,
   serialized exactly once; the same string is signed and sent.
4. **`/api/set_date` body**: **Confirmed against `src/common/backend.py`.**
   Firmware does `date = [int(e) for e in request.json["date"]]` then
   `rtc.datetime((date[0], date[1], date[2], 0, date[3], date[4], date[5], 0))`
   — the wire body is `{"date": [year, month, day, hour, minute, second]}`, a
   **6-element** list with no weekday/subseconds; the firmware derives the
   weekday itself. The originally-implemented 8-element
   `[year, month, day, weekday, hour, minute, second, 0]` shape was wrong and
   would have been rejected/misread by the real device; fixed in
   `Machine.set_date()`. `/api/get_date` (`{"date": list(rtc.datetime())}`) is
   still the 8-tuple `(year, month, day, weekday, hour, minute, second, sub)`,
   which `date()` already parses correctly.
5. **Adjustments routes**: **Confirmed against `src/common/backend.py`.**
   `/api/adjustments/status` (GET, no auth) returns
   `{"profiles": [[name, active, exists], ...], "adjustments_support": bool}`;
   `/api/adjustments/capture` `{"index"}` (auth); `/api/adjustments/restore`
   `{"index"}` (auth, 5 s cooldown); `/api/adjustments/name`
   `{"index", "name"}` (auth). Matches the original implementation as-is.
6. **`check_for_updates()` URL key**: **Confirmed** — the firmware's
   `/api/update/check` proxies GitHub release JSON and only ever provides a
   `"url"` key; there is no `"update_url"` variant. Removed the speculative
   fallback from `apply_update()`.
7. **BCD encoding**: packed BCD, most-significant byte first (standard
   Williams/Bally score storage). Two decimal digits per byte. Not covered by
   the firmware route file (score encoding lives in `ScoreTrack`/`DataMapper`,
   not present here) — still unverified.
8. **`watch_game()` key detection**: `/api/game/status` (`src/common/backend.py`
   → `GameStatus.cached_report()`) is confirmed to return keys like
   `GameActive` (bool), `BallInPlay` (int), `Scores` (list[int]) — the existing
   fragment-matching heuristic (`gameactive`/`active`, `ball`, `score`) already
   covers this shape, so no code change was needed here.
9. **Wrapper return values**: wrappers return the parsed JSON from the device
   as-is (dicts/lists). `warpedpinball.models` offers lenient typed dataclasses
   (`Score`, `Player`, `GameStatus`, `UpdateInfo`) users can wrap raw payloads
   in; they are not forced on return values because the exact firmware shapes
   could not be verified from this repo.
10. **License**: MIT, committed as `LICENSE` and declared via `license = "MIT"`
    in `pyproject.toml`.
11. **`/api/memory-snapshot` auth**: **Confirmed against `src/common/backend.py`**
    — `@add_route("/api/memory-snapshot")` has no `auth=True`, so the route is
    genuinely unauthenticated. `memory_snapshot()` calling it unauthenticated
    was already correct; no change needed.
12. **PyPI publishing**: workflow uses PyPI *trusted publishing* (OIDC) on
    GitHub release; the PyPI project must be configured with this repo as a
    trusted publisher before the first release.
13. **Async `AsyncMachine` variant**: permanently out of scope per product
    owner — will not be built.
14. **AP-mode setup routes** (`/api/settings/set_vector_config`,
    `/api/available_ssids`): permanently out of scope per product owner —
    intentionally left unimplemented (v1 targets app-mode/station use only).
