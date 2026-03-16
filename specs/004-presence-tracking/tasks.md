# Tasks: Desk Presence Tracking

**Input**: Design documents from `/specs/004-presence-tracking/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Organization**: Tasks grouped by user story — each story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add new env vars so all later tasks can reference them.

- [X] T001 Add 6 `AIHUB_PRESENCE_*` env vars to `.env` with production values (`ENABLED=1`, `ENTITY=binary_sensor.reolink_e1pro_person`, `POLL_SEC=5`, `MIN_TRIP_SEC=60`, `MAX_TRIP_SEC=14400`, `SITTING_ALERT_SEC=7200`)
- [X] T002 Add 6 `AIHUB_PRESENCE_*` vars to `.env.example` with defaults and inline comments explaining each

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB table + CRUD must exist before any tracker logic can run.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `desk_trips` table DDL to `init_db()` in `ai-hub/app/db.py` — columns: `id`, `date` (TEXT YYYY-MM-DD), `left_at` (TEXT ISO8601), `returned_at` (TEXT ISO8601 nullable), `duration_sec` (INTEGER nullable), `time_of_day` (TEXT: morning/afternoon/evening); add index on `date`
- [X] T004 Add `log_desk_trip_start(left_at: str, date: str, time_of_day: str) -> int` to `ai-hub/app/db.py` — inserts open trip row, returns new row id
- [X] T005 Add `log_desk_trip_end(trip_id: int, returned_at: str, duration_sec: int) -> None` to `ai-hub/app/db.py` — updates open trip row with return time and duration
- [X] T006 Add `get_desk_summary_today(date: str) -> dict` to `ai-hub/app/db.py` — returns `{trip_count, avg_duration_sec, longest_trip_sec, longest_sitting_sec, last_left_at}` for completed trips (60s ≤ duration ≤ 14400s)
- [X] T007 Add `get_desk_summary_week(days: int = 7) -> list[dict]` to `ai-hub/app/db.py` — returns one dict per day for the last `days` days; days with no data return zeros
- [X] T008 Add `close_open_trips(now_utc: str) -> None` to `ai-hub/app/db.py` — closes any rows where `returned_at IS NULL` by computing duration from `left_at` to `now_utc`

**Checkpoint**: DB layer complete — can be verified by running `init_db()` and checking table exists.

---

## Phase 3: User Story 1 — Daily Away-Trip Summary (Priority: P1) 🎯 MVP

**Goal**: Track away-trips in the background; Jarvis answers "hur många gånger har jag gått ifrån datorn idag?" correctly.

**Independent Test**: Walk away from the desk for 90+ seconds, return, restart aihub, then ask Jarvis the question above. Verify count and duration are correct. Check `desk_trips` table directly.

### Implementation

- [X] T009 [US1] Add `PresenceTracker` class to `ai-hub/app/main.py` — reads env vars (`AIHUB_PRESENCE_ENABLED`, `AIHUB_PRESENCE_ENTITY`, `AIHUB_PRESENCE_POLL_SEC`, `AIHUB_PRESENCE_MIN_TRIP_SEC`, `AIHUB_PRESENCE_MAX_TRIP_SEC`), holds in-memory state (`_person_present`, `_away_since`, `_open_trip_id`, `_at_desk_since`), exposes `start()` and `get_today_summary()` methods
- [X] T010 [US1] Implement polling loop inside `PresenceTracker._run()` in `ai-hub/app/main.py` — calls `get_ha_state(cfg, PRESENCE_ENTITY)` every `POLL_SEC` seconds; detects ON→OFF transition (call `log_desk_trip_start()`), OFF→ON transition (call `log_desk_trip_end()` if `duration >= MIN_TRIP_SEC`, else discard); wraps all in try/except with `log.warning` on HA errors
- [X] T011 [US1] Call `db.close_open_trips()` then `tracker.start()` inside `startup()` in `ai-hub/app/main.py` — initialise a module-level `_presence_tracker: PresenceTracker | None` and start it only if `PRESENCE_ENABLED=1`
- [X] T012 [US1] Inject daily presence summary into `_build_session_context_block()` in `ai-hub/app/codex_client.py` — call `db.get_desk_summary_today(today_date)` and append a `[Skrivbordsaktivitet idag]` block when `trip_count > 0` or `longest_sitting_sec > 1800`; format: "X pauser (snitt Y min, längst Z min), suttit sammanhängande: W min"

**Checkpoint**: User Story 1 fully testable — walk away, return, ask Jarvis.

---

## Phase 4: User Story 2 — Spontaneous Awareness Comments (Priority: P2)

**Goal**: Jarvis proactively mentions long sitting streaks without being asked — at most once per hour.

**Independent Test**: Sit for 2+ hours (or manually set `SITTING_ALERT_SEC=120` for testing), then speak to Jarvis on any topic. Verify Jarvis mentions the sitting streak exactly once; speak again within the hour and verify no repeat.

### Implementation

- [X] T013 [US2] Add `_last_sitting_comment_at: float = 0.0` in-memory field to `PresenceTracker` in `ai-hub/app/main.py`
- [X] T014 [US2] Add `get_sitting_comment() -> str | None` method to `PresenceTracker` in `ai-hub/app/main.py` — returns a Swedish comment string if `(now - _at_desk_since) >= SITTING_ALERT_SEC` AND `(now - _last_sitting_comment_at) >= 3600`, then sets `_last_sitting_comment_at = now`; returns `None` otherwise
- [X] T015 [US2] In the conversation turn handler in `ai-hub/app/main.py`, call `_presence_tracker.get_sitting_comment()` after a successful Codex reply is built; if non-None, append the comment to `assistant_text` with a newline separator (only if `_presence_tracker` is not None and `PRESENCE_ENABLED=1`)

**Checkpoint**: User Stories 1 AND 2 work — trip counting correct, spontaneous comment fires once per 1h sitting streak.

---

## Phase 5: User Story 3 — Weekly Patterns (Priority: P3)

**Goal**: Jarvis describes weekly desk habits when asked ("hur ser mina vanor ut den här veckan?").

**Independent Test**: After 3+ days of trip data (or seed test rows directly into `desk_trips`), ask Jarvis the weekly pattern question. Verify response mentions at least: most active day, quietest day, average break frequency.

### Implementation

- [X] T016 [US3] Inject weekly presence summary into `_build_session_context_block()` in `ai-hub/app/codex_client.py` — call `db.get_desk_summary_week(7)`, compute most/least active day and average daily trip count; append a `[Veckovanor]` block when ≥ 3 days have data; format: "Snitt X pauser/dag, mest aktiv: [dag], minst: [dag]"
- [X] T017 [US3] Add deviation comment to daily block in `_build_session_context_block()` in `ai-hub/app/codex_client.py` — if today's `trip_count` differs from weekly average by ≥ 30%, append: "Idag rör du dig [mer/mindre] än vanligt"

**Checkpoint**: All three user stories functional — query weekly patterns, verify meaningful output.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T018 [P] Add `INFO` startup log in `PresenceTracker.start()` in `ai-hub/app/main.py`: `"Presence tracker started (entity=%s, poll=%ds)"` — matches quickstart.md verify step
- [ ] T019 [P] Verify graceful degradation: take HA offline (stop container), confirm aihub logs show `WARNING` not `ERROR`, no crash, no user-facing error message
- [ ] T020 Run quickstart.md validation steps: walk away 90s, return, ask Jarvis, verify response and DB rows

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — T009/T010 can run in parallel, T011 depends on T009+T010, T012 is independent
- **Phase 4 (US2)**: Depends on Phase 3 complete (needs `PresenceTracker` class)
- **Phase 5 (US3)**: Depends on Phase 2 only (only adds to codex_client.py, independent of US2)
- **Phase 6 (Polish)**: Depends on all desired stories complete

### Parallel Opportunities

- T001 and T002 can run in parallel (different files)
- T003–T008 can all run in parallel (all in db.py, non-overlapping functions)
- T009 and T012 can run in parallel (different files: main.py vs codex_client.py)
- T016 and T017 are in the same file but non-overlapping edits — sequential within phase
- T018 and T019 can run in parallel

---

## Implementation Strategy

### MVP (User Story 1 only — ~8 tasks)

1. Phase 1: T001, T002
2. Phase 2: T003–T008
3. Phase 3: T009–T012
4. **STOP and validate**: walk away, ask Jarvis, check DB
5. Rebuild: `docker compose up -d --build aihub`

### Full Feature

Continue with Phase 4 (US2), Phase 5 (US3), Phase 6 (Polish) after MVP is validated.

---

## Notes

- All tasks modify existing files — no new files needed
- Rebuild required after each phase: `docker compose up -d --build aihub`
- Test DB directly between phases: `docker exec ai-cam-aihub python3 -c "import sqlite3; ..."`
- `AIHUB_PRESENCE_SITTING_ALERT_SEC=120` for fast testing of US2 (2 min instead of 2 hours)
