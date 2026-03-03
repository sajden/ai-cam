# Implementation Plan: Humanize AI Companion Personality

**Branch**: `001-humanize-ai-companion` | **Date**: 2026-02-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-humanize-ai-companion/spec.md`

## Summary

Replace all hardcoded single-phrase response strings in the `ai-hub` service with contextual phrase pools using LRU variant selection, add a deferred follow-up remark mechanism for workout sessions, expand the Codex system prompt with warmth and social engagement guidance, and introduce per-identity persistent minimal/direct mode. All changes are confined to the `ai-hub` container; no new services, dependencies, or external APIs are introduced.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: FastAPI 0.115.6, Uvicorn 0.32.1, Pillow 10.4.0, OpenCV-headless 0.10.0.84 (no new dependencies required)
**Storage**: SQLite at `/data/aihub.db` via `ai-hub/app/db.py` — one new table (`response_pool_usage`), one new key namespace in existing `mode_state` table (`companion_pref_{person_id}`)
**Testing**: No existing test framework; acceptance tests via `curl` against the running container (see `quickstart.md`)
**Target Platform**: Docker container on WSL2 / Linux
**Project Type**: Internal microservice (voice assistant hub)
**Performance Goals**: Wake-ack response must remain within existing `LATENCY_BUDGET_TURN_TOTAL_MS`. Pool variant selection is in-memory (O(1)) with one async-safe SQLite write-through; no additional latency introduced to the hot path.
**Constraints**: No new Docker services. No new Python packages. No raw audio or video egress (Constitution Principle I). All new tunable values exposed as env vars with defaults in `.env.example` (Constitution Principle III).
**Scale/Scope**: Single-household, single-container service. One `ai-hub` instance.

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Privacy-by-Default | ✅ Pass | No new data egress. Dynamic context injected into system prompt is text-only (identity name, time of day, recent activity summary) — consistent with existing Codex text-only policy. |
| II. Container-First Architecture | ✅ Pass | All changes confined to `ai-hub` container. No new containers or shared code across services. |
| III. Config-as-Environment | ✅ Pass | All new tunable parameters (`AIHUB_MINIMAL_MODE_ON_ACK_TEXT`, `AIHUB_MINIMAL_MODE_OFF_ACK_TEXT`, `AIHUB_FOLLOWUP_DELAY_SEC`, `AIHUB_FOLLOWUP_PROBABILITY`) added to `.env.example` with safe defaults. |
| IV. Graceful Degradation | ✅ Pass | LRU pool selection falls back to random selection if all variants recently used. Deferred follow-up failure is caught and logged, never propagated. New DB tables created with `CREATE TABLE IF NOT EXISTS`. |
| V. Minimal External Surface | ✅ Pass | Zero new external API calls. No new services. New SQLite table adds one write per interaction. System prompt expansion adds ~60–90 tokens; within budget. YAGNI: no speculative configurability beyond what specs require. |

## Project Structure

### Documentation (this feature)

```text
specs/001-humanize-ai-companion/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code Changes

```text
ai-hub/app/
├── response_pool.py     # NEW — phrase pool definitions + LRU variant selector
├── main.py              # MODIFIED — replace hardcoded strings, add follow-up
│                        #   scheduler, add minimal mode pre-flight, inject
│                        #   session context into Codex calls
├── db.py                # MODIFIED — add response_pool_usage table + CRUD,
│                        #   add get/set companion preference helpers,
│                        #   add get_last_interaction_for_person()
└── codex_client.py      # MODIFIED — expand base system prompt with persona
│                        #   section, add build_system_prompt() for dynamic
│                        #   session context suffix
.env.example             # MODIFIED — document 4 new env vars
```

**Structure Decision**: Single project (Option 1). All changes are within the existing `ai-hub/app/` module. No new top-level directories.

---

## Phase 0: Research

All NEEDS CLARIFICATION items resolved. See [research.md](research.md) for full findings.

| Unknown | Resolution |
|---------|------------|
| LRU variant selection approach | In-memory `OrderedDict` + write-through to new `response_pool_usage` SQLite table |
| Deferred/cancellable TTS | `threading.Timer` + `threading.Event` cancel flag; fits existing 14 `threading.Thread` dispatch pattern |
| Dynamic system prompt injection | Static base prompt + computed `[Session]` suffix appended at `ask_codex` call time |
| Minimal mode detection | Two-signal regex pre-flight in `main.py` (consistent with `_is_training_start_command` pattern) |
| Swedish phrase content | Pre-authored sv-SE phrase pools tuned for Microsoft Sofie Neural prosody |

---

## Phase 1: Design

### 1.1 New Module: `ai-hub/app/response_pool.py`

