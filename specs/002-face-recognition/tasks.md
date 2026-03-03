# Tasks: AI Companion — Identity, Memory & Embodiment

**Input**: Design documents from `/specs/002-face-recognition/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅ quickstart.md ✅

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)

---

## Phase 1: Setup (face-recognition service scaffold)

**Purpose**: Create the new `face-recognition` Docker service structure and update shared config.

- [X] T001 Create `face-recognition/` directory structure: `face-recognition/app/__init__.py`, `face-recognition/app/main.py` (skeleton), `face-recognition/app/recognizer.py` (skeleton), `face-recognition/app/enrollment.py` (skeleton)
- [X] T002 Create `face-recognition/requirements.txt` with: `insightface==0.7.3`, `onnxruntime-gpu`, `fastapi`, `uvicorn`, `numpy`, `opencv-python-headless`, `python-multipart`
- [X] T003 Create `face-recognition/Dockerfile` based on `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`, Python 3.11, pre-download `buffalo_l` models at build time, set `LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/lib/wsl/lib`
- [X] T004 Add `face-recognition` service to `docker-compose.yml` with `deploy.resources.reservations.devices` GPU config, `ai_net` network, named volume `insightface_models:/root/.insightface`, port 8082 internal only
- [X] T005 [P] Add `FACE_RECOGNITION_*` env vars to `.env.example`: `FACE_RECOGNITION_API_KEY`, port, model name
- [X] T006 [P] Add `AIHUB_*` arrival/presence env vars to `.env.example`: `AIHUB_FACE_RECOGNITION_URL`, `AIHUB_FACE_RECOGNITION_THRESHOLD`, `AIHUB_ARRIVAL_COOLDOWN_SEC`, `AIHUB_UNKNOWN_PERSON_COOLDOWN_SEC`, `AIHUB_HA_URL`, `AIHUB_HA_TOKEN`, `AIHUB_PTZ_GESTURES_ENABLED`, `AIHUB_MORNING_GREETING_TIME`, `AIHUB_PROACTIVE_ENABLED`, `AIHUB_MEMORY_EXTRACTION_ENABLED`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core InsightFace inference, DB tables, and ai-hub HTTP client — MUST be complete before any user story.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Implement `face-recognition/app/recognizer.py`: `FaceAnalysis` init with `buffalo_l` + `CUDAExecutionProvider`, log GPU/CPU provider at startup, `recognize(jpeg_bytes) -> dict` (matched, name, confidence, bbox, face_detected), `enroll(name, jpeg_bytes) -> dict` (ok, embedding stored, embedding_count), cosine threshold from env `FACE_RECOGNITION_THRESHOLD`
- [X] T008 Implement `face-recognition/app/enrollment.py`: in-memory `enrolled: dict[str, list[np.ndarray]]`, `load_from_disk(models_dir)` on startup, `save_embedding(name, normed_embedding)`, `delete_person(name)`, `get_count(name) -> int`, persist embeddings to JSON files in models volume
- [X] T009 Implement `face-recognition/app/main.py`: FastAPI with `POST /recognize` (multipart JPEG), `POST /enroll` (multipart name+JPEG), `DELETE /persons/{name}`, `GET /health` — all per contracts/face-recognition-service.md, `X-API-Key` auth header validation
- [X] T010 Add `person_presence` table to `ai-hub/app/db.py`: schema per data-model.md, `upsert_presence(person_name, last_seen_at)`, `set_greeted(person_name)`, `get_presence(person_name) -> dict`, `is_new_arrival(person_name, cooldown_sec) -> bool`
- [X] T011 [P] Add `last_unknown_face_at` key helpers to `ai-hub/app/db.py`: `get_last_unknown_face_at() -> datetime | None`, `set_last_unknown_face_at()`, using existing `mode_state` key-value table
- [X] T012 [P] Create `ai-hub/app/face_client.py`: async HTTP client (httpx) wrapping face-recognition service — `async_recognize(jpeg_bytes) -> dict`, `async_enroll(name, jpeg_bytes) -> dict`, `async_delete(name) -> dict`, reads `AIHUB_FACE_RECOGNITION_URL` + `FACE_RECOGNITION_API_KEY` from env, graceful fallback (log warning + return `{"matched": false}`) if service unavailable

**Checkpoint**: `docker compose up -d --build face-recognition` → `POST /enroll` with a photo → `POST /recognize` with same photo → `{"matched": true, "name": "..."}` returned ✅

---

## Phase 3: User Story 1 + User Story 5 — Välkommen hem & Enrollment (P1 🎯 MVP + P5)

**Goal**: Reolink detects person → ai-hub fetches snapshot → InsightFace identifies → greeting spoken + camera nods. Enrollment via voice command and API.

**Independent Test**: Enroll via `POST /v1/persons/Sebastian/enroll`. Walk in front of camera. HA fires webhook. Within 5s: TTS greeting with name. Re-enter within 30 min: no second greeting.

### Implementation

- [X] T013 [US5] Add `POST /v1/persons/{name}/enroll` endpoint to `ai-hub/app/main.py`: accepts multipart image or grabs current camera frame (snapshot from `AIHUB_HA_URL`), calls `face_client.async_enroll()`, calls `db.remember_identity()`, returns `{"ok": true, "name": ..., "message": "..."}`
- [X] T014 [US5] Add voice enrollment intent detection in `ai-hub/app/main.py`: regex pre-flight for `"det här är (\w+)"` pattern (similar to existing `_detect_minimal_mode_switch`), triggers enrollment flow with current camera snapshot, speaks Swedish confirmation via TTS
- [X] T015 [US1] Add `POST /v1/events/person_arrived` endpoint to `ai-hub/app/main.py` per contracts/aihub-new-endpoints.md: reads `event`, `camera_entity`, `snapshot_url`, `timestamp` from JSON body, requires `AIHUB_API_KEY` auth
- [X] T016 [US1] Implement snapshot fetch in `ai-hub/app/main.py`: `async _fetch_ha_snapshot(snapshot_url) -> bytes`, uses `httpx.AsyncClient` with `AIHUB_HA_TOKEN` Bearer header fallback, logs failure and returns empty bytes on error
- [X] T017 [US1] Implement arrival logic in `ai-hub/app/main.py`: `async _handle_person_arrived(snapshot_bytes)` — calls `face_client.async_recognize()`, calls `db.is_new_arrival()`, branches: known+new arrival / known+already home / unknown+cooldown elapsed / unknown+cooldown active
- [X] T018 [US1] Implement arrival greeting dispatch in `ai-hub/app/main.py`: build time-appropriate Swedish greeting string (morgon/eftermiddag/kväll), call `speak_to_camera()`, call `db.upsert_presence()` + `db.set_greeted()`, call `db.bind_identity_to_conversation()`, update `active_person_name` in mode_state
- [X] T019 [US1] Implement unknown-person handling in `ai-hub/app/main.py`: check `db.get_last_unknown_face_at()` vs `AIHUB_UNKNOWN_PERSON_COOLDOWN_SEC`, if elapsed speak `"Hej, jag känner inte igen dig — vem är du?"` + call `db.set_last_unknown_face_at()`, else stay silent
- [X] T020 [US1] Add `GET /v1/persons` endpoint to `ai-hub/app/main.py`: calls `db.list_athlete_names()`, enriches with `db.get_presence()` per person, returns list per contracts/aihub-new-endpoints.md
- [X] T021 [US1] Document HA automation + rest_command setup: update `specs/002-face-recognition/quickstart.md` with exact `binary_sensor.reolink_e1pro_person` entity name, camera.record automation YAML, and test steps

**Checkpoint**: Fully functional arrival greeting with known + unknown person handling. Enrollment via voice "Det här är Emma" and API. HA automation fires on person detection. ✅

---

## Phase 4: User Story 2 — Kamerans kroppsspråk / PTZ-gester (P2)

**Goal**: Camera nods on yes, shakes head on no, looks down when thinking, turns toward speaker on wake word.

**Independent Test**: Ask "är klockan 10?" (say a wrong time). AI corrects → camera shakes head. Ask "är du redo?" → AI confirms → camera nods.

### Implementation

- [X] T022 [US2] Add `nod(speed, duration_sec)` method to `ai-hub/app/reolink_client.py`: `ptz_burst("Up", speed, duration)` then `ptz_burst("Down", speed, duration)`, reads `AIHUB_PTZ_NOD_SPEED` from env, runs in thread (non-blocking), catches all exceptions → log warning only
- [X] T023 [P] [US2] Add `shake_head(speed, duration_sec)` method to `ai-hub/app/reolink_client.py`: `ptz_burst("Left", speed, duration)` then `ptz_burst("Right", speed, duration)`, reads `AIHUB_PTZ_SHAKE_SPEED` from env
- [X] T024 [P] [US2] Add `thinking(speed, duration_sec)` method to `ai-hub/app/reolink_client.py`: `ptz_burst("Down", speed=6, 0.4)` — subtle downward tilt
- [X] T025 [P] [US2] Add `home_pos()` method to `ai-hub/app/reolink_client.py`: calls `ptz_preset(preset_id=0)`, safe fallback if PTZ not configured
- [X] T026 [US2] Add Swedish response-type detector in `ai-hub/app/main.py`: `_detect_response_type(text) -> Literal["yes", "no", "neutral"]`, scan for affirmative keywords (ja, absolut, självklart, visst, precis, stämmer, givetvis) and negative keywords (nej, inte, tyvärr, dessvärre, fel), return "neutral" if none found
- [X] T027 [US2] Dispatch PTZ gesture alongside TTS in `ai-hub/app/main.py`: after Codex response received and before/during TTS, call `_detect_response_type()`, fire appropriate gesture in `threading.Thread(daemon=True)` — guard with `AIHUB_PTZ_GESTURES_ENABLED` env flag
- [X] T028 [US2] Add thinking pose on processing gap in `ai-hub/app/main.py`: call `reolink_client.thinking()` in daemon thread immediately after STT text received (before Codex call), cancel/return to home after response ready
- [X] T029 [US2] Add wake-word camera turn in `ai-hub/app/main.py`: on wake word event, call `reolink_client.home_pos()` first (standardize start position), then if `active_person_name` is set look toward camera center — guard with `AIHUB_PTZ_GESTURES_ENABLED`

**Checkpoint**: Full PTZ gesture suite working. Camera physically reacts to conversation content. ✅

---

## Phase 5: User Story 3 — AI:n minns vad du berättar (P3)

**Goal**: Facts from conversations are extracted and stored. AI references them naturally in future conversations without being reminded.

**Independent Test**: Have a conversation saying "Jag är trött idag, sov bara 4 timmar". Close session. Next conversation: AI references poor sleep unprompted.

### Implementation

- [X] T030 [US3] Add `memory_facts` table to `ai-hub/app/db.py`: schema per data-model.md, `insert_fact(person_name, fact_text, category, source_conv_id, follow_up_date=None)`, `get_facts_for_person(person_name, limit=10, active_only=True) -> list[dict]`, `mark_followed_up(fact_id)`, `deactivate_fact(fact_id)`
- [X] T031 [US3] Create `ai-hub/app/memory_manager.py`: `async extract_and_store_facts(conversation_id, person_name)` — fetches last N turns from `db.get_memory_context()`, builds Codex extraction prompt asking for JSON array `[{fact, category, follow_up_date?}]`, calls codex via `codex_client`, parses JSON response, calls `db.insert_fact()` for each, runs in background thread (non-blocking)
- [X] T032 [US3] Wire memory extraction at conversation close in `ai-hub/app/main.py`: detect conversation end (session TTL expiry or explicit close), call `memory_manager.extract_and_store_facts()` in daemon thread, guard with `AIHUB_MEMORY_EXTRACTION_ENABLED`
- [X] T033 [US3] Extend `_build_session_context_block()` in `ai-hub/app/codex_client.py`: if `session_ctx` contains `person_name`, call `db.get_facts_for_person(person_name, limit=10)`, format as Swedish bullet list, inject into system prompt context block under "Vad jag vet om [name]:"
- [X] T034 [US3] Add `person_name` to session context propagation in `ai-hub/app/main.py`: when `active_person_name` is set in mode_state, include in `session_ctx` dict passed to `ask_codex()`

**Checkpoint**: Two-session memory test passes. Facts visible in `GET /v1/persons` response (add `facts` field). ✅

---

## Phase 6: User Story 4 — Proaktiv kompis (P4)

**Goal**: AI initiates conversation without wake word — morning greeting, word of day, memory follow-ups.

**Independent Test**: Set `AIHUB_MORNING_GREETING_TIME` to 2 minutes from now with `active_person_name` set. AI speaks unprompted greeting + word of day. No second attempt if no response within 15s.

### Implementation

- [X] T035 [US4] Add daily morning greeting scheduler in `ai-hub/app/main.py`: on startup, schedule `threading.Timer` for `AIHUB_MORNING_GREETING_TIME`, on fire check `active_person_name` in mode_state and privacy_mode, if person home + not in privacy: dispatch morning greeting + word of day via `speak_to_camera()`, reschedule for next day, guard with `AIHUB_PROACTIVE_ENABLED`
- [X] T036 [US4] Add word-of-day generator in `ai-hub/app/main.py`: `_get_word_of_day() -> str`, calls Codex with prompt "Ge mig ett intressant svenskt eller engelskt ord med kort förklaring på svenska, max 20 ord", returns formatted string, falls back to static list of 30 words if Codex fails
- [X] T037 [US4] Wire `follow_up_date` from `memory_facts` to proactive trigger in `ai-hub/app/memory_manager.py`: after storing facts, check for any with `follow_up_date` set, schedule `threading.Timer` for that datetime, on fire call `speak_to_camera()` with follow-up question referencing the fact, mark `followed_up_at` in DB
- [X] T038 [US4] Add 15-second no-response timeout for proactive initiations in `ai-hub/app/main.py`: after proactive TTS fires, set a flag `_proactive_waiting_response = True` with timestamp, if no wake word / audio_turn within 15s, clear flag silently (no retry)
- [X] T039 [US4] Add `AIHUB_PROACTIVE_ENABLED` and `AIHUB_MORNING_GREETING_TIME` env var reads + validation at startup in `ai-hub/app/main.py`

**Checkpoint**: Morning greeting fires at scheduled time. Memory follow-up fires on correct date. 15s timeout works. ✅

---

## Phase 7: Frigate Migration (Infrastructure)

**Purpose**: Replace Frigate with standalone go2rtc + HA recording. Reduces CPU load, simplifies stack.

- [X] T040 Add standalone `go2rtc` service to `docker-compose.yml` using `alexxit/go2rtc` image, mount `./data/go2rtc/config.yaml`, port 8554 (RTSP) and 1984 (API) internal
- [X] T041 Create `data/go2rtc/config.yaml.example` with same streams as Frigate's go2rtc config: `reolink_e1pro_main` and `reolink_e1pro_sub` RTSP sources
- [X] T042 Update `camera-listener` service in `docker-compose.yml`: change `CAMERA_LISTENER_RTSP_URL` default from `rtsp://frigate:8554/...` to `rtsp://go2rtc:8554/reolink_e1pro_main`
- [X] T043 Update `AIHUB_GO2RTC_BASE_URL` default in `docker-compose.yml` from `http://frigate:1984` to `http://go2rtc:1984`
- [X] T044 Add `camera.record` + `camera.snapshot` to HA automation in `specs/002-face-recognition/quickstart.md`: `allowlist_external_dirs` config, automation YAML with lookback recording, web-accessible path
- [X] T045 Remove `frigate` service from `docker-compose.yml`
- [X] T046 Update `.specify/memory/constitution.md` Technology Constraints: replace "NVR: Frigate" with "NVR: go2rtc (standalone) + HA camera.record for event clips" — PATCH-level amendment, bump version 1.0.0 → 1.0.1, update Sync Impact Report comment

