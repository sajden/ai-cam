# ai-cam Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-02-26

## Active Technologies
- Python 3.11 + insightface 0.7.3, onnxruntime-gpu, FastAPI (existing), httpx (HA snapshot fetch), numpy (002-face-recognition)
- SQLite aihub.db — 2 new tables (`person_presence`, `memory_facts`); named Docker volume for InsightFace models (002-face-recognition)
- Python 3.11 + FastAPI + Uvicorn (existing), SQLite via stdlib `sqlite3` (existing), `urllib.request` for HA REST polling (existing) (004-presence-tracking)
- SQLite `aihub.db` — new `desk_trips` table (004-presence-tracking)

- Python 3.11 + FastAPI 0.115.6, Uvicorn 0.32.1, Pillow 10.4.0, OpenCV-headless 0.10.0.84 (no new dependencies required) (001-humanize-ai-companion)

## Project Structure

```text
face-recognition/       ← NEW: InsightFace GPU service (port 8082 internal)
  app/
    main.py             ← FastAPI endpoints: /recognize /enroll /health
    recognizer.py       ← FaceAnalysis buffalo_l wrapper, cosine matching
    enrollment.py       ← In-memory + JSON disk embedding store
  Dockerfile            ← nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
  requirements.txt

ai-hub/app/
  main.py               ← Arrival flow, PTZ gestures, memory extraction wire-up
  db.py                 ← person_presence + memory_facts tables + CRUD
  face_client.py        ← NEW: async HTTP client for face-recognition service
  memory_manager.py     ← NEW: post-conversation fact extraction + follow-up scheduler
  codex_client.py       ← _build_session_context_block now injects memory facts
  reolink_client.py     ← PTZ gesture helpers used via main.py

data/go2rtc/
  config.yaml.example   ← go2rtc stream config template (copy → config.yaml)
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11: Follow standard conventions

## Recent Changes
- 004-presence-tracking: Added Python 3.11 + FastAPI + Uvicorn (existing), SQLite via stdlib `sqlite3` (existing), `urllib.request` for HA REST polling (existing)
- 002-face-recognition: Added Python 3.11 + insightface 0.7.3, onnxruntime-gpu, FastAPI (existing), httpx (HA snapshot fetch), numpy

- 001-humanize-ai-companion: Added Python 3.11 + FastAPI 0.115.6, Uvicorn 0.32.1, Pillow 10.4.0, OpenCV-headless 0.10.0.84 (no new dependencies required)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