Central module for all phrase pool logic. Responsibilities:
- Define all phrase pools as typed data structures with `pool_name`, `variant_key`, `text` (with optional `{name}` placeholder), and optional context metadata (`time_of_day`, `recency`, `companion_mode`).
- Implement `pick(pool_name, context)` — filters eligible variants by context, selects least-recently-used, updates in-memory LRU and writes through to SQLite.
- Implement `load_lru_from_db()` — called at startup to seed in-memory state from `response_pool_usage`.
- Thread-safe via a single `threading.Lock` wrapping all `_pool_lru` mutations.
- Fallback: if all variants have been recently used, select least-recently-used ignoring recency filter (prevents deadlock on small pools).

**Pool selector context object**:
```python
@dataclass
class PoolContext:
    time_of_day: str          # "morning" | "afternoon" | "evening" | "night"
    recency: bool             # True if last interaction < 10 min ago
    identity_name: str | None
    companion_mode: bool      # False = minimal/direct mode active
    last_action: str | None   # e.g. "training_stop", "spotify_play"
```

**Phrase pools to define** (minimum variant counts per spec FR-001, FR-003):

| Pool Name | Variants | Context Filter |
|-----------|----------|----------------|
| `wake_morning` | 5+ | `time_of_day=morning` |
| `wake_afternoon` | 5+ | `time_of_day=afternoon` |
| `wake_evening` | 5+ | `time_of_day=evening` |
| `wake_continuity` | 5 | `recency=True` (any time) |
| `spotify_play` | 3+ | — |
| `spotify_pause` | 3+ | — |
| `spotify_next` | 3+ | — |
| `spotify_prev` | 3+ | — |
| `follow_start` | 3+ | — |
| `follow_stop` | 3+ | — |
| `training_start_named` | 3+ | `identity_name` required |
| `training_stop` | 3+ | — |
| `workout_followup` | 6+ | `companion_mode=True` only |
| `processing_ack` | 5+ | — |
| `error_generic` | 3+ | — |

### 1.2 DB Changes: `ai-hub/app/db.py`

New functions added to `db.py`:

**Schema addition** (in `init_db()` `executescript`):
```sql
CREATE TABLE IF NOT EXISTS response_pool_usage (
    pool_name   TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    used_at     TEXT NOT NULL,
    PRIMARY KEY (pool_name, variant_key)
);
```

**New helper functions**:
- `load_pool_usage() -> list[dict]` — `SELECT pool_name, variant_key, used_at ORDER BY used_at ASC` for LRU seeding on startup.
- `upsert_pool_usage(pool_name: str, variant_key: str) -> None` — `INSERT OR REPLACE` with current timestamp.
- `get_companion_pref(person_id: int) -> str` — reads `mode_state` key `companion_pref_{person_id}`; returns `"full"` if absent.
- `set_companion_pref(person_id: int, pref: str) -> None` — upserts `companion_pref_{person_id}` in `mode_state`.
- `get_last_interaction_at(person_id: int | None) -> datetime | None` — queries `conversation_turns` joined with `conversation_identity` to find the most recent turn for this identity; returns UTC datetime or None.

### 1.3 Changes: `ai-hub/app/codex_client.py`

**Expand base `SYSTEM_PROMPT`**: Append a `Personlighet:` section after the existing rules block:

```
Personlighet:
- Du är varm, nyfiken och engagerad — inte bara ett verktyg.
- Om någon frågar hur du mår eller vad du tycker, svara kort och naturligt utan att avfärda frågan.
- Du kan ställa en följdfråga om användaren verkar vilja prata mer.
- Om en begäran är oklar, fråga snabbt vad de menar snarare än att gissa tyst.
- Undvik fraser som "Som en AI kan jag inte..." — svara alltid något naturligt.
```

**Add `build_system_prompt(session_ctx)`**: Constructs the dynamic `[Session]` suffix from `identity_name`, `time_of_day`, `recent_activity`, and `companion_mode` and appends it to the (potentially env-var-overridden) base prompt. Only non-empty fields contribute tokens.

**Update `ask_codex` signature**: Accept an optional `session_ctx: dict | None = None` parameter; pass `build_system_prompt(session_ctx)` as the `system_prompt` payload field when provided.

### 1.4 Changes: `ai-hub/app/main.py`

This is the largest change. Specific modifications:

**A. Follow-up remark scheduler** — Add module-level globals and two functions:
- `schedule_followup(text, delay_sec=1.5)` — cancels any pending timer, creates a new `threading.Timer`, sets it on `_pending_followup_timer`.
- `cancel_followup()` — sets `_followup_cancel` event, calls `timer.cancel()`.

**B. Cancel follow-up at top of each audio turn** — Add `cancel_followup()` as the first statement in the `/v1/events/audio/text` and `/v1/events/audio/wake` handlers.

