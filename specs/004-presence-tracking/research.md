# Research: Desk Presence Tracking

**Feature**: `004-presence-tracking`
**Phase**: 0 – Outline & Research
**Date**: 2026-03-05

---

## Finding 1: HA Sensor Integration — Polling vs Webhooks

### Decision
Poll `binary_sensor.reolink_e1pro_person` via the existing `get_ha_state()` REST call every 5 seconds in a background daemon thread.

### Rationale
The codebase has no event subscription infrastructure. `get_ha_state()` in `actions.py` (line 153) already calls `HA_BASE_URL/api/states/{entity_id}` synchronously. A background thread calling it every 5s is the simplest, most consistent approach. 5s polling lag means a trip that lasts 60s is detected within 5s — acceptable.

HA webhooks/WebSocket subscriptions would be more real-time but require a new server-side listener and session management — disproportionate complexity for a 5s accuracy target.

### Alternatives Considered
- **HA WebSocket API**: Real-time, but requires `websockets` package (new dependency) and persistent WS session management. Rejected: YAGNI.
- **MQTT events from Reolink/HA**: Mosquitto is in the stack, but HA person sensor events are not currently published to MQTT. Rejected: requires HA automation setup outside this service.

---

## Finding 2: Where to Store Trip Data

### Decision
Add a `desk_trips` table to the existing SQLite database at `/data/aihub.db` managed by `ai-hub/app/db.py`. No new database or file.

### Rationale
All persistent data lives in `aihub.db` (mode_state, conversation_turns, memory_facts, person_presence, etc.). Adding `desk_trips` follows the exact same pattern as the 15 existing tables. The `init_db()` function runs at startup and creates tables if missing — zero migration friction.

### Table Schema
```sql
CREATE TABLE IF NOT EXISTS desk_trips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,          -- YYYY-MM-DD local date
    left_at     TEXT NOT NULL,          -- ISO8601 UTC
    returned_at TEXT,                   -- ISO8601 UTC (NULL if still away)
    duration_sec INTEGER,               -- filled on return
    time_of_day TEXT                    -- morning / afternoon / evening
);
```

---

## Finding 3: Context Injection into Codex

### Decision
Extend `_build_session_context_block()` in `codex_client.py` to append a presence summary block when data exists. No new call path — this function already runs on every conversation turn.

### Rationale
`_build_session_context_block()` (line 119, `codex_client.py`) is the single point where dynamic context is added to the system prompt. It already injects identity, time_of_day, recent_activity, and memory_facts. Adding a presence summary here follows the established pattern with zero routing changes.

The presence summary is computed once per turn (from a fast SQLite query + in-memory cache) and appended as a compact block:
```
[Skrivbordsaktivitet idag]
- 4 pauser (snitt 6 min, längst 14 min)
- Suttit sammanhängande: 1 t 45 min
```

### Alternatives Considered
- Inject only on demand (when user asks): Would miss spontaneous comments. Rejected.
- Separate Codex context field: Would require changes to `ask_codex()` signature and all callers. Rejected.

---

## Finding 4: Spontaneous Comment Guard

### Decision
Track `_last_sitting_comment_at` (Unix timestamp, in-memory) in the presence tracker. Only emit a sitting-streak comment if `now - _last_sitting_comment_at > 3600s` (1 hour).

### Rationale
FR-008 requires Jarvis to mention long sitting at most once per conversation session. Using a 1-hour wall-clock guard (not session-based) is simpler and more robust than tracking conversation sessions in the presence module. If Jarvis speaks every 30 minutes, this means at most one comment per hour — well within spec.

---

## Finding 5: New Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AIHUB_PRESENCE_ENTITY` | `binary_sensor.reolink_e1pro_person` | HA entity to poll |
| `AIHUB_PRESENCE_POLL_SEC` | `5` | Polling interval in seconds |
| `AIHUB_PRESENCE_MIN_TRIP_SEC` | `60` | Trips shorter than this are discarded |
| `AIHUB_PRESENCE_MAX_TRIP_SEC` | `14400` | Trips longer are flagged as "left home" |
| `AIHUB_PRESENCE_SITTING_ALERT_SEC` | `7200` | Sitting streak that triggers a comment (2 h) |
| `AIHUB_PRESENCE_ENABLED` | `1` | Feature on/off flag |

---

## Summary of Changes Required

| Component | File | Change |
|-----------|------|--------|
| ai-hub | `app/db.py` | Add `desk_trips` table + CRUD: `log_desk_trip_start()`, `log_desk_trip_end()`, `get_desk_summary_today()`, `get_desk_summary_week()` |
| ai-hub | `app/main.py` | Add `PresenceTracker` class (background polling thread) + call `tracker.start()` in `startup()` |
| ai-hub | `app/codex_client.py` | Extend `_build_session_context_block()` to append presence summary |
| `.env` | `.env` | Add 6 new `AIHUB_PRESENCE_*` vars |
| `.env.example` | `.env.example` | Document all 6 new vars with defaults |
