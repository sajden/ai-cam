from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field


APP_VERSION = "0.3.0"
TOKEN = os.getenv("CAMERA_VOICE_BRIDGE_TOKEN", "").strip()
EDGE_TTS_VOICE = os.getenv("CAMERA_VOICE_EDGE_TTS_VOICE", "sv-SE-SofieNeural").strip()
GAIN_DB = float(os.getenv("CAMERA_VOICE_GAIN_DB", "14"))
AUDIO_RETENTION_SEC = int(os.getenv("CAMERA_VOICE_AUDIO_RETENTION_SEC", "900"))
AIHUB_URL = os.getenv("CAMERA_VOICE_AIHUB_URL", "http://aihub:8080").strip().rstrip("/")
AUDIO_BRIDGE_URL = os.getenv("CAMERA_VOICE_AUDIO_BRIDGE_URL", "http://host.docker.internal:8092").strip().rstrip("/")
AUDIO_BRIDGE_TIMEOUT_SEC = int(os.getenv("CAMERA_VOICE_AUDIO_BRIDGE_TIMEOUT_SEC", "30"))
AUDIO_BRIDGE_TOKEN = os.getenv("CAMERA_VOICE_AUDIO_BRIDGE_TOKEN", "").strip()
AUDIO_BRIDGE_CALLER = os.getenv("CAMERA_VOICE_AUDIO_BRIDGE_CALLER", "camera-voice-bridge").strip()
AUDIO_DIR = Path(os.getenv("CAMERA_VOICE_AUDIO_DIR", "/data/audio")).resolve()
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
SPEAK_MAX_LENGTH = int(os.getenv("CAMERA_VOICE_SPEAK_MAX_LENGTH", "4000"))

app = FastAPI(title="camera-voice-bridge", version=APP_VERSION)

logger = logging.getLogger("camera-voice-bridge")


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    supplied = authorization.replace("Bearer ", "", 1).strip()
    if supplied != TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )


def _cleanup_old_audio() -> None:
    now = time.time()
    if not AUDIO_DIR.exists():
        return
    for p in AUDIO_DIR.glob("*.wav"):
        try:
            if now - p.stat().st_mtime > AUDIO_RETENTION_SEC:
                p.unlink(missing_ok=True)
        except Exception:
            pass


