# Research: AI Companion — Identity, Memory & Embodiment

**Branch**: `002-face-recognition` | **Date**: 2026-03-03

---

## Decision 1: Face Recognition Library

**Decision**: InsightFace `buffalo_l` model via `insightface==0.7.3` + `onnxruntime-gpu`

**Rationale**:
- `buffalo_l` is the best open-source accuracy pack (RetinaFace detection + ArcFace ResNet50 recognition)
- 512-D `normed_embedding` (pre-L2-normalized) — cosine similarity = simple dot product
- ~326 MB total model download, ~1–2 GB VRAM resident on RTX 4070 (ONNX arena allocation)
- Replaces the existing 128-D pixel-hash embedding in ai-hub — much better accuracy under lighting variation

**Alternatives considered**:
- Existing pixel-hash approach: rejected — not robust enough for varied lighting, too crude for multi-person household
- DeepFace: rejected — higher-level abstraction, harder to control embedding extraction
- face_recognition (dlib): rejected — CPU-only, no CUDA support, slower
- antelopev2: rejected — commercial license required

**Threshold**: `0.55` cosine similarity (dot product of normed embeddings). Community consensus for 2–5 person household with `buffalo_l`. Calibrate down to `0.50` if false-rejects are too frequent.

---

## Decision 2: face-recognition Docker Container

**Decision**: New standalone Docker service `face-recognition` using `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` base image

**Rationale**:
- Constitution Principle II: single-purpose containers
- InsightFace model initialization is heavy — isolates GPU memory from ai-hub
- Independently restartable if GPU crashes
- ai-hub calls it via HTTP (`POST /recognize`, `POST /enroll`)

**Key Dockerfile requirements**:
- Python 3.11 explicitly (Ubuntu 22.04 ships 3.10)
- `libgl1 libglib2.0-0` for OpenCV headless
- `pip install insightface onnxruntime-gpu opencv-python-headless numpy` — do NOT install both `onnxruntime` and `onnxruntime-gpu`
- Pre-download `buffalo_l` at image build time (avoid runtime internet dependency)
- Mount `insightface_models` named volume to persist model files across rebuilds
- `LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/lib/wsl/lib` in environment

**WSL2 / GPU gotchas**:
- Verify `CUDAExecutionProvider` is listed in `ort.get_available_providers()` at startup — log clearly if falling back to CPU
- Docker Desktop must have "Use NVIDIA GPU" enabled in Settings > Resources
- `deploy.resources.reservations.devices` required in docker-compose for GPU passthrough

---

## Decision 3: HA → ai-hub Trigger (Person Detection)

**Decision**: HA `rest_command` + automation → `POST http://aihub:8080/v1/events/person_arrived`

**Rationale**:
- HA Reolink integration is fully local (no cloud), communicates with camera via LAN HTTP API
- Fires `binary_sensor.<camera_slug>_person` → `on` on person detection
- `rest_command` in HA sends POST with JSON payload including `snapshot_url`
- ai-hub fetches snapshot from `GET http://homeassistant:8123/api/camera_proxy/<entity>?token=<access_token>`
- No new MQTT subscriber needed — simpler than MQTT for this use case

**Entity name pattern**: `binary_sensor.reolink_e1pro_person` (based on camera name in HA)

**Snapshot access**: HA camera access token embedded in URL (valid several hours, no Bearer header needed)

**Alternatives considered**:
- MQTT (Frigate events): rejected — Frigate being removed; adds MQTT subscriber complexity to ai-hub
- Reolink HTTP API polling: rejected — polling introduces latency; HA push is instant
- go2rtc frame grab: rejected — requires ai-hub to maintain RTSP connection continuously

---

## Decision 4: Video Recording (Frigate Replacement)

**Decision**: HA `camera.record` service + `camera.snapshot` for clips and still images

**Rationale**:
- Saves `.mp4` (H.264) to `/config/www/recordings/` on HA host, accessible via `http://homeassistant:8123/local/recordings/`
- Triggered by same automation that fires the ai-hub webhook — no extra services
- Requires `stream:` integration enabled (default in HA 2023+) and `allowlist_external_dirs`
- `lookback: 5` captures 5s of pre-event buffer

**Frigate migration path**:
- Remove `frigate` service from docker-compose
- Move go2rtc to standalone `alexxit/go2rtc` container (or use HA's embedded go2rtc)
- Update `camera-listener` RTSP URL from `rtsp://frigate:8554/...` to `rtsp://go2rtc:8554/...`
- Update `AIHUB_GO2RTC_BASE_URL` from `http://frigate:1984` to `http://go2rtc:1984`
- **Note**: Constitution Technology Constraints lists Frigate — amendment required (PATCH level)

---

## Decision 5: PTZ Gestures

**Decision**: Extend existing `reolink_client.py` with gesture methods using existing `ptz_burst(op, speed, duration)` API

**Implementation**:
```
nod()        → ptz_burst("Up", speed=10, 0.25s) then ptz_burst("Down", speed=10, 0.25s)
shake_head() → ptz_burst("Left", speed=10, 0.25s) then ptz_burst("Right", speed=10, 0.25s)
thinking()   → ptz_burst("Down", speed=6, 0.4s)
home_pos()   → ptz_preset(preset_id=0)
```

**Response type detection**: Scan Codex response text for Swedish affirmative/negative keywords before TTS dispatch — call appropriate gesture in background thread.

**Affirmative keywords**: ja, absolut, självklart, visst, precis, stämmer, exakt, givetvis
**Negative keywords**: nej, inte, tyvärr, dessvärre, fel, stämmer inte

---

## Decision 6: Memory Layer

**Decision**: Post-conversation async Codex extraction → new `memory_facts` SQLite table → injected into system prompt

**Rationale**:
- Reuses existing Codex client — no new NLP pipeline
- Extraction prompt: ask Codex to return JSON array of `{fact, category, follow_up_date?}` after each conversation
- Categories: `mood`, `event`, `plan`, `preference`, `health`, `social`
- Inject top 10 most recent/relevant facts for active person into system prompt context block
- `follow_up_date` enables proactive scheduler to trigger follow-up conversations

**Extraction timing**: Background thread after conversation closes (not blocking main response loop)

---

## Decision 7: Presence Tracking

**Decision**: New `person_presence` table in aihub.db — updated on every face recognition event

**Fields**: `person_name`, `last_seen_at`, `arrived_at`, `greeted_at`
**Arrival logic**: `last_seen_at` older than `AIHUB_ARRIVAL_COOLDOWN_SEC` (default 7200s = 2h) → treat current detection as new arrival
**Unknown-person cooldown**: separate `last_unknown_at` field in `mode_state` key-value table — compare against `AIHUB_UNKNOWN_PERSON_COOLDOWN_SEC` (default 86400s = 24h)

---

## Decision 8: Proactive Triggers

**Decision**: Extend existing `schedule_followup` / threading.Timer pattern in main.py for time-based and memory-based triggers

**Morning greeting**: `AIHUB_MORNING_GREETING_TIME` env var (default `07:00`) — scheduler checks at startup and reschedules daily
**Memory follow-up**: After memory extraction, if `follow_up_date` is set, schedule a timer for that date/time
**Word of day**: Simple daily scheduler pulling from a configurable word list or Codex-generated word

---

## Resolved: All NEEDS CLARIFICATION

- FR-010 (recognition approach): **ML-based (InsightFace buffalo_l)** — RTX 4070 handles event-triggered recognition in < 50ms per image ✅
