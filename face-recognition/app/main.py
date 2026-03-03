"""face-recognition FastAPI service — identity via InsightFace buffalo_l."""
from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.security.api_key import APIKeyHeader

from .enrollment import EnrollmentStore
from .recognizer import FaceRecognizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

store = EnrollmentStore()
recognizer = FaceRecognizer(store)

app = FastAPI(title="face-recognition", version="1.0.0")


@app.on_event("startup")
async def _startup() -> None:
    store.load_from_disk()
    logger.info("face-recognition service ready, enrolled: %s", store.list_persons())


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("FACE_RECOGNITION_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_api_key(key: str | None = Depends(_api_key_header)) -> None:
    if _API_KEY and key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/recognize")
async def recognize(
    image: UploadFile = File(...),
    min_score: float = Form(None),
    _: None = Depends(_require_api_key),
) -> dict:
    """Identify a person from a JPEG image."""
    if min_score is not None:
        os.environ["FACE_RECOGNITION_THRESHOLD"] = str(min_score)
    jpeg_bytes = await image.read()
    return recognizer.recognize(jpeg_bytes)


@app.post("/enroll")
async def enroll(
    name: str = Form(...),
    image: UploadFile = File(...),
    _: None = Depends(_require_api_key),
) -> dict:
    """Add or update a face for a named person."""
    jpeg_bytes = await image.read()
    result = recognizer.enroll(name, jpeg_bytes)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.delete("/persons/{name}")
async def delete_person(
    name: str,
    _: None = Depends(_require_api_key),
) -> dict:
    """Remove all stored embeddings for a person."""
    removed = store.delete_person(name)
    return {"ok": True, "name": name, "removed_count": removed}


@app.get("/health")
async def health() -> dict:
    """Service health + GPU status."""
    gpu = False
    provider = "CPUExecutionProvider"
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        if "CUDAExecutionProvider" in available:
            gpu = True
            provider = "CUDAExecutionProvider"
    except Exception:
        pass
    return {
        "ok": True,
        "gpu": gpu,
        "provider": provider,
        "enrolled_persons": len(store.list_persons()),
        "model": "buffalo_l",
    }
