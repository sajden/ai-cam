"""HTTP client for the face-recognition service."""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("AIHUB_FACE_RECOGNITION_URL", "http://face-recognition:8082")
_API_KEY = os.getenv("FACE_RECOGNITION_API_KEY", "")
_TIMEOUT = 10.0

_FALLBACK_NO_MATCH: dict = {"matched": False, "name": None, "confidence": 0.0, "bbox": None, "face_detected": False}


def _headers() -> dict[str, str]:
    if _API_KEY:
        return {"X-API-Key": _API_KEY}
    return {}


async def async_recognize(jpeg_bytes: bytes) -> dict:
    """
    POST JPEG bytes to face-recognition /recognize.

    Returns a result dict per the service contract. On any error,
    logs a warning and returns a ``matched=False`` fallback so the
    caller can degrade gracefully.
    """
    if not jpeg_bytes:
        return dict(_FALLBACK_NO_MATCH)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_BASE_URL}/recognize",
                files={"image": ("snapshot.jpg", jpeg_bytes, "image/jpeg")},
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("face-recognition /recognize unavailable: %s", exc)
        return dict(_FALLBACK_NO_MATCH)


async def async_enroll(name: str, jpeg_bytes: bytes) -> dict:
    """
    POST name + JPEG to face-recognition /enroll.

    Returns the service response dict. On error returns ``{"ok": False}``.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_BASE_URL}/enroll",
                data={"name": name},
                files={"image": ("enroll.jpg", jpeg_bytes, "image/jpeg")},
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("face-recognition /enroll failed for %s: %s", name, exc)
        return {"ok": False, "reason": str(exc)}


async def async_delete(name: str) -> dict:
    """DELETE /persons/{name} from face-recognition service."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.delete(
                f"{_BASE_URL}/persons/{name}",
                headers=_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("face-recognition /persons/%s delete failed: %s", name, exc)
        return {"ok": False, "reason": str(exc)}
