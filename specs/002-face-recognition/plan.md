# Implementation Plan: AI Companion — Identity, Memory & Embodiment

**Branch**: `002-face-recognition` | **Date**: 2026-03-03 | **Spec**: [spec.md](spec.md)

## Summary

Build an always-present AI companion that identifies household members via local ML face recognition (InsightFace buffalo_l on RTX 4070), greets them on arrival, expresses itself through PTZ camera gestures, and builds a persistent memory of conversations to enable proactive follow-ups. Replaces the existing pixel-hash embedding approach. Adds a new `face-recognition` Docker service. Extends ai-hub with arrival flow, memory layer, and PTZ gesture dispatch. HA Reolink integration replaces Frigate for person-detection triggers.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: insightface 0.7.3, onnxruntime-gpu, FastAPI (existing), httpx (HA snapshot fetch), numpy
**Storage**: SQLite aihub.db — 2 new tables (`person_presence`, `memory_facts`); named Docker volume for InsightFace models
**Testing**: pytest
**Target Platform**: Docker Desktop / WSL2, NVIDIA RTX 4070 (CUDA 12.4), Ubuntu 22.04 base
**Project Type**: New Docker service + extensions to existing ai-hub service
**Performance Goals**: End-to-end arrival greeting < 5s; face recognition inference < 500ms; memory injection < 50ms
**Constraints**: No video/images leave LAN; GPU required for face-recognition service; all new config via env vars
**Scale/Scope**: 1–6 enrolled household members; single camera; single-occupant context at a time

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Privacy-by-Default | ✅ PASS | InsightFace runs locally on RTX 4070. Snapshot fetch is LAN-only. Only text (name, greeting) sent to Codex. No video or images leave the network. |
| II. Container-First | ✅ PASS | New `face-recognition` service is single-purpose. ai-hub extended via HTTP calls to it. HA communicates over `ai_net`. |
| III. Config-as-Environment | ✅ PASS | All new parameters (threshold, cooldowns, HA token, API keys) via env vars. `.env.example` updated. |
| IV. Graceful Degradation | ✅ PASS | face-recognition unavailable → ai-hub logs warning, skips recognition, continues voice-only. PTZ failures logged, not raised. Memory extraction failure → silent, no impact on conversation. |
| V. Minimal External Surface | ✅ PASS | No new cloud calls. HA is LAN-local. One new internal HTTP service. |

**Violation requiring justification**:

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New Docker service (`face-recognition`) | InsightFace is GPU-heavy; isolates model memory from ai-hub; single-purpose per Constitution II | Running InsightFace inside ai-hub would mix responsibilities and risk GPU memory contention with Ollama |
| Frigate removal (constitution amendment) | Frigate CPU detection replaced by HA Reolink integration (camera-native AI); reduces host CPU load | Keeping Frigate adds 2–4 CPU cores of load for redundant detection already done by camera firmware |

*Constitution amendment required*: Technology Constraints section lists Frigate as NVR. Must update to reflect standalone go2rtc + HA recording. PATCH-level amendment.

## Project Structure

### Documentation (this feature)

```text
specs/002-face-recognition/
├── plan.md              ← this file
├── research.md          ← Phase 0 decisions
├── data-model.md        ← new tables + entity relationships
├── quickstart.md        ← setup and test guide
├── contracts/
│   ├── face-recognition-service.md   ← new service API
│   └── aihub-new-endpoints.md        ← extended ai-hub endpoints + HA automation
└── tasks.md             ← Phase 2 output (/speckit.tasks)
```

### Source Code

```text
face-recognition/               ← NEW service
├── app/
│   ├── main.py                 ← FastAPI app, /recognize /enroll /health endpoints
│   ├── recognizer.py           ← InsightFace FaceAnalysis wrapper, cosine matching
│   └── enrollment.py           ← per-person embedding store (memory + persist via ai-hub)
├── Dockerfile
└── requirements.txt

ai-hub/
├── app/
│   ├── main.py                 ← extended: /v1/events/person_arrived, /v1/persons/*
│   │                              arrival flow, PTZ gesture dispatch, voice enrollment handler
│   ├── db.py                   ← extended: person_presence, memory_facts tables + CRUD
│   ├── codex_client.py         ← extended: memory facts injected into session context
│   ├── reolink_client.py       ← extended: nod(), shake_head(), thinking(), home_pos()
│   ├── face_client.py          ← NEW: HTTP client for face-recognition service
│   └── memory_manager.py       ← NEW: post-conversation fact extraction + follow-up scheduling
└── Dockerfile                  ← no change (no new system deps in ai-hub)

docker-compose.yml              ← add face-recognition service + GPU config
                                   phase 2: replace frigate with standalone go2rtc
.env.example                    ← 10 new AIHUB_* and FACE_RECOGNITION_* vars
```

