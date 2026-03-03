# CONTEXT.md — ai-cam

## Project Overview

Privacy-first local AI camera stack running on Windows host + Docker Desktop WSL2. Four custom Python
3.11 microservices (aihub, camera-listener, camera-voice-bridge, codex-gateway) coordinate STT, wake-word
detection, LLM routing, TTS, and camera PTZ over an internal Docker network. All audio/video processing
runs on-premises; only text transcripts may reach external LLM APIs when explicitly configured.

## Tech Stack & Tooling

| Layer | Tool / Version |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI 0.115.6 + uvicorn[standard] 0.32.1 |
| STT | faster-whisper 1.1.1, SpeechRecognition 3.12.0, Google Cloud STT (opt-in) |
| Wake word | openwakeword ≥ 0.6.0 |
| VAD | webrtcvad-wheels 2.0.14 |
| Vision | opencv-python-headless 4.10.0.84, Pillow 10.4.0, Ollama (Windows host GPU) |
| TTS | edge-tts ≥ 7.0.0 (Microsoft Sofie sv-SE) |
| LLM gateway | Codex CLI via `@openai/codex` (Node.js 24) + openai ≥ 1.75.0 (fallback) |
| Messaging | MQTT via Mosquitto 2 |
| NVR | Frigate (object detection, RTSP) |
| Containers | Docker Compose; base image `python:3.11-slim` for all Python services |
| Dependency mgmt | Plain `pip` + `requirements.txt` (no poetry / uv / pyproject.toml) |
| Testing | None configured |
| Linting | None configured |
| CI/CD | None configured |

## Architecture & Module Structure

Each service lives in its own top-level directory with a single `app/` package:

```
<service>/
├── Dockerfile          # FROM python:3.11-slim; installs requirements.txt; sets CMD
├── requirements.txt    # Pinned deps (pip)
└── app/
    ├── __init__.py
    └── main.py         # Entry point — FastAPI app or __main__ loop
```

**aihub** (`port 8080`) — Central policy hub. Routes turns to local LLM or Codex, manages conversation
memory (SQLite at `./data/aihub/aihub.db`), executes camera/Spotify/HA actions, runs vision loop.
Modules: `main.py`, `db.py`, `actions.py`, `codex_client.py`, `follow_tracker.py`, `reolink_client.py`,
`spotify_client.py`, `ollama_client.py`, `rep_counter.py`, `live_video.py`, `intent_detector.py`,
`policy.py`, `snapshot_client.py`, `stt_corrector.py`.

**codex-gateway** (`port 8090`) — Wraps Codex CLI subprocess (OAuth session) or direct OpenAI API.
Handles thread resumption and search toggling. Auth persisted in `./data/codex-auth/`.

**camera-voice-bridge** (`port 8091`) — Generates edge-tts audio, applies gain, streams to Windows
audio-bridge (port 8092) or camera speaker via RTSP.

**camera-listener** (no port) — Always-on mic service. Reads RTSP audio, runs VAD + OpenWakeWord +
Whisper STT, POSTs turn text to aihub. Entry: `python -m app.main`.

## Dependency Management

- Each service has its own `requirements.txt` with pinned versions (except `openwakeword>=0.6.0`, `numpy`, `edge-tts>=7.0.0`, `openai>=1.75.0`).
- Install: `pip install -r <service>/requirements.txt` inside the container.
- No shared dependency file. Each service is independently buildable.
- To add a dep: edit the service's `requirements.txt`, then `docker compose up -d --build <service>`.

## Testing Strategy

No formal test suite exists. TODO: Clarify if unit/integration tests are planned.

Manual verification pattern used in this repo:
- `docker logs <service> --tail=50` to inspect behaviour.
- Health endpoints: `GET /v1/health` on aihub (8080), codex-gateway (8090).
- Scripts: `./scripts/camera_speak_test.sh`, `./scripts/codex_status.sh`, `./scripts/reolink_ptz_diag.sh`.

## Linting & Formatting Rules

No linter or formatter is configured. TODO: Clarify if ruff/mypy should be adopted.

Observed style conventions in the codebase:
- `from __future__ import annotations` in every module.
- Named module-level logger: `log = logging.getLogger("<service-name>")`.
- `logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", force=True)` at top of `main.py`.
- Pydantic `BaseModel` + `Field` for all FastAPI request/response schemas.
- Module-level constants in `ALL_CAPS` sourced from `os.getenv(...)`.

## Error Handling Conventions

- **API layer**: raise `HTTPException(status_code=..., detail=...)` for client/upstream errors.
- **Background threads**: wrap all work in `try/except Exception as _exc` and `log.error(...)`. Never propagate.
- **Optional imports**: guarded with `try/except Exception` at import time (e.g. Pillow), variable set to `None`.
- **External clients**: return `(ok: bool, reason: str)` tuples or raise `RuntimeError`; callers decide how to surface.
- **Thread safety**: module-level `threading.Lock()` for shared mutable state (token cache, cooldown timestamps).

## CLI / Runtime Behaviour

- `uvicorn app.main:app --host 0.0.0.0 --port <N>` — aihub, codex-gateway, camera-voice-bridge.
- `python -m app.main` — camera-listener (long-running loop, no HTTP server).
- All config via env vars; services fail fast on missing required vars.
- Privacy gate: `AIHUB_AUDIO_REQUIRE_WAKE_OR_ACTIVE=1` — audio ignored unless wake phrase heard or conversation window active.
- Codex OAuth session: `./data/codex-auth/` (volume-mounted); re-auth via `./scripts/codex_reauth.sh`.

## Quality Gates

No automated gates exist. Before pushing, manually verify:

```bash
# 1. Rebuild affected service
docker compose up -d --build <service>

# 2. Check logs for startup errors
docker logs <service> --tail=30

# 3. Health check
docker run --rm --network ai-cam_ai_net curlimages/curl:8.6.0 -fsS http://<service>:<port>/v1/health

# 4. Verify .env.example is in sync with any new env vars you added
```

## DO / DON'T

**DO:**
- Source all config from `os.getenv(...)` with safe defaults; validate at startup.
- Update `.env.example` whenever a new env var is introduced.
- Use `log.error(...)` (not `print`) for all diagnostic output.
- Wrap background thread bodies in `try/except Exception` — a crashing thread MUST log and exit cleanly.
- Use `threading.Lock()` around every shared mutable module-level variable.
- Run `docker compose up -d --build <service>` after any code or requirements change.

**DO NOT:**
- Hardcode credentials, hostnames, or ports in source code — all belong in `.env`.
- Add a new Python dependency without pinning its version in `requirements.txt`.
- Send raw audio or video frames to external APIs — text only.
- Expose service ports to the host unless strictly required for UI access (scope to `UI_BIND_ADDR`).
- Use `assert` for runtime validation in production paths — use `if ... raise RuntimeError(...)` instead.
- Share code between services via imports — duplicate the small helper or expose it via HTTP.
- Commit the `.env` file or any file under `./data/`.
