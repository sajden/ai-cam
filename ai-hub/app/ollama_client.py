"""Ollama VLM client — sends a base64-encoded image + text prompt to a local vision model."""

from __future__ import annotations

import base64
import json
import os
import socket
import urllib.error
import urllib.request

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None


OLLAMA_BASE_URL = os.getenv("AIHUB_OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_VISION_MODEL = os.getenv("AIHUB_OLLAMA_VISION_MODEL", "llama3.2-vision")
OLLAMA_TIMEOUT_SEC = int(os.getenv("AIHUB_OLLAMA_TIMEOUT_SEC", "30"))
OLLAMA_VISION_NUM_PREDICT = int(os.getenv("AIHUB_OLLAMA_VISION_NUM_PREDICT", "160"))
OLLAMA_MAX_IMAGE_EDGE = int(os.getenv("AIHUB_OLLAMA_MAX_IMAGE_EDGE", "960"))
OLLAMA_JPEG_QUALITY = int(os.getenv("AIHUB_OLLAMA_JPEG_QUALITY", "72"))
OLLAMA_RETRY_ON_TIMEOUT = os.getenv("AIHUB_OLLAMA_RETRY_ON_TIMEOUT", "1").strip() == "1"
OLLAMA_CLASSIFY_MODEL = os.getenv("AIHUB_OLLAMA_CLASSIFY_MODEL", OLLAMA_VISION_MODEL)
OLLAMA_CLASSIFY_TIMEOUT_SEC = int(os.getenv("AIHUB_OLLAMA_CLASSIFY_TIMEOUT_SEC", "3"))


def _prepare_image(
    image_bytes: bytes,
    *,
    max_edge: int,
    quality: int,
) -> bytes:
    if not image_bytes:
        return image_bytes
    if Image is None:
        return image_bytes
    try:
        from io import BytesIO

        with Image.open(BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            w, h = img.size
            edge = max(1, int(max_edge))
            if max(w, h) > edge:
                ratio = float(edge) / float(max(w, h))
                nw = max(1, int(w * ratio))
                nh = max(1, int(h * ratio))
                img = img.resize((nw, nh))
            out = BytesIO()
            img.save(out, format="JPEG", quality=max(35, min(95, int(quality))), optimize=True)
            return out.getvalue()
    except Exception:
        return image_bytes


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, socket.timeout):
        return True
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg


def _ollama_generate(
    *,
    question: str,
    image_bytes: bytes,
    timeout_sec: int,
    num_predict: int,
    extra_frames: list[bytes] | None = None,
) -> tuple[bool, str]:
    all_frames = [image_bytes] + list(extra_frames or [])
    images_b64 = [base64.b64encode(f).decode("ascii") for f in all_frames if f]
    payload = {
        "model": OLLAMA_VISION_MODEL,
        "prompt": question,
        "images": images_b64,
        "stream": False,
        "options": {
            "num_predict": max(32, int(num_predict)),
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        method="POST",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, int(timeout_sec))) as resp:
            body = json.loads(resp.read())
            text = str(body.get("response", "")).strip()
            if not text:
                return False, "Vision-modellen returnerade inget svar."
            return True, text
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        return False, f"Ollama HTTP {exc.code}: {detail or 'okänt fel'}"
    except Exception as exc:
        return False, f"Ollama-koppling misslyckades: {type(exc).__name__}"


def classify_as_vision(text: str) -> bool:
    """Return True if *text* is a query a camera can help answer.

    Sends a short text-only request to Ollama (no image).  Uses a tight
    timeout so a busy/slow Ollama never blocks the main conversation path.
    Falls back to False on any error.
    """
    prompt = (
        f'Fråga: "{text.strip()}"\n\n'
        "Kan en kamera hjälpa till att besvara denna fråga — t.ex. hur personen ser ut, "
        "vad de har på sig, hur de rör sig, dansar eller tränar?\n"
        "Svara enbart med: ja eller nej"
    )
    payload = {
        "model": OLLAMA_CLASSIFY_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 5},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        method="POST",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_CLASSIFY_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read())
            answer = str(body.get("response", "")).strip().lower()
            return answer.startswith("ja")
    except Exception:
        return False


def ask_vision_model(
    question: str,
    image_bytes: bytes,
    *,
    extra_frames: list[bytes] | None = None,
    timeout_sec: int | None = None,
    num_predict: int | None = None,
) -> tuple[bool, str]:
    """Send *question* + JPEG frame(s) to Ollama and return (ok, answer_text).

    Pass *extra_frames* to send a multi-frame sequence for activity/motion analysis.
    Uses the ``/api/generate`` endpoint with inline base64 images.
    """
    t = max(1, int(timeout_sec or OLLAMA_TIMEOUT_SEC))
    n = max(32, int(num_predict or OLLAMA_VISION_NUM_PREDICT))
    prepared = _prepare_image(
        image_bytes,
        max_edge=OLLAMA_MAX_IMAGE_EDGE,
        quality=OLLAMA_JPEG_QUALITY,
    )
    prepared_extras = [
        _prepare_image(f, max_edge=OLLAMA_MAX_IMAGE_EDGE, quality=OLLAMA_JPEG_QUALITY)
        for f in (extra_frames or [])
        if f
    ]
    ok, text = _ollama_generate(
        question=question,
        image_bytes=prepared,
        extra_frames=prepared_extras or None,
        timeout_sec=t,
        num_predict=n,
    )
    if ok:
        return True, text

    # One fast fallback retry for timeouts only: single frame + smaller image.
    if OLLAMA_RETRY_ON_TIMEOUT and "TimeoutError" in text:
        retry_img = _prepare_image(
            image_bytes,
            max_edge=min(640, OLLAMA_MAX_IMAGE_EDGE),
            quality=min(60, OLLAMA_JPEG_QUALITY),
        )
        ok2, text2 = _ollama_generate(
            question=question,
            image_bytes=retry_img,
            timeout_sec=max(6, min(12, t)),
            num_predict=min(120, n),
        )
        if ok2:
            return True, text2
        return False, f"{text}; retry={text2}"
    return False, text
