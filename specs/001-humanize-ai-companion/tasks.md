# Tasks: Humanize AI Companion Personality

**Input**: Design documents from `/specs/001-humanize-ai-companion/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: Not requested — acceptance validated manually via `curl` per `quickstart.md`.

**Organization**: Tasks are grouped by user story. Each phase is independently deliverable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different functions/sections, no mutual dependency)
- **[Story]**: Which user story this task belongs to (US1–US4)

## Path Conventions

All source changes are within `ai-hub/app/` (existing single-service structure).

---

## Phase 1: Setup — DB Layer

**Purpose**: Extend the existing SQLite schema and add helper functions that all subsequent phases depend on. All changes are in `ai-hub/app/db.py`.

**⚠️ CRITICAL**: Phases 2–7 cannot begin until this phase is complete.

- [x] T001 Add `response_pool_usage` table definition to the `executescript` block in `init_db()` in `ai-hub/app/db.py` — schema: `(pool_name TEXT, variant_key TEXT, used_at TEXT, PRIMARY KEY (pool_name, variant_key))`
- [x] T00 [P] Add `load_pool_usage() -> list[dict]` to `ai-hub/app/db.py` — `SELECT pool_name, variant_key, used_at FROM response_pool_usage ORDER BY used_at ASC` for LRU seeding at startup
- [x] T00 [P] Add `upsert_pool_usage(pool_name: str, variant_key: str) -> None` to `ai-hub/app/db.py` — `INSERT OR REPLACE INTO response_pool_usage` with `now_iso()` timestamp
- [x] T00 [P] Add `get_companion_pref(person_id: int) -> str` and `set_companion_pref(person_id: int, pref: str) -> None` to `ai-hub/app/db.py` — read/write `mode_state` key `companion_pref_{person_id}`; return `"full"` if key absent
- [x] T00 [P] Add `get_last_interaction_at(person_id: int | None) -> datetime | None` to `ai-hub/app/db.py` — join `conversation_turns` with `conversation_identity` to find most recent turn timestamp for the given person; return UTC `datetime` or `None`

**Checkpoint**: All DB helpers available — run `docker compose exec ai-hub python3 -c "from app import db; db.init_db(); print('ok')"` to verify schema migration applies cleanly.

---

## Phase 2: Foundational — Response Pool Module

**Purpose**: Create `ai-hub/app/response_pool.py` as the central phrase-pool selector. All user story phases that replace hardcoded strings depend on this module.

**⚠️ CRITICAL**: Phases 3–6 cannot begin until this phase is complete.

- [x] T00 Create `ai-hub/app/response_pool.py` with the `PoolContext` dataclass (`time_of_day: str`, `recency: bool`, `identity_name: str | None`, `companion_mode: bool`, `last_action: str | None`) and module-level `_pool_lru: dict[str, OrderedDict[str, float]]` + `_pool_lock: threading.Lock`
- [x] T00 Add all 16 phrase pool definitions to `ai-hub/app/response_pool.py` as module-level dicts: `wake_morning`, `wake_afternoon`, `wake_evening`, `wake_continuity`, `spotify_play`, `spotify_pause`, `spotify_next`, `spotify_prev`, `follow_start`, `follow_stop`, `training_start_named`, `training_stop`, `workout_followup`, `processing_ack`, `error_generic`, `identity_bind` — each entry is a list of `{"key": str, "text": str}` dicts using sv-SE phrases from `research.md` (including `{name}` placeholder where applicable)
- [x] T00 Implement `pick(pool_name: str, ctx: PoolContext) -> str` in `ai-hub/app/response_pool.py` — filter eligible variants by context (companion_mode gate on `workout_followup`), select least-recently-used variant from `_pool_lru`, format `{name}` placeholder if `ctx.identity_name`, update `_pool_lru` and call `db.upsert_pool_usage()`; fall back to least-recently-used if all variants recently used
- [x] T00 Implement `load_lru_from_db()` in `ai-hub/app/response_pool.py` — call `db.load_pool_usage()` and seed `_pool_lru` `OrderedDict` entries in ascending `used_at` order; call this function from the `@app.on_event("startup")` handler in `ai-hub/app/main.py`
- [x] T0 [P] Add `_get_time_of_day() -> str` helper to `ai-hub/app/main.py` — returns `"morning"` (06–11), `"afternoon"` (11–18), `"evening"` (18–23), `"night"` (23–06) based on `datetime.now()` local hour
- [x] T0 [P] Add `_build_pool_context(conversation_id: str) -> PoolContext` helper to `ai-hub/app/main.py` — resolves current `person_id` from `db` `conversation_identity`, fetches `companion_pref`, checks `last_interaction_at` for recency (`< 10 min`), populates and returns a `PoolContext`

**Checkpoint**: Import `response_pool` in a REPL and call `response_pool.pick("wake_morning", ctx)` with a test `PoolContext` — verify it returns a non-empty Swedish string and rotates on repeated calls.

---

## Phase 3: User Story 1 — Natural, Varied Greetings (Priority: P1) 🎯 MVP

**Goal**: Wake acknowledgements vary by time of day, identity, and recency. No two consecutive triggers produce the same greeting.

**Independent Test**: Trigger wake word 10 times (SC-001 in `quickstart.md`) — no phrase repeats more than twice.

- [x] T0 [US1] Add `_build_wake_response(pool_ctx: PoolContext) -> str` to `ai-hub/app/main.py` — returns `response_pool.pick("wake_continuity", pool_ctx)` when `pool_ctx.recency` is True, otherwise `response_pool.pick(f"wake_{pool_ctx.time_of_day}", pool_ctx)`
- [x] T0 [US1] Replace `assistant_text = WAKE_ACK_TEXT` (main.py line 1637) with `pool_ctx = _build_pool_context(req.conversation_id)` and `assistant_text = _build_wake_response(pool_ctx)` in `ai-hub/app/main.py`

**Checkpoint**: User Story 1 complete — 10 consecutive wake triggers produce varied greetings.

---

## Phase 4: User Story 2 — Warm, Varied Task Confirmations (Priority: P2)

**Goal**: All hardcoded task-confirmation strings replaced by LRU phrase pools. Same command issued 5 times produces at least 3 distinct confirmations.

**Independent Test**: Issue "pausa musik" 5 times (SC-002 in `quickstart.md`) — at least 3 distinct `assistant_text` responses.

- [x] T0 [P] [US2] Replace Spotify confirmation strings (main.py lines 1948–1957) with `response_pool.pick()` calls in `ai-hub/app/main.py` — `spotify_play` pool for play, `spotify_pause` pool for pause, `spotify_next` pool for next, `spotify_prev` pool for prev; preserve success/failure branching, substituting failure cases with `response_pool.pick("error_generic", pool_ctx)`
- [x] T0 [P] [US2] Replace camera follow start/stop text (main.py line 1889, `assistant_text = cam_result or "Automatisk följning avaktiverad."`) with `response_pool.pick("follow_start", pool_ctx)` or `response_pool.pick("follow_stop", pool_ctx)` based on `camera_intent` in `ai-hub/app/main.py`
- [x] T0 [P] [US2] Replace training stop confirmation (main.py line 1796, `"Okej, jag stoppar träningsläget nu."`) with `response_pool.pick("training_stop", pool_ctx)` in `ai-hub/app/main.py`
- [x] T0 [P] [US2] Replace training start with identity confirmation (main.py lines 1851–1853, `f"Okej {athlete_name}, träningsläget är igång. Jag börjar räkna reps nu."`) with `response_pool.pick("training_start_named", pool_ctx)` (pool_ctx must have `identity_name=athlete_name`) in `ai-hub/app/main.py`
- [x] T0 [P] [US2] Replace identity-bind confirmation (main.py line 1725, `f"Tack {candidate_name}. Jag känner igen dig nu."`) with `response_pool.pick("identity_bind", pool_ctx)` with `identity_name=candidate_name` in `ai-hub/app/main.py`
- [x] T0 [P] [US2] Replace `PROCESSING_ACK_TEXT` singleton (main.py line 2150, used in `speak_to_camera(PROCESSING_ACK_TEXT, ...)`) with `response_pool.pick("processing_ack", pool_ctx)` in `ai-hub/app/main.py`
- [x] T0 [US2] Replace Codex unavailable fallback string (main.py line 2178–2179, `"Codex är inte tillgänglig just nu."`) with `response_pool.pick("error_generic", pool_ctx)` + detail suffix in `ai-hub/app/main.py`

**Checkpoint**: User Story 2 complete — same command 5 times yields 3+ distinct confirmations (SC-002).

---

## Phase 5: User Story 3 — Conversational Follow-Through (Priority: P2)

**Goal**: After workout sessions end, the assistant occasionally (≥30% of sessions) offers a brief follow-up remark ~1.5 seconds after the confirmation, suppressed if the user speaks first.

**Independent Test**: End a training session 10 times — follow-up remark heard at least 3 times (SC-003). Cancel test: speak immediately after confirmation — follow-up is suppressed.

- [x] T0 [US3] Add follow-up scheduler module-level state to `ai-hub/app/main.py`: `FOLLOWUP_DELAY_SEC = float(os.getenv("AIHUB_FOLLOWUP_DELAY_SEC", "1.5"))`, `FOLLOWUP_PROBABILITY = float(os.getenv("AIHUB_FOLLOWUP_PROBABILITY", "0.30"))`, `_followup_cancel = threading.Event()`, `_followup_lock = threading.Lock()`, `_pending_followup_timer: threading.Timer | None = None`
- [x] T0 [US3] Implement `schedule_followup(text: str, source: str, delay_sec: float = FOLLOWUP_DELAY_SEC) -> None` in `ai-hub/app/main.py` — cancels any pending timer, clears `_followup_cancel`, creates a new `threading.Timer` whose callback checks `_followup_cancel.is_set()` before calling `speak_to_camera(text, source, event="reply")`; wraps callback in try/except logging
- [x] T0 [US3] Implement `cancel_followup() -> None` in `ai-hub/app/main.py` — sets `_followup_cancel` event and calls `_pending_followup_timer.cancel()` under `_followup_lock`
- [x] T0 [US3] Add `cancel_followup()` as the first statement in the `/v1/events/audio/text` request handler and the `/v1/events/audio/wake` request handler in `ai-hub/app/main.py`
- [x] T0 [US3] After the training stop early return (R7 path, after TTS dispatch, main.py ~line 1800), add: `if pool_ctx.companion_mode and random.random() < FOLLOWUP_PROBABILITY: schedule_followup(response_pool.pick("workout_followup", pool_ctx), req.source)` in `ai-hub/app/main.py`

**Checkpoint**: User Story 3 complete — follow-up appears in ≥3/10 sessions; barge-in cancels it (SC-003).

---

## Phase 6: User Story 4 — Richer Conversational Persona (Priority: P3)

**Goal**: Codex-powered responses are warmer and engage naturally with social questions. The system prompt includes explicit warmth, curiosity, and small-talk guidance. Session context (identity, time, mode) is injected per-call.

**Independent Test**: Ask "Hur mår du?" and "Vad tycker du om musik?" — both receive natural, warm Swedish responses with no AI disclaimer (SC-004).

- [x] T0 [US4] Append `Personlighet:` section to the default `SYSTEM_PROMPT` string in `ai-hub/app/codex_client.py` — add 5 guidance lines from `research.md §6` covering warmth, social questions, follow-up questions, ambiguity handling, and avoiding AI disclaimers
- [x] T0 [US4] Implement `_build_session_context_block(identity_name, time_of_day, recent_activity, companion_mode) -> str` in `ai-hub/app/codex_client.py` — returns a `"\n\n[Session]\n..."` suffix from only non-empty fields; cap `recent_activity` at 120 chars; return `""` if all fields empty/default
- [x] T0 [US4] Implement `build_system_prompt(session_ctx: dict | None) -> str` in `ai-hub/app/codex_client.py` — appends `_build_session_context_block(**session_ctx)` to the (possibly env-var-overridden) `SYSTEM_PROMPT`; returns `SYSTEM_PROMPT` unchanged if `session_ctx` is `None`
- [x] T0 [US4] Update `ask_codex()` signature in `ai-hub/app/codex_client.py` to accept `session_ctx: dict | None = None` and pass `build_system_prompt(session_ctx)` as the `"system_prompt"` payload field (replacing the current literal `SYSTEM_PROMPT`)
- [x] T0 [US4] Build and pass `session_ctx` dict at the `ask_codex()` call site (main.py ~line 2158) in `ai-hub/app/main.py` — populate with `identity_name` (from `pool_ctx`), `time_of_day` (from `_get_time_of_day()`), `recent_activity` (from last workout summary via `db` if available), `companion_mode` (from `pool_ctx`)

**Checkpoint**: User Story 4 complete — social questions answered naturally; Codex response reflects known identity name (SC-004).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Minimal mode (FR-009), environment configuration, and regression validation.

- [x] T0 Add compiled regex constants `_MINIMAL_MODE_ON` and `_MINIMAL_MODE_OFF` at module level in `ai-hub/app/main.py` — patterns from `research.md §4` using two-signal verb+adverb design
- [x] T0 Add env-var-backed string constants `MINIMAL_MODE_ON_ACK_TEXT = os.getenv("AIHUB_MINIMAL_MODE_ON_ACK_TEXT", "Okej, jag svarar kortare.")` and `MINIMAL_MODE_OFF_ACK_TEXT = os.getenv("AIHUB_MINIMAL_MODE_OFF_ACK_TEXT", "Okej, jag svarar som vanligt igen.")` to `ai-hub/app/main.py`
- [x] T0 Implement `_detect_minimal_mode_switch(text: str) -> str | None` in `ai-hub/app/main.py` — returns `"minimal_mode_on"`, `"minimal_mode_off"`, or `None` using the regex constants
- [x] T0 Add minimal mode pre-flight block in the `/v1/events/audio/text` handler before the `detect_camera_intent()` call (main.py ~line 1862) in `ai-hub/app/main.py` — resolve `person_id` from `db.get_conversation_identity(req.conversation_id)`, call `db.set_companion_pref(person_id, "minimal"|"full")`, speak confirmation via `speak_to_camera()` in daemon thread, log route, return early
- [x] T0 [P] Add 4 new env vars to `.env.example`: `AIHUB_MINIMAL_MODE_ON_ACK_TEXT`, `AIHUB_MINIMAL_MODE_OFF_ACK_TEXT`, `AIHUB_FOLLOWUP_DELAY_SEC`, `AIHUB_FOLLOWUP_PROBABILITY` — with current default values as comments
- [x] T0 Run regression acceptance tests per `specs/001-humanize-ai-companion/quickstart.md` SC-005 (camera control + Spotify actions still succeed), SC-001 (10 wake triggers vary), SC-002 (5 same commands → 3+ distinct responses)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (DB Layer)**: No dependencies — start immediately
- **Phase 2 (Response Pool)**: Requires Phase 1 complete — blocks all user story phases
- **Phase 3 (US1)**: Requires Phase 2 complete
- **Phase 4 (US2)**: Requires Phase 2 complete — can run in parallel with Phase 3
- **Phase 5 (US3)**: Requires Phase 2 complete — can run in parallel with Phases 3 and 4
- **Phase 6 (US4)**: Requires Phase 2 complete — fully independent of Phases 3, 4, 5
- **Phase 7 (Polish)**: Requires all user story phases complete

### User Story Dependencies

- **US1 (P1)**: Unblocked after Phase 2 — no dependency on US2, US3, US4
- **US2 (P2)**: Unblocked after Phase 2 — no dependency on US1, US3, US4
- **US3 (P2)**: Unblocked after Phase 2 — depends on US2's `training_stop` pool (T007 must include the pool); otherwise independent
- **US4 (P3)**: Fully independent — only touches `codex_client.py` and the Codex call site in `main.py`

### Within Each Phase

- All [P]-marked tasks within the same phase can be started in parallel
- Within US2 (Phase 4): T014–T019 are all in different sections of `main.py` and can be edited independently; T020 depends on T014–T019 being complete to avoid conflicting edits at adjacent lines

### Parallel Opportunities

```bash
# Phase 1 — all T002–T005 in parallel after T001:
Task: "Add load_pool_usage() in db.py"          # T002
Task: "Add upsert_pool_usage() in db.py"        # T002 (same task)
Task: "Add get/set_companion_pref() in db.py"   # T003
Task: "Add get_last_interaction_at() in db.py"  # T004

