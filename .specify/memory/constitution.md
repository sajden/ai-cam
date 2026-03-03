<!--
  SYNC IMPACT REPORT
  ==================
  Version change: 1.0.0 → 1.0.1
  PATCH amendment: Replace Frigate NVR with standalone go2rtc + HA camera.record.
  Frigate bundled go2rtc replaced by alexxit/go2rtc standalone container; person detection
  now handled by HA Reolink integration. Recording via HA camera.record to /config/www/.
  Original version 1.0.0 — initial ai-cam constitution.

  New principles:
    I.   Privacy-by-Default
    II.  Container-First Architecture
    III. Config-as-Environment
    IV.  Graceful Degradation
    V.   Minimal External Surface

  New sections:
    - Core Principles (5 principles)
    - Technology Constraints
    - Development Workflow
    - Governance

  Templates reviewed:
    - .specify/templates/plan-template.md   ✅ Constitution Check gate present; no changes needed
    - .specify/templates/spec-template.md   ✅ No constitution-specific references; no changes needed
    - .specify/templates/tasks-template.md  ✅ Task structure compatible with these principles
    - .specify/templates/checklist-template.md  ✅ Generic; no changes needed

  Deferred TODOs:
    - None. All placeholders resolved.
-->

# ai-cam Constitution

## Core Principles

### I. Privacy-by-Default

All audio and video data MUST be processed on-premises. Raw camera feeds and microphone audio MUST NOT leave the local network.
Wake word detection MUST run locally (OpenWakeWord). STT MUST default to a local engine (Whisper) with cloud fallback only when
explicitly configured. When text is sent to a cloud LLM (e.g. Codex/ChatGPT), only the text transcript is transmitted — never
raw audio or video frames. Any cloud integration MUST be opt-in, documented, and clearly labelled in `.env.example`.

**Rationale**: The system processes home interior audio and video 24/7. Privacy violations are irreversible. Local-first is
non-negotiable; cloud is a configurable escape hatch, not the default.

### II. Container-First Architecture

Every service MUST run as a single-purpose Docker container defined in `docker-compose.yml`. Services MUST communicate
exclusively over the internal Docker network (`ai_net`). Host-port bindings MUST only exist for UI access (e.g. go2rtc,
Home Assistant) and MUST be scoped to `UI_BIND_ADDR` (never hardcoded to `0.0.0.0` in production). A service MUST have
one primary responsibility; shared logic MUST be exposed via HTTP API, not shared code.

**Rationale**: Single-purpose containers are independently deployable, restartable, and auditable. Tight network scoping
minimises the attack surface when the stack is running.

### III. Config-as-Environment

All secrets, credentials, and tunable runtime parameters MUST be sourced from environment variables. `.env` MUST be gitignored.
`.env.example` MUST be kept in sync with every new env var added — including a safe default or a placeholder comment.
No secret MUST appear in `docker-compose.yml`, Dockerfiles, or source code. Config read at startup MUST be validated and
the service MUST fail fast with a clear error if a required value is absent.

**Rationale**: Secrets in version control are a permanent leak. Env-var driven config enables per-environment overrides
without code changes and keeps the git history clean.

### IV. Graceful Degradation

Each service MUST remain operational when optional dependent services are unavailable. Specifically:
- TTS failures (camera speaker, audio bridge) MUST be logged but MUST NOT crash or block the assistant reply loop.
- STT cloud fallback MAY be used when the primary engine fails, but the assistant MUST still respond if both fail.
- Camera PTZ/action failures MUST be surfaced as log warnings, not unhandled exceptions.
- Background threads MUST wrap all work in try/except and log errors without propagating them to the main loop.

**Rationale**: The assistant runs in a home environment where individual services (camera, Spotify, TTS) can drop at any
time. A partial failure MUST degrade gracefully, not bring down the whole interaction loop.

### V. Minimal External Surface

External API calls MUST be justified and documented in code comments or README. Prefer local-first alternatives. When a
cloud dependency is introduced, its cost, data exposure, and fallback behaviour MUST be documented. New external endpoints
MUST NOT be added without a corresponding `.env` opt-in flag. Complexity MUST be proportional to the current requirement —
YAGNI applies: no speculative abstractions, no premature configurability.

**Rationale**: Every external call is a latency risk, a cost, and a privacy concern. Keeping the surface small makes the
system auditable and budget-predictable.

## Technology Constraints

- **Runtime**: Docker Desktop on Windows host with WSL2 backend.
- **Primary language**: Python 3.11 (all custom services: aihub, camera-listener, camera-voice-bridge, codex-gateway).
- **Service framework**: FastAPI + Uvicorn for HTTP APIs.
- **Messaging**: MQTT via Mosquitto for event-driven triggers between services.
- **Local LLM**: Ollama on Windows host (GPU), accessible via `host.docker.internal`.
- **Cloud LLM**: Codex CLI (OpenAI ChatGPT OAuth) via codex-gateway — configurable, not mandatory.
- **STT**: Google Cloud STT (primary) + Whisper large-v3-turbo (fallback). Both configurable.
- **TTS**: edge-tts (Microsoft Sofie sv-SE cloud) via camera-voice-bridge → audio-bridge (Windows).
- **Vision**: OpenCV (local CV) + Ollama llava/llama3.2-vision (local VLM).
- **NVR**: go2rtc (standalone, `alexxit/go2rtc`) for RTSP re-publishing and WebRTC live view.
  Person detection via HA Reolink integration (`binary_sensor.reolink_e1pro_person`).
  Event recording via HA `camera.record` service to `/config/www/recordings/`.
- **Wake word**: OpenWakeWord (local, model: hey_jarvis).
- **Storage**: SQLite for aihub turn history (`./data/aihub/aihub.db`). No shared database.

## Development Workflow

- All services MUST be buildable and runnable with `docker compose up -d --build <service>`.
- `.env.example` MUST be updated alongside any new env var before the change is committed.
- Container image changes (Dockerfile or requirements.txt) REQUIRE a `--build` flag — never assume a stale image.
- Service logs MUST use structured `INFO`/`WARNING`/`ERROR` levels. Debug noise MUST be gated behind an env flag.
- The Codex CLI auth session (`./data/codex-auth`) MUST be re-authenticated via `./scripts/codex_reauth.sh`
  whenever a `401 refresh_token_reused` error appears — never delete the volume without backing up the session.
- Privacy mode (recording on/off) MUST be controllable via ai-hub API or MQTT without a container restart.

## Governance

This constitution supersedes all other implicit practices for the ai-cam project. Amendments require:
1. A version bump according to semantic versioning (MAJOR: principle removal/redefinition; MINOR: new principle or section;
   PATCH: clarification or wording fix).
2. The Sync Impact Report HTML comment updated at the top of this file.
3. Dependent templates (plan, spec, tasks) reviewed and updated if the amendment affects mandatory gates or task categories.

All implementation plans (`plan.md`) MUST include a **Constitution Check** gate that explicitly verifies compliance with
principles I–V before any Phase 0 research proceeds. Any violation MUST be logged in the Complexity Tracking table with
justification.

**Version**: 1.0.1 | **Ratified**: 2026-02-22 | **Last Amended**: 2026-03-03