def _strip_markdown(text: str) -> str:
    """Remove common markdown formatting so TTS reads clean text."""
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _wav_duration_sec(wav_path: Path) -> float:
    """Return duration in seconds of a WAV file, or 0.0 on error."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return frames / rate
    except Exception:
        return 0.0


def _report_speaker_state(playing: bool, duration_sec: float = 0.0) -> None:
    """Best-effort POST to ai-hub speaker state endpoint."""
    payload = {"speaker_playing": playing, "duration_sec": duration_sec}
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{AIHUB_URL}/v1/speaker/state",
            method="POST",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        logger.debug("Failed to report speaker state: %s", exc)


def _generate_edge_tts(text: str, voice: str = EDGE_TTS_VOICE) -> bytes:
    """Generate WAV bytes via Microsoft edge-tts."""
    import edge_tts

    async def _synth() -> bytes:
        communicate = edge_tts.Communicate(text=text, voice=voice)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_mp3 = tmp.name
        await communicate.save(tmp_mp3)

        tmp_wav = tmp_mp3.replace(".mp3", ".wav")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_mp3,
                "-ar", "24000", "-ac", "1", "-f", "wav", tmp_wav,
            ],
            capture_output=True, timeout=30,
        )
        wav_bytes = Path(tmp_wav).read_bytes()

        Path(tmp_mp3).unlink(missing_ok=True)
        Path(tmp_wav).unlink(missing_ok=True)
        return wav_bytes

    return asyncio.run(_synth())


def _apply_gain_if_needed(wav_path: Path) -> Path:
    if abs(GAIN_DB) < 0.01:
        return wav_path

    boosted = wav_path.with_name(f"{wav_path.stem}_gain.wav")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(wav_path),
        "-af",
        f"volume={GAIN_DB}dB",
        str(boosted),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0 and boosted.exists() and boosted.stat().st_size > 0:
            return boosted
    except Exception:
        pass
    return wav_path


def _send_to_audio_bridge(wav_path: Path) -> tuple[bool, str]:
    """POST WAV bytes to the Windows audio bridge."""
    wav_bytes = wav_path.read_bytes()
    headers = {
        "Content-Type": "audio/wav",
        "X-Audio-Bridge-Caller": AUDIO_BRIDGE_CALLER or "camera-voice-bridge",
    }
    if AUDIO_BRIDGE_TOKEN:
        headers["Authorization"] = f"Bearer {AUDIO_BRIDGE_TOKEN}"
    req = urllib.request.Request(
        AUDIO_BRIDGE_URL,
        method="POST",
        data=wav_bytes,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=AUDIO_BRIDGE_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return False, f"audio_bridge_http_{exc.code}: {detail}"
    except Exception as exc:
        return False, f"audio_bridge_error: {exc}"


def _interrupt_audio_bridge(reason: str = "barge_in") -> tuple[bool, str]:
    payload = json.dumps({"reason": reason.strip() or "barge_in"}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Audio-Bridge-Caller": AUDIO_BRIDGE_CALLER or "camera-voice-bridge",
    }
    if AUDIO_BRIDGE_TOKEN:
        headers["Authorization"] = f"Bearer {AUDIO_BRIDGE_TOKEN}"
    req = urllib.request.Request(
        f"{AUDIO_BRIDGE_URL}/interrupt",
        method="POST",
        data=payload,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=min(5, AUDIO_BRIDGE_TIMEOUT_SEC)) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return False, f"audio_bridge_http_{exc.code}: {detail}"
    except Exception as exc:
        return False, f"audio_bridge_error: {exc}"


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=max(200, SPEAK_MAX_LENGTH))


class InterruptRequest(BaseModel):
    reason: str = Field(default="barge_in", max_length=120)


@app.get("/v1/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "camera-voice-bridge",
        "version": APP_VERSION,
        "tts_voice": EDGE_TTS_VOICE,
        "gain_db": GAIN_DB,
        "audio_bridge_url": AUDIO_BRIDGE_URL,
        "audio_bridge_token_set": bool(AUDIO_BRIDGE_TOKEN),
        "audio_bridge_caller": AUDIO_BRIDGE_CALLER or "camera-voice-bridge",
    }


@app.post("/v1/speak")
def speak(req: SpeakRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    _cleanup_old_audio()

    text = _strip_markdown(req.text.strip())
    try:
        wav_bytes = _generate_edge_tts(text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"edge_tts_error: {exc}")
    if not wav_bytes:
        raise HTTPException(status_code=502, detail="edge-tts returned empty audio")

    filename = f"tts_{uuid.uuid4().hex[:12]}.wav"
    out_path = AUDIO_DIR / filename
    out_path.write_bytes(wav_bytes)
    play_path = _apply_gain_if_needed(out_path)
    duration = _wav_duration_sec(play_path)

    pushed, push_detail = _send_to_audio_bridge(play_path)

    if not pushed:
        raise HTTPException(
            status_code=502,
            detail=f"audio_push_error: {push_detail}",
        )

    # Report speaker state to ai-hub so camera-listener can suppress echo.
    if duration > 0:
        _report_speaker_state(playing=True, duration_sec=duration)

    return {
        "ok": True,
        "audio_file": filename,
        "tts_engine": "edge-tts",
        "audio_bridge": AUDIO_BRIDGE_URL,
        "duration_sec": round(duration, 2),
    }


@app.post("/v1/interrupt")
def interrupt(req: InterruptRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _require_auth(authorization)
    ok, detail = _interrupt_audio_bridge(req.reason)
    _report_speaker_state(playing=False, duration_sec=0.0)
    if not ok:
        raise HTTPException(
            status_code=502,
            detail=f"audio_interrupt_error: {detail}",
        )
    return {
        "ok": True,
        "audio_bridge": AUDIO_BRIDGE_URL,
        "detail": detail,
    }
