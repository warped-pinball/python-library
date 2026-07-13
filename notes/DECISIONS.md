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
4. **`/api/set_date` body**: sends `{"date": [year, month, day, weekday, hour,
   minute, second, 0]}` (MicroPython RTC 8-tuple). `date()` accepts either that
   tuple shape or an ISO string in the response. **Verify against firmware.**
5. **Adjustments routes**: assumed `/api/adjustments/status` (GET, no auth),
   `/api/adjustments/capture` `{"index"}` (auth), `/api/adjustments/restore`
   `{"index"}` (auth, 5 s cooldown), `/api/adjustments/name`
   `{"index", "name"}` (auth). **Verify against `docs/routes.md`.**
6. **`check_for_updates()` URL key**: `apply_update()` with no `url` looks for
   `"url"` in the check response, falling back to `"update_url"`. **Verify.**
7. **BCD encoding**: packed BCD, most-significant byte first (standard
   Williams/Bally score storage). Two decimal digits per byte.
8. **`watch_game()` key detection**: the exact `/api/game/status` shape is not
   in the spec, so change detection is heuristic — it looks for keys matching
   game-active / ball-in-play / scores case-insensitively and falls back to a
   generic `status_changed` event. Tighten once the real shape is known.
9. **Wrapper return values**: wrappers return the parsed JSON from the device
   as-is (dicts/lists). `warpedpinball.models` offers lenient typed dataclasses
   (`Score`, `Player`, `GameStatus`, `UpdateInfo`) users can wrap raw payloads
   in; they are not forced on return values because the exact firmware shapes
   could not be verified from this repo.
10. **License**: MIT, committed as `LICENSE` and declared via `license = "MIT"`
    in `pyproject.toml`.
11. **`/api/memory-snapshot` auth**: the spec marks `/api/address/read`/`write`
    as authenticated but never states the snapshot route's auth requirement;
    `memory_snapshot()` currently calls it unauthenticated. **Verify against
    `docs/routes.md`** and flip to `authenticated=True` if needed.
12. **PyPI publishing**: workflow uses PyPI *trusted publishing* (OIDC) on
    GitHub release; the PyPI project must be configured with this repo as a
    trusted publisher before the first release.
