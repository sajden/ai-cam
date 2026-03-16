# Implementation Plan: Desk Presence Tracking

**Branch**: `004-presence-tracking` | **Date**: 2026-03-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-presence-tracking/spec.md`

## Summary

Track how many times the user leaves and returns to their desk by polling the existing Home Assistant Reolink person sensor (`binary_sensor.reolink_e1pro_person`) every 5 seconds from a background thread. Store each away-trip in SQLite. Inject a compact daily/weekly summary into the Codex system prompt so Jarvis can comment naturally on presence patterns — no VLM, no new hardware, no new external dependencies.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI + Uvicorn (existing), SQLite via stdlib `sqlite3` (existing), `urllib.request` for HA REST polling (existing)
**Storage**: SQLite `aihub.db` — new `desk_trips` table
**Testing**: Manual spot-check (step away from desk, verify trip recorded correctly)
**Target Platform**: Linux Docker container (`ai-hub` service)
**Project Type**: web-service extension (adds background thread + DB table to existing service)
**Performance Goals**: Presence state updated within 5s of actual transition; daily summary query < 50ms
**Constraints**: No new Python packages; no data leaves local network; degrade gracefully if HA offline
**Scale/Scope**: Single user; hundreds of trips per month; < 10 KB/month storage growth

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Privacy-by-Default | ✅ PASS | All data stays local; only polls HA over internal Docker network; no audio/video sent anywhere |
| II. Container-First | ✅ PASS | All new code lives in the existing `ai-hub` container; no new container needed |
| III. Config-as-Environment | ✅ PASS | All 6 new vars are env-var driven with documented defaults in `.env.example` |
| IV. Graceful Degradation | ✅ PASS | If HA offline → polling loop logs warning and retries; no crash; no user-facing errors |
| V. Minimal External Surface | ✅ PASS | No new external API calls; reuses existing `get_ha_state()` pattern |

**Post-design re-check**: No violations introduced in Phase 1 design.

## Project Structure

### Documentation (this feature)

```text
specs/004-presence-tracking/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
ai-hub/app/
├── main.py              # MODIFIED: PresenceTracker class + startup() hook
├── db.py                # MODIFIED: desk_trips table + 4 new CRUD functions
└── codex_client.py      # MODIFIED: presence summary in _build_session_context_block()

.env                     # MODIFIED: 6 new AIHUB_PRESENCE_* vars
.env.example             # MODIFIED: document 6 new vars
```

**Structure Decision**: Pure extension of the existing single-service layout. No new files, no new containers. Follows the exact same pattern as `memory_manager.py` (background thread), `person_presence` table (DB extension), and `_build_session_context_block()` (context injection).

## Data Model

See [data-model.md](data-model.md).

## API Contracts

No new HTTP endpoints. The feature is internal to `ai-hub`: background thread writes to DB, context injected into Codex prompts.

## Complexity Tracking

> No constitution violations — table left intentionally empty.