# Phase 2 — T010 and T011 in parallel with T007–T009:
Task: "Implement pick() in response_pool.py"    # T008
Task: "Add _get_time_of_day() in main.py"       # T010
Task: "Add _build_pool_context() in main.py"    # T011

# Phase 4 — T014–T019 all in parallel:
Task: "Replace Spotify strings in main.py"      # T014
Task: "Replace follow start/stop in main.py"    # T015
Task: "Replace training stop in main.py"        # T016
Task: "Replace training start in main.py"       # T017
Task: "Replace identity-bind in main.py"        # T018
Task: "Replace processing ACK in main.py"       # T019

# Phases 3, 4, 5, 6 — can start in parallel after Phase 2:
Task: "Phase 3 US1 wake greeting pool"
Task: "Phase 4 US2 task confirmations"
Task: "Phase 5 US3 follow-up scheduler"
Task: "Phase 6 US4 Codex persona"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (DB) → Phase 2 (Response Pool) — critical path
2. Complete Phase 3 (US1 wake greetings — 2 tasks)
3. **STOP and VALIDATE**: Trigger wake word 10 times, verify variety (SC-001)
4. Deploy as-is — already noticeably less robotic

### Incremental Delivery

1. **Phase 1 + 2** → Foundation ready
2. **Phase 3** → Varied wake greetings (MVP — US1) → test SC-001
3. **Phase 4** → Varied task confirmations (US2) → test SC-002
4. **Phase 5** → Workout follow-ups (US3) → test SC-003
5. **Phase 6** → Richer Codex persona (US4) → test SC-004
6. **Phase 7** → Minimal mode + regression → test SC-005 + FR-009

### Effort Summary

| Phase | Tasks | Scope |
|-------|-------|-------|
| Phase 1 (DB) | T001–T005 | 5 tasks |
| Phase 2 (Pool) | T006–T011 | 6 tasks |
| Phase 3 (US1) | T012–T013 | 2 tasks |
| Phase 4 (US2) | T014–T020 | 7 tasks |
| Phase 5 (US3) | T021–T025 | 5 tasks |
| Phase 6 (US4) | T026–T030 | 5 tasks |
| Phase 7 (Polish) | T031–T036 | 6 tasks |
| **Total** | **T001–T036** | **36 tasks** |

---

## Notes

- `[P]` = independent function/section, safe to implement in a separate edit session
- Each user story phase delivers a standalone testable increment
- No new Python packages required — `collections.OrderedDict` and `threading.Timer/Event` are stdlib
- Container rebuild required after any change: `docker compose up -d --build ai-hub`
- Verify `.env.example` stays in sync (Principle III) — T035 is the checkpoint
- All phrase content is in `research.md §5` — copy directly into T007's pool definitions
