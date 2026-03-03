# Data Model: Humanize AI Companion Personality

**Branch**: `001-humanize-ai-companion` | **Date**: 2026-02-26

## Overview

This feature adds two new data concerns to the existing `aihub.db` SQLite database:
1. **Response pool LRU tracking** — persist least-recently-used state for phrase variant selection across container restarts.
2. **Per-identity companion preference** — store each registered identity's mode preference (companion vs. minimal/direct) durably across sessions.

No new databases or services are introduced. Both additions extend the existing SQLite schema managed by `ai-hub/app/db.py`.

---

## New Table: `response_pool_usage`

Tracks the last time each phrase variant was selected, per named pool, per identity (optional). Used to enforce LRU selection so no phrase repeats more than twice consecutively (SC-001, SC-002).

```sql
CREATE TABLE IF NOT EXISTS response_pool_usage (
    pool_name    TEXT NOT NULL,
    variant_key  TEXT NOT NULL,
    used_at      TEXT NOT NULL,   -- ISO-8601 UTC timestamp
    PRIMARY KEY (pool_name, variant_key)
);
```

**Fields**:
- `pool_name` — Canonical pool identifier (e.g., `"wake_morning"`, `"spotify_pause"`, `"workout_followup"`). Scoped to a single identity if needed by appending `_pid_{person_id}` suffix.
- `variant_key` — Stable string key for the phrase (e.g., hash or short slug of the phrase text). Allows phrase text to change without losing LRU history.
- `used_at` — ISO-8601 UTC timestamp of last selection. Used for LRU ordering on startup.

**Access pattern**:
- On startup: `SELECT pool_name, variant_key, used_at FROM response_pool_usage ORDER BY used_at ASC` — seeds in-memory `OrderedDict`.
- On selection: `INSERT OR REPLACE INTO response_pool_usage (pool_name, variant_key, used_at) VALUES (?, ?, ?)` — write-through after each variant pick.
- Reads in the hot path are served entirely from in-memory `OrderedDict`; SQLite is write-only at runtime.

---

## Per-Identity Companion Preference

Stored in the existing `mode_state` table (key-value store at `ai-hub/app/db.py:37`) using a namespaced key per identity.

**Key format**: `companion_pref_{person_id}` where `person_id` is the integer primary key from `person_profiles`.

**Values**: `"full"` (companion mode, default) | `"minimal"` (minimal/direct mode).

**No schema migration required.** The `mode_state` table already uses `ON CONFLICT DO UPDATE` upsert semantics. New keys are written on first use.

**Example entries**:
```
key: "companion_pref_1"    value: "minimal"    (Sebastian has minimal mode active)
key: "companion_pref_2"    value: "full"       (another identity, companion mode)
```

**Access pattern**:
- Read: `SELECT value FROM mode_state WHERE key = 'companion_pref_{person_id}'` — returns `"full"` if absent (default).
- Write: standard `set_mode_state({"companion_pref_{person_id}": "minimal"})` upsert.

---

## Existing Tables Used (Read-Only for This Feature)

| Table | Purpose in this feature |
|-------|------------------------|
| `person_profiles` | Look up `person_id` by display name to namespace pool and preference keys |
| `conversation_identity` | Resolve current identity from active `conversation_id` |
| `task_sessions` + `workouts` | Determine `recent_activity` for session context injection and follow-up remark eligibility |
| `mode_state` | Read companion preference; write mode-switch updates |

---

## In-Memory State (Runtime Only)

| Name | Type | Purpose |
|------|------|---------|
| `_pool_lru` | `dict[str, OrderedDict[str, float]]` | LRU cache per pool; keyed by `pool_name`, values are `variant_key → last_used_epoch` |
| `_pool_lock` | `threading.Lock` | Guards all mutations to `_pool_lru` across TTS daemon threads |
| `_followup_cancel` | `threading.Event` | Cancel flag for pending deferred follow-up TTS utterance |
| `_followup_lock` | `threading.Lock` | Guards `_pending_followup_timer` reference |
| `_pending_followup_timer` | `threading.Timer \| None` | Currently scheduled follow-up remark timer; `None` if none pending |

---

## Response Pool Definitions (Compile-Time)

Phrase pools are defined as Python data structures in `ai-hub/app/response_pool.py`. They are not stored in the database.

Each pool entry has a stable `key` (used as `variant_key` in DB), the `text` (with optional `{name}` format placeholder), and optional `context` metadata for eligibility filtering.

```
Pool: wake_morning          (time_of_day=morning, recency=any)
Pool: wake_afternoon        (time_of_day=afternoon, recency=any)
Pool: wake_evening          (time_of_day=evening, recency=any)
Pool: wake_continuity       (recency=recent, any time)
Pool: spotify_play          (action=spotify_play)
Pool: spotify_pause         (action=spotify_pause)
Pool: spotify_next          (action=spotify_next)
Pool: spotify_prev          (action=spotify_prev)
Pool: follow_start          (action=camera_follow_start)
Pool: follow_stop           (action=camera_follow_stop)
Pool: training_start        (action=training_start, identity=known)
Pool: training_stop         (action=training_stop)
Pool: workout_followup      (action=training_stop, companion_mode=full)
Pool: processing_ack        (action=processing_ack)
Pool: error_generic         (action=error)
```

---

## State Lifecycle

```
Container start
    └── db.init_db()
        └── CREATE TABLE IF NOT EXISTS response_pool_usage
    └── response_pool.load_lru_from_db()
        └── SELECT → seed _pool_lru OrderedDict

Wake word received
    └── resolve identity from conversation_identity
    └── get companion_pref_{person_id} from mode_state
    └── response_pool.pick("wake_{time_of_day}", context)
        └── LRU select → INSERT OR REPLACE response_pool_usage
    └── speak_to_camera(phrase)

Training session ends
    └── response_pool.pick("training_stop", context)
        └── LRU select → INSERT OR REPLACE response_pool_usage
    └── speak_to_camera(confirmation)
    └── if companion_mode AND random() < 0.3:
        └── schedule_followup(response_pool.pick("workout_followup"), delay=1.5)
            └── threading.Timer → _deliver (cancellable via threading.Event)

New audio turn arrives
    └── cancel_followup()  ← cancels any pending Timer + sets Event
    └── _detect_minimal_mode_switch(user_text)
        └── if match: set_mode_state, speak confirmation, return early

Container stop
    └── response_pool_usage rows persist in SQLite → survive restart
```