**C. Minimal mode pre-flight** — Add before the `detect_camera_intent()` call (before line 1862):
1. Two compiled regex constants at module level: `_MINIMAL_MODE_ON`, `_MINIMAL_MODE_OFF`.
2. Two new env-var-backed constants: `MINIMAL_MODE_ON_ACK_TEXT`, `MINIMAL_MODE_OFF_ACK_TEXT`.
3. `_detect_minimal_mode_switch(text)` private function.
4. Pre-flight block: detect → resolve current identity → persist preference → speak confirmation → return early.

**D. Replace hardcoded wake ACK** — Replace `assistant_text = WAKE_ACK_TEXT` (line 1637) with:
```python
assistant_text = response_pool.pick(
    _wake_pool_name(interaction_context),   # "wake_continuity" or "wake_{time_of_day}"
    interaction_context,
)
```
`_wake_pool_name()` returns `"wake_continuity"` if last interaction was < 10 minutes ago, else `"wake_{time_of_day}"`.

**E. Replace hardcoded training responses** — Lines 1796, 1815, 1851–1853: replace with pool picks from `training_stop`, `training_start_named` pools with `{name}` substitution.

**F. Replace hardcoded Spotify confirmations** — Lines 1948–1962: replace with pool picks from `spotify_play`, `spotify_pause`, `spotify_next`, `spotify_prev` pools.

**G. Replace hardcoded follow start/stop** — Line 1889: replace `cam_result` override with a pool pick from `follow_start` / `follow_stop` pools.

**H. Replace hardcoded processing ACK** — `PROCESSING_ACK_TEXT` remains as the default env var fallback; pool selection is used when available.

**I. Add follow-up scheduling after training_stop** — After speaking the training stop confirmation (R7 path), call `schedule_followup(response_pool.pick("workout_followup", ctx))` when `companion_mode=True` and `random() < FOLLOWUP_PROBABILITY`.

**J. Inject session context into Codex calls** — At the `ask_codex()` call site (line 2158), build and pass `session_ctx` containing `identity_name`, `time_of_day`, `recent_activity`, `companion_mode`.

**K. Replace hardcoded identity-bind ACK** — Line 1725: replace `f"Tack {candidate_name}. Jag känner igen dig nu."` with a pool variant.

### 1.5 New Env Vars for `.env.example`

```bash
# Minimal mode verbal confirmations
AIHUB_MINIMAL_MODE_ON_ACK_TEXT=Okej, jag svarar kortare.
AIHUB_MINIMAL_MODE_OFF_ACK_TEXT=Okej, jag svarar som vanligt igen.

# Follow-up remark timing and probability
AIHUB_FOLLOWUP_DELAY_SEC=1.5
AIHUB_FOLLOWUP_PROBABILITY=0.30
```

---

## Contracts

This feature modifies internal behavior only. No new HTTP endpoints are added or removed. The existing `/v1/events/audio/wake` and `/v1/events/audio/text` endpoint response schemas are unchanged — `assistant_text` continues to be the field containing the spoken response. No external service contracts are affected.

---

## Implementation Sequence

Tasks should be implemented in this order to enable incremental testing at each step:

1. **DB layer** — Add `response_pool_usage` table + `load_pool_usage`, `upsert_pool_usage`, `get_companion_pref`, `set_companion_pref`, `get_last_interaction_at` to `db.py`. Run `init_db()` to verify schema migration.

2. **Response pool module** — Implement `response_pool.py` with all pool definitions, `PoolContext`, `pick()`, `load_lru_from_db()`. Verify LRU selection independently by unit-testing `pick()` with a mock DB.

3. **System prompt expansion** — Update `codex_client.py` with persona section and `build_system_prompt()`. Verify via direct curl to Codex-enabled endpoint.

4. **Wake ACK pool** — Replace hardcoded `WAKE_ACK_TEXT` in `main.py` with pool selection. Test SC-001 (10 triggers, no phrase repeats more than twice).

5. **Task confirmation pools** — Replace Spotify + training + follow start/stop hardcoded strings. Test SC-002 (5 same commands, 3+ distinct responses).

6. **Follow-up scheduler** — Add `schedule_followup` / `cancel_followup` + trigger after training_stop. Test SC-003 (10 sessions, 3+ follow-ups).

7. **Minimal mode pre-flight** — Add regex constants, `_detect_minimal_mode_switch()`, pre-flight block, DB persistence. Test FR-009 (activate → restart → verify → deactivate).

8. **Session context injection** — Wire `session_ctx` into `ask_codex` calls. Test SC-004 (social questions receive natural responses).

9. **`.env.example` update** — Document all 4 new env vars.

10. **Regression test** — Run SC-005 (camera control + Spotify search still work).