**Structure Decision**: Single-project extension. New `face-recognition/` directory at repo root alongside existing service directories. ai-hub gets 2 new modules and extensions to 4 existing files.

---

## Phase 0: Research ✅

All decisions resolved in [research.md](research.md). No NEEDS CLARIFICATION markers remain.

Key decisions:
- **InsightFace buffalo_l** — 512-D ArcFace, cosine threshold 0.55, CUDA via onnxruntime-gpu
- **Separate face-recognition container** — `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`
- **HA Reolink integration** — local, no cloud, `binary_sensor.reolink_e1pro_person` → `on`
- **HA rest_command webhook** → `POST /v1/events/person_arrived` in ai-hub
- **HA camera.record** — replaces Frigate recording, saves MP4 to `/config/www/`
- **PTZ gestures** — extend `ptz_burst()` with nod/shake/thinking methods
- **Memory extraction** — async Codex call post-conversation → `memory_facts` table

---

## Phase 1: Design & Contracts ✅

### Data Model

See [data-model.md](data-model.md).

New tables:
- `person_presence` — arrival cooldown, last_seen_at, greeted_at per person
- `memory_facts` — extracted conversation facts with optional follow_up_date

Existing tables used unchanged: `athletes`, `face_embeddings`, `conversation_identity`.

InsightFace embeddings stored with `source = "insightface_buffalo_l"` — coexists with old pixel-hash embeddings, no migration needed.

### Contracts

See [contracts/](contracts/).

- **face-recognition service**: `POST /recognize`, `POST /enroll`, `DELETE /persons/{name}`, `GET /health`
- **ai-hub extensions**: `POST /v1/events/person_arrived`, `POST /v1/persons/{name}/enroll`, `GET /v1/persons`
- **HA automation**: `rest_command.notify_person_arrived` + automation on `binary_sensor.reolink_e1pro_person`

### Implementation Phases

**Phase A — face-recognition service** (standalone, testable independently)
1. Create `face-recognition/` directory with Dockerfile, requirements.txt
2. Implement `recognizer.py`: FaceAnalysis init, `recognize(jpeg_bytes)`, `enroll(name, jpeg_bytes)`
3. Implement `main.py`: FastAPI with `/recognize`, `/enroll`, `/health` endpoints
4. Add to `docker-compose.yml` with GPU config
5. Add `FACE_RECOGNITION_*` env vars to `.env.example`
6. Test: `POST /enroll` with photo → `POST /recognize` with same photo → name returned

**Phase B — ai-hub arrival flow**
1. Add `face_client.py`: thin HTTP client wrapping face-recognition service
2. Add `person_presence` table + CRUD to `db.py`
3. Add `POST /v1/events/person_arrived` endpoint to `main.py`
4. Implement arrival logic: fetch snapshot → recognize → check cooldown → greet or silent update
5. Add `POST /v1/persons/{name}/enroll` + voice enrollment intent handler
6. Add 10 new env vars to `.env.example`
7. Test: trigger endpoint manually → confirm greeting TTS fires

**Phase C — PTZ gestures**
1. Add `nod()`, `shake_head()`, `thinking()`, `home_pos()` to `reolink_client.py`
2. Add response-type detection in `main.py` (Swedish keyword scan before TTS dispatch)
3. Dispatch gesture in daemon thread alongside TTS
4. Add `AIHUB_PTZ_GESTURES_ENABLED` guard + speed env vars
5. Test: ask yes/no questions → confirm camera moves

**Phase D — memory layer**
1. Add `memory_facts` table + CRUD to `db.py` (`insert_fact`, `get_facts_for_person`, `mark_followed_up`)
2. Add `memory_manager.py`: async post-conversation extraction via Codex + follow-up scheduler
3. Extend `codex_client.py` `_build_session_context_block()` to inject top-10 facts
4. Wire memory extraction call at conversation close in `main.py`
5. Test: have a conversation mentioning a plan → next conversation AI references it

**Phase E — proactive triggers**
1. Extend `schedule_followup` pattern with daily morning greeting scheduler
2. Add word-of-day picker (Codex-generated or static list)
3. Wire `follow_up_date` from memory_facts to trigger proactive conversation
4. Add `AIHUB_PROACTIVE_ENABLED` guard
5. Test: set `AIHUB_MORNING_GREETING_TIME` to 2 minutes from now → confirm unprompted greeting

**Phase F — Frigate migration** (separate, after all above stable)
1. Add standalone `go2rtc` service to `docker-compose.yml` (`alexxit/go2rtc`)
2. Move go2rtc config from Frigate to standalone service
3. Update `camera-listener` RTSP URL
4. Update `AIHUB_GO2RTC_BASE_URL`
5. Configure HA `camera.record` + `camera.snapshot` automation
6. Remove `frigate` service from docker-compose
7. Update constitution Technology Constraints (PATCH amendment)
8. Test: full stack without Frigate — live stream, recording, recognition all working