**Checkpoint**: Full stack runs without Frigate. Live stream works in HA. Recording saves to HA media. camera-listener detects wake word via go2rtc RTSP. ✅

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T047 [P] Validate all 16 new env vars are documented in `.env.example` with safe defaults or placeholder comments
- [X] T048 [P] Add `AIHUB_PTZ_NOD_SPEED`, `AIHUB_PTZ_SHAKE_SPEED`, `AIHUB_PTZ_NOD_DURATION_SEC`, `AIHUB_PTZ_SHAKE_DURATION_SEC` env vars to `.env.example` and read in `reolink_client.py`
- [X] T049 Update `CLAUDE.md` Active Technologies to include: InsightFace 0.7.3, onnxruntime-gpu, httpx — and add face-recognition service to Project Structure
- [X] T050 Add `active_person_name` propagation to conversation address: verify `codex_client.py` correctly uses `person_name` from session_ctx to address user by name in at least one reply per US5 acceptance scenario
- [ ] T051 Run `specs/002-face-recognition/quickstart.md` end-to-end validation: enroll, trigger arrival, test gestures, verify memory, verify proactive trigger
- [ ] T052 Commit all changes with message `feat(002): ai companion identity memory and embodiment`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 ⚠️ BLOCKS all user stories
- **US1+US5 (Phase 3)**: Depends on Phase 2
- **US2 (Phase 4)**: Depends on Phase 2 only — can run in parallel with Phase 3
- **US3 (Phase 5)**: Depends on Phase 2 + Phase 3 (needs `active_person_name` from arrival flow)
- **US4 (Phase 6)**: Depends on Phase 5 (memory facts needed for follow-ups)
- **Frigate Migration (Phase 7)**: Independent — can run any time after Phase 1
- **Polish (Phase 8)**: After all desired phases complete

