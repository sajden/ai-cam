# Data Model: Desk Presence Tracking

**Feature**: `004-presence-tracking`
**Date**: 2026-03-05

---

## New Table: `desk_trips`

Stores one row per away-trip. A trip begins when the person sensor goes OFF and ends when it returns ON.

```sql
CREATE TABLE IF NOT EXISTS desk_trips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,   -- YYYY-MM-DD in local timezone
    left_at      TEXT    NOT NULL,   -- ISO8601 UTC timestamp (sensor OFF)
    returned_at  TEXT,               -- ISO8601 UTC timestamp (sensor ON); NULL if still away
    duration_sec INTEGER,            -- seconds away; filled when returned_at is set
    time_of_day  TEXT    NOT NULL    -- 'morning' (06-12) / 'afternoon' (12-18) / 'evening' (18-23)
);
```

**Indexes**:
```sql
CREATE INDEX IF NOT EXISTS idx_desk_trips_date ON desk_trips(date);
```

**Rules**:
- Trips with `duration_sec < 60` are never inserted (filtered in application logic before write).
- Trips with `duration_sec > 14400` (4 hours) are inserted but excluded from desk-break aggregations via a `WHERE duration_sec <= 14400` filter in summary queries.
- If service restarts while user is away, the open trip row (`returned_at IS NULL`) is closed with `returned_at = startup_time` and flagged by having `duration_sec` computed from available timestamps.

---

## New CRUD Functions (db.py)

### `log_desk_trip_start(left_at: str, date: str, time_of_day: str) -> int`
Inserts a new trip row with `returned_at = NULL`. Returns the new row `id`.

### `log_desk_trip_end(trip_id: int, returned_at: str, duration_sec: int) -> None`
Updates the open trip row with return time and duration.

### `get_desk_summary_today(date: str) -> dict`
Returns aggregated stats for a given date:
```python
{
    "trip_count": int,           # number of completed trips (dur <= 4h)
    "avg_duration_sec": int,     # average trip duration
    "longest_trip_sec": int,     # longest single trip
    "longest_sitting_sec": int,  # longest gap between trips (in-desk streak)
    "last_left_at": str | None,  # ISO8601 of most recent departure
}
```

### `get_desk_summary_week(days: int = 7) -> list[dict]`
Returns one dict per day for the last `days` days, each with the same fields as `get_desk_summary_today`. Days with no data return zeros.

### `close_open_trips(now_utc: str) -> None`
Called at startup — closes any trip rows where `returned_at IS NULL` by setting `returned_at = now_utc` and computing `duration_sec`. Handles service restart edge case.

---

## In-Memory State (PresenceTracker)

Maintained by the background polling thread — not persisted:

```python
_person_present: bool         # last known sensor state
_away_since: float | None     # monotonic time when person left (None if at desk)
_open_trip_id: int | None     # db row id of current open trip
_at_desk_since: float         # monotonic time when person last returned
_last_comment_at: float       # monotonic time of last sitting-streak comment
```

---

## Context Block Shape (Codex injection)

Appended to the `[Session]` block in the system prompt when today has ≥ 1 completed trip or sitting streak > 30 min:

```
[Skrivbordsaktivitet idag]
- 4 pauser (snitt 6 min, längst 14 min kl 14:32)
- Suttit sammanhängande nu: 1 t 52 min
```

Weekly summary (appended when ≥ 3 days of data exist):
```
[Veckovanor]
- Snitt 5 pauser/dag, mest aktiv: måndag, minst: onsdag
```
