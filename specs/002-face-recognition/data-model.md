# Data Model: AI Companion — Identity, Memory & Embodiment

**Branch**: `002-face-recognition` | **Date**: 2026-03-03

---

## Existing Tables (unchanged)

These tables already exist in `aihub.db` and are used as-is:

| Table | Purpose | Relevant fields |
|---|---|---|
| `athletes` | Named persons | `id`, `name` (UNIQUE) |
| `person_profiles` | Identity metadata | `athlete_id`, `display_name` |
| `face_embeddings` | Stored face vectors | `person_id`, `embedding_json`, `source`, `quality` |
| `conversation_identity` | Who is in a conversation | `conversation_id`, `person_id`, `confidence` |
| `mode_state` | Key-value runtime state | extended with new keys |

---

## New Table: `person_presence`

Tracks arrival/departure state per person for cooldown logic.

```sql
CREATE TABLE IF NOT EXISTS person_presence (
    person_name     TEXT PRIMARY KEY,           -- matches athletes.name
    last_seen_at    TEXT NOT NULL,              -- ISO8601 UTC, updated every recognition
    arrived_at      TEXT NOT NULL,              -- ISO8601 UTC, set when arrival detected
    greeted_at      TEXT                        -- ISO8601 UTC, set when greeting spoken (nullable)
);
```

**Logic**:
- `last_seen_at` > `AIHUB_ARRIVAL_COOLDOWN_SEC` ago → new arrival (upsert `arrived_at`, clear `greeted_at`)
- On greeting spoken → set `greeted_at = now()`
- On every recognition → update `last_seen_at = now()`

---

## New Table: `memory_facts`

Stores extracted facts from conversations for long-term companion memory.

```sql
CREATE TABLE IF NOT EXISTS memory_facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name     TEXT NOT NULL,              -- matches athletes.name
    fact_text       TEXT NOT NULL,              -- plain Swedish sentence
    category        TEXT NOT NULL,              -- mood | event | plan | preference | health | social
    source_conv_id  TEXT,                       -- conversation_id it was extracted from
    extracted_at    TEXT NOT NULL,              -- ISO8601 UTC
    follow_up_date  TEXT,                       -- ISO8601 UTC, nullable — triggers proactive follow-up
    followed_up_at  TEXT,                       -- ISO8601 UTC, set when follow-up spoken
    active          INTEGER NOT NULL DEFAULT 1  -- 0 = dismissed/superseded
);

CREATE INDEX IF NOT EXISTS idx_memory_facts_person
    ON memory_facts(person_name, extracted_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_facts_followup
    ON memory_facts(follow_up_date)
    WHERE follow_up_date IS NOT NULL AND followed_up_at IS NULL AND active = 1;
```

**Categories**:
- `mood` — "Sebastian verkade trött och stressad"
- `event` — "Sebastian har ett viktigt möte på fredag"
- `plan` — "Sebastian planerar att börja springa mer"
- `preference` — "Sebastian gillar inte måndagar"
- `health` — "Sebastian sov dåligt igår natt"
- `social` — "Susanne (mamman) hälsade på i helgen"

---

## New `mode_state` Keys

Extend the existing key-value table with:

| Key | Value | Purpose |
|---|---|---|
| `last_unknown_face_at` | ISO8601 UTC | Cooldown for "vem är du?" prompt |
| `proactive_morning_scheduled` | `true`/`false` | Prevent double-scheduling morning greeting |
| `active_person_name` | string or empty | Currently identified person in frame |

---

## face-recognition Service: In-Memory State

The `face-recognition` container maintains enrolled embeddings in memory (loaded from disk on startup):

```python
# In-memory enrollment store (backed by ai-hub SQLite via API call)
enrolled: dict[str, list[np.ndarray]]  # name -> list of normed 512-D embeddings
```

On startup: fetches all stored embeddings from ai-hub `GET /v1/persons/embeddings` and loads into memory.
On new enrollment: stores in memory + calls ai-hub `POST /v1/persons/{name}/embedding` to persist.

---

## InsightFace Embedding Format Change

The existing `face_embeddings` table stores 128-D pixel-hash embeddings. InsightFace produces 512-D ArcFace embeddings.

**Migration strategy**:
- New InsightFace embeddings stored with `source = "insightface_buffalo_l"`
- Old pixel-hash embeddings (`source = "vision_loop_*"`) are ignored by the new recognizer
- `resolve_identity_by_embedding()` in db.py filters by `source LIKE 'insightface%'` when called from face-recognition service
- No schema change needed — existing `embedding_json` column holds both (different lengths)

---

## Entity Relationships

```
athletes (person)
    ├── face_embeddings (1:N) ← InsightFace enrollment
    ├── person_presence (1:1) ← arrival/cooldown state
    ├── memory_facts (1:N)    ← extracted conversation facts
    ├── conversation_identity (1:N) ← active conversation binding
    └── task_identity (1:N)   ← active workout binding
```