### User Story Dependencies

- **US1+US5 (Phase 3)**: No story dependencies — first deliverable after foundational
- **US2 (Phase 4)**: No story dependencies — can parallel with US1
- **US3 (Phase 5)**: Soft dependency on US1 (needs `active_person_name` in session context)
- **US4 (Phase 6)**: Depends on US3 (`memory_facts.follow_up_date`)

### Parallel Opportunities

- T005 + T006 parallel (both `.env.example` additions, different sections)
- T010 + T011 + T012 parallel (different files in ai-hub/app/)
- T022 + T023 + T024 + T025 parallel (all PTZ methods, independent functions in reolink_client.py)
- Phase 4 (US2) can start in parallel with Phase 3 (US1+US5) after Phase 2 completes

---

## Parallel Example: US1 Arrival Flow (Phase 3)

```text
After Phase 2 checkpoint:

Group A (run together):
  T013 — POST /v1/persons/{name}/enroll endpoint
  T015 — POST /v1/events/person_arrived endpoint skeleton

Group B (after T015):
  T016 — snapshot fetch helper
  T017 — arrival logic (recognize + presence check)

Group C (after T017):
  T018 — greeting dispatch
  T019 — unknown person handling

Sequential finish:
  T020 — GET /v1/persons
  T021 — HA automation docs
```

---

## Implementation Strategy

### MVP: User Story 1 only (Phases 1–3)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational — build face-recognition service, verify CUDA ✅
3. Complete Phase 3: US1+US5 — enroll, arrive, get greeted ✅
4. **STOP and VALIDATE**: Walk in front of camera → greeted by name within 5 seconds
5. Demo: The AI knows who you are

### Incremental Delivery

1. Phase 1–3 → "The AI knows who I am and says hello" (MVP)
2. Phase 4 → "The camera has body language" (+PTZ gestures)
3. Phase 5 → "The AI remembers what I tell it" (+Memory)
4. Phase 6 → "The AI talks to me without me asking" (+Proactive)
5. Phase 7 → "Frigate removed, simpler stack" (+Infra cleanup)

---

## Notes

- All PTZ gesture tasks [T022–T025] marked [P] — independent functions in same file, no shared state
- Memory extraction (T031–T034) is async/background — never blocks conversation loop
- Frigate migration (Phase 7) is fully independent — safe to defer or do first
- Total: **52 tasks** across 8 phases
- Suggested MVP stop: after T021 (end of Phase 3) — fully working arrival greeting
