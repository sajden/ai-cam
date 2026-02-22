from __future__ import annotations

import collections
import json
import logging
import math
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import wave
import audioop
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
import requests
import speech_recognition as sr
import webrtcvad
from faster_whisper import WhisperModel

try:
    from openwakeword.model import Model as OWWModel
    from openwakeword.utils import download_models as oww_download_models

    OWW_AVAILABLE = True
except Exception:
    OWW_AVAILABLE = False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


LOG_LEVEL = os.getenv("CAMERA_LISTENER_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("camera-listener")
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("faster_whisper.transcribe").setLevel(logging.WARNING)

ENABLED = _env_bool("CAMERA_LISTENER_ENABLED", True)
RTSP_URL = os.getenv("CAMERA_LISTENER_RTSP_URL", "rtsp://frigate:8554/reolink_e1pro_main").strip()
DEVICE_ID = os.getenv("CAMERA_LISTENER_DEVICE_ID", "reolink_mic").strip()
AIHUB_URL = os.getenv("CAMERA_LISTENER_AIHUB_URL", "http://aihub:8080").strip().rstrip("/")
AIHUB_TOKEN = os.getenv("CAMERA_LISTENER_AIHUB_TOKEN", os.getenv("AIHUB_TOKEN", "")).strip()
ALLOW_CODEX = _env_bool("CAMERA_LISTENER_ALLOW_CODEX", True)

WAKE_PHRASES = [
    p.strip().lower()
    for p in os.getenv("CAMERA_LISTENER_WAKE_PHRASES", "hej codex,hey codex").split(",")
    if p.strip()
]
WAKE_ALIASES = [
    p.strip().lower()
    for p in os.getenv("CAMERA_LISTENER_WAKE_ALIASES", "").split(",")
    if p.strip()
]
if not WAKE_ALIASES:
    aliases = set(WAKE_PHRASES)
    for p in WAKE_PHRASES:
        aliases.add(p.replace("codex", "kodex"))
    WAKE_ALIASES = sorted(aliases)
WAKE_CANONICAL = WAKE_PHRASES[0] if WAKE_PHRASES else "hej codex"
STOP_PHRASES = [
    p.strip().lower()
    for p in os.getenv(
        "CAMERA_LISTENER_STOP_PHRASES",
        "stopp codex,stopp kodex,sluta codex,sluta kodex",
    ).split(",")
    if p.strip()
]
STOP_ACK_TEXT = os.getenv("CAMERA_LISTENER_STOP_ACK_TEXT", "Okej, jag pausar.").strip()
IDLE_PHRASES = [
    p.strip().lower()
    for p in os.getenv(
        "CAMERA_LISTENER_IDLE_PHRASES",
        "sov jarvis,vila jarvis,jarvis sov,jarvis vila",
    ).split(",")
    if p.strip()
]
IDLE_ACK_TEXT = os.getenv("CAMERA_LISTENER_IDLE_ACK_TEXT", "Okej, går till viloläge.").strip()
CORRECTION_PREFIXES = [
    p.strip().lower()
    for p in os.getenv(
        "CAMERA_LISTENER_CORRECTION_PREFIXES",
        "vänta jarvis,jarvis vänta,jag menar,jag menade,nej vänta,ändring",
    ).split(",")
    if p.strip()
]
CORRECTION_ACK_TEXT = os.getenv("CAMERA_LISTENER_CORRECTION_ACK_TEXT", "").strip()

STT_BACKEND = os.getenv("CAMERA_LISTENER_STT_BACKEND", "local").strip().lower()
STT_MODEL = os.getenv("CAMERA_LISTENER_STT_MODEL", "small").strip()
STT_DEVICE = os.getenv("CAMERA_LISTENER_STT_DEVICE", "cpu").strip()
STT_COMPUTE_TYPE = os.getenv("CAMERA_LISTENER_STT_COMPUTE_TYPE", "int8").strip()
STT_LANGUAGE = os.getenv("CAMERA_LISTENER_STT_LANGUAGE", "sv").strip()
MODEL_DIR = os.getenv("CAMERA_LISTENER_MODEL_DIR", "/data/models").strip()
STT_BEAM_SIZE = _env_int("CAMERA_LISTENER_STT_BEAM_SIZE", 1)
STT_BEST_OF = _env_int("CAMERA_LISTENER_STT_BEST_OF", 1)
STT_NO_SPEECH_THRESHOLD = _env_float("CAMERA_LISTENER_STT_NO_SPEECH_THRESHOLD", 0.55)
STT_LOGPROB_THRESHOLD = _env_float("CAMERA_LISTENER_STT_LOGPROB_THRESHOLD", -0.8)
SEGMENT_MIN_AVG_LOGPROB = _env_float("CAMERA_LISTENER_SEGMENT_MIN_AVG_LOGPROB", -0.9)
SEGMENT_MAX_NO_SPEECH_PROB = _env_float("CAMERA_LISTENER_SEGMENT_MAX_NO_SPEECH_PROB", 0.6)
WAKE_SECOND_TOKEN_MIN_SIM = _env_float("CAMERA_LISTENER_WAKE_SECOND_TOKEN_MIN_SIM", 0.58)
WAKE_ONLY_MODE = _env_bool("CAMERA_LISTENER_WAKE_ONLY_MODE", True)
WAKE_STT_MODEL = os.getenv("CAMERA_LISTENER_WAKE_STT_MODEL", "tiny").strip()
WAKE_STT_DEVICE = os.getenv("CAMERA_LISTENER_WAKE_STT_DEVICE", STT_DEVICE).strip()
WAKE_STT_COMPUTE_TYPE = os.getenv("CAMERA_LISTENER_WAKE_STT_COMPUTE_TYPE", STT_COMPUTE_TYPE).strip()
WAKE_STT_LANGUAGE = os.getenv("CAMERA_LISTENER_WAKE_STT_LANGUAGE", STT_LANGUAGE).strip()
WAKE_STT_BEAM_SIZE = _env_int("CAMERA_LISTENER_WAKE_STT_BEAM_SIZE", 1)
WAKE_STT_BEST_OF = _env_int("CAMERA_LISTENER_WAKE_STT_BEST_OF", 1)
WAKE_STT_NO_SPEECH_THRESHOLD = _env_float("CAMERA_LISTENER_WAKE_STT_NO_SPEECH_THRESHOLD", 0.7)
WAKE_STT_LOGPROB_THRESHOLD = _env_float("CAMERA_LISTENER_WAKE_STT_LOGPROB_THRESHOLD", -0.4)
WAKE_SEGMENT_MIN_AVG_LOGPROB = _env_float("CAMERA_LISTENER_WAKE_SEGMENT_MIN_AVG_LOGPROB", -1.6)
WAKE_SEGMENT_MAX_NO_SPEECH_PROB = _env_float("CAMERA_LISTENER_WAKE_SEGMENT_MAX_NO_SPEECH_PROB", 0.98)
WAKE_ALLOW_FUZZY_MATCH = _env_bool("CAMERA_LISTENER_WAKE_ALLOW_FUZZY_MATCH", False)

SAMPLE_RATE = _env_int("CAMERA_LISTENER_SAMPLE_RATE", 16000)
CHUNK_SEC = _env_float("CAMERA_LISTENER_CHUNK_SEC", 1.2)
MIN_DBFS = _env_float("CAMERA_LISTENER_MIN_DBFS", -42.0)
MAX_PENDING_CHUNKS = _env_int("CAMERA_LISTENER_MAX_PENDING_CHUNKS", 3)
VAD_MODE = _env_int("CAMERA_LISTENER_VAD_MODE", 2)  # 0..3, higher = stricter
VAD_FRAME_MS = _env_int("CAMERA_LISTENER_VAD_FRAME_MS", 30)
VAD_START_FRAMES = _env_int("CAMERA_LISTENER_VAD_START_FRAMES", 3)
VAD_END_FRAMES = _env_int("CAMERA_LISTENER_VAD_END_FRAMES", 14)
VAD_PREROLL_FRAMES = _env_int("CAMERA_LISTENER_VAD_PREROLL_FRAMES", 6)
VAD_MIN_SPEECH_MS = _env_int("CAMERA_LISTENER_VAD_MIN_SPEECH_MS", 240)
VAD_MAX_SPEECH_SEC = _env_float("CAMERA_LISTENER_VAD_MAX_SPEECH_SEC", 8.0)
MIN_TEXT_LEN = _env_int("CAMERA_LISTENER_MIN_TEXT_LEN", 3)
WAKE_COOLDOWN_SEC = _env_float("CAMERA_LISTENER_WAKE_COOLDOWN_SEC", 3.0)
CONVERSATION_TTL_SEC = _env_float("CAMERA_LISTENER_CONVERSATION_TTL_SEC", 90.0)
MIN_TURN_INTERVAL_SEC = _env_float("CAMERA_LISTENER_MIN_TURN_INTERVAL_SEC", 1.2)
DUPLICATE_WINDOW_SEC = _env_float("CAMERA_LISTENER_DUPLICATE_WINDOW_SEC", 8.0)
RECONNECT_DELAY_SEC = _env_float("CAMERA_LISTENER_RECONNECT_DELAY_SEC", 1.5)
STATUS_PATH = Path(os.getenv("CAMERA_LISTENER_STATUS_PATH", "/data/status.json"))
STATUS_HEARTBEAT_SEC = _env_float("CAMERA_LISTENER_STATUS_HEARTBEAT_SEC", 2.0)
DEBUG_TRANSCRIPTS = _env_bool("CAMERA_LISTENER_DEBUG_TRANSCRIPTS", False)
HTTP_CONNECT_TIMEOUT_SEC = _env_float("CAMERA_LISTENER_HTTP_CONNECT_TIMEOUT_SEC", 2.0)
SPEAKER_STATE_TIMEOUT_SEC = _env_float("CAMERA_LISTENER_SPEAKER_STATE_TIMEOUT_SEC", 1.5)
WAKE_TIMEOUT_SEC = _env_float("CAMERA_LISTENER_WAKE_TIMEOUT_SEC", 12.0)
TURN_TIMEOUT_SEC = _env_float("CAMERA_LISTENER_TURN_TIMEOUT_SEC", 45.0)
INTERRUPT_TIMEOUT_SEC = _env_float("CAMERA_LISTENER_INTERRUPT_TIMEOUT_SEC", 3.0)
ANNOUNCE_TIMEOUT_SEC = _env_float("CAMERA_LISTENER_ANNOUNCE_TIMEOUT_SEC", 5.0)
LATENCY_WARN_STT_MS = _env_float("CAMERA_LISTENER_LATENCY_WARN_STT_MS", 1200.0)
LATENCY_WARN_BARGE_STT_MS = _env_float("CAMERA_LISTENER_LATENCY_WARN_BARGE_STT_MS", 900.0)
LATENCY_WARN_SPEAKER_STATE_MS = _env_float("CAMERA_LISTENER_LATENCY_WARN_SPEAKER_STATE_MS", 180.0)
LATENCY_WARN_WAKE_HTTP_MS = _env_float("CAMERA_LISTENER_LATENCY_WARN_WAKE_HTTP_MS", 900.0)
LATENCY_WARN_TURN_HTTP_MS = _env_float("CAMERA_LISTENER_LATENCY_WARN_TURN_HTTP_MS", 3500.0)
LATENCY_WARN_INTERRUPT_HTTP_MS = _env_float("CAMERA_LISTENER_LATENCY_WARN_INTERRUPT_HTTP_MS", 500.0)
ASSISTANT_ECHO_GUARD_SEC = _env_float("CAMERA_LISTENER_ASSISTANT_ECHO_GUARD_SEC", 5.0)
ECHO_SIMILARITY_THRESHOLD = _env_float("CAMERA_LISTENER_ECHO_SIMILARITY_THRESHOLD", 0.84)
MIN_WORDS_FORWARD = _env_int("CAMERA_LISTENER_MIN_WORDS_FORWARD", 2)
FILLER_WORDS = {
    w.strip().lower()
    for w in os.getenv(
        "CAMERA_LISTENER_FILLER_WORDS",
        "ja,nej,okej,ok,tack,hej,dag,mm,mhm",
    ).split(",")
    if w.strip()
}
DIRECTED_HINT_WORDS = {
    w.strip().lower()
    for w in os.getenv(
        "CAMERA_LISTENER_DIRECTED_HINT_WORDS",
        "codex,kan du,du,hjälp,hur,vad,varför,när,visa,berätta,påminn",
    ).split(",")
    if w.strip()
}
DIRECTED_MIN_SCORE = _env_float("CAMERA_LISTENER_DIRECTED_MIN_SCORE", 1.2)
WAKEWORD_ENGINE = os.getenv("CAMERA_LISTENER_WAKEWORD_ENGINE", "openwakeword").strip().lower()
OWW_MODEL_NAME = os.getenv("CAMERA_LISTENER_OWW_MODEL", "hey_jarvis").strip()
OWW_THRESHOLD = _env_float("CAMERA_LISTENER_OWW_THRESHOLD", 0.5)
OWW_PLAYBACK_THRESHOLD = _env_float("CAMERA_LISTENER_OWW_PLAYBACK_THRESHOLD", max(OWW_THRESHOLD, 0.75))
SILERO_VAD_THRESHOLD = _env_float("CAMERA_LISTENER_SILERO_VAD_THRESHOLD", 0.4)
BARGE_IN_ENABLED = _env_bool("CAMERA_LISTENER_BARGE_IN_ENABLED", True)
BARGE_IN_MIN_DBFS = _env_float("CAMERA_LISTENER_BARGE_IN_MIN_DBFS", -50.0)
BARGE_IN_IGNORE_SPEAKER_SEC = _env_float("CAMERA_LISTENER_BARGE_IN_IGNORE_SPEAKER_SEC", 4.0)
BARGE_IN_INTERRUPT_SPEAKER = _env_bool("CAMERA_LISTENER_BARGE_IN_INTERRUPT_SPEAKER", True)
WAKE_INTERRUPT_DURING_PLAYBACK = _env_bool("CAMERA_LISTENER_WAKE_INTERRUPT_DURING_PLAYBACK", False)
BARGE_IN_REQUIRE_ACTIVE_CONVERSATION = _env_bool(
    "CAMERA_LISTENER_BARGE_IN_REQUIRE_ACTIVE_CONVERSATION",
    False,
)
BARGE_IN_REQUIRE_INTERRUPT_PHRASE = _env_bool(
    "CAMERA_LISTENER_BARGE_IN_REQUIRE_INTERRUPT_PHRASE",
    True,
)
BARGE_IN_FREE_TURN_AFTER_WAKE_SEC = _env_float(
    "CAMERA_LISTENER_BARGE_IN_FREE_TURN_AFTER_WAKE_SEC",
    4.0,
)
HARD_IDLE_INTERRUPT_COOLDOWN_SEC = _env_float(
    "CAMERA_LISTENER_HARD_IDLE_INTERRUPT_COOLDOWN_SEC",
    0.8,
)
HARD_IDLE_ACK_GRACE_SEC = _env_float(
    "CAMERA_LISTENER_HARD_IDLE_ACK_GRACE_SEC",
    1.2,
)
INTERRUPT_PHRASES = [
    p.strip().lower()
    for p in os.getenv(
        "CAMERA_LISTENER_INTERRUPT_PHRASES",
        "stopp jarvis,stopp codex,stopp kodex,hej jarvis,hey jarvis,hej codex,hey codex",
    ).split(",")
    if p.strip()
]

FFMPEG_AUDIO_FILTER = os.getenv(
    "CAMERA_LISTENER_FFMPEG_AUDIO_FILTER",
    "highpass=f=100,lowpass=f=3700,volume=2.5",
).strip()
_debug_audio_raw = os.getenv("CAMERA_LISTENER_DEBUG_AUDIO_DIR", "").strip()
DEBUG_AUDIO_DIR = Path(_debug_audio_raw) if _debug_audio_raw else None
INITIAL_PROMPT = os.getenv(
    "CAMERA_LISTENER_INITIAL_PROMPT",
    "Hej, kan du hjälpa mig? Vad är klockan? Hur är vädret idag? Kan du berätta?",
).strip() or None

BYTES_PER_SAMPLE = 2
CHUNK_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_SEC)
VAD_FRAME_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * (VAD_FRAME_MS / 1000.0))
VAD_MIN_SPEECH_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * (VAD_MIN_SPEECH_MS / 1000.0))
VAD_MAX_SPEECH_BYTES = int(SAMPLE_RATE * BYTES_PER_SAMPLE * VAD_MAX_SPEECH_SEC)


def _ms_since(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000.0, 1)


def _warn_if_slow(stage: str, elapsed_ms: float, budget_ms: float) -> None:
    if budget_ms <= 0:
        return
    if elapsed_ms > budget_ms:
        logger.warning(
            "Latency budget exceeded: %s=%.1fms (budget=%.1fms)",
            stage,
            elapsed_ms,
            budget_ms,
        )


def _timeout_pair(read_timeout_sec: float) -> tuple[float, float]:
    connect_timeout = max(0.2, HTTP_CONNECT_TIMEOUT_SEC)
    return connect_timeout, max(connect_timeout, read_timeout_sec)


@dataclass
class ListenerState:
    active_conversation_id: str = ""
    active_until: float = 0.0
    last_wake_ts: float = 0.0
    last_sent_text: str = ""
    last_sent_ts: float = 0.0
    last_assistant_text: str = ""
    last_assistant_ts: float = 0.0
    assistant_guard_until: float = 0.0
    last_transcript: str = ""
    last_forwarded_text: str = ""
    last_forwarded_ts: float = 0.0
    ignore_speaker_until: float = 0.0
    wake_count: int = 0
    forwarded_count: int = 0
    ignored_count: int = 0
    worker_queue_size: int = 0
    last_stt_ms: float = 0.0
    last_barge_in_stt_ms: float = 0.0
    last_wake_http_ms: float = 0.0
    last_turn_http_ms: float = 0.0
    last_interrupt_http_ms: float = 0.0
    last_speaker_state_ms: float = 0.0
    hard_idle_mode: bool = False
    hard_idle_interrupt_after: float = 0.0
    last_hard_idle_interrupt_ts: float = 0.0

    def conversation_active(self, now_ts: float) -> bool:
        return bool(self.active_conversation_id) and now_ts < self.active_until


def _status_payload(state: ListenerState, phase: str, note: str = "") -> dict[str, Any]:
    now_ts = time.time()
    return {
        "ok": True,
        "service": "camera-listener",
        "phase": phase,
        "note": note,
        "enabled": ENABLED,
        "rtsp_url": RTSP_URL,
        "device_id": DEVICE_ID,
        "aihub_url": AIHUB_URL,
        "stt_model": STT_MODEL,
        "wakeword_engine": WAKEWORD_ENGINE,
        "oww_model": OWW_MODEL_NAME if WAKEWORD_ENGINE == "openwakeword" else "",
        "wake_stt_model": "openwakeword" if WAKEWORD_ENGINE == "openwakeword" else (WAKE_STT_MODEL if WAKE_ONLY_MODE else STT_MODEL),
        "wake_only_mode": WAKE_ONLY_MODE,
        "vad_mode": VAD_MODE,
        "stt_language": STT_LANGUAGE,
        "stt_beam_size": STT_BEAM_SIZE,
        "stt_best_of": STT_BEST_OF,
        "segment_min_avg_logprob": SEGMENT_MIN_AVG_LOGPROB,
        "segment_max_no_speech_prob": SEGMENT_MAX_NO_SPEECH_PROB,
        "wake_segment_min_avg_logprob": WAKE_SEGMENT_MIN_AVG_LOGPROB,
        "wake_segment_max_no_speech_prob": WAKE_SEGMENT_MAX_NO_SPEECH_PROB,
        "wake_phrases": WAKE_PHRASES,
        "wake_aliases": WAKE_ALIASES,
        "stop_phrases": STOP_PHRASES,
        "idle_phrases": IDLE_PHRASES,
        "correction_prefixes": CORRECTION_PREFIXES,
        "active_conversation_id": state.active_conversation_id,
        "conversation_active": state.conversation_active(now_ts),
        "conversation_seconds_left": max(0.0, round(state.active_until - now_ts, 2))
        if state.active_conversation_id
        else 0.0,
        "assistant_guard_seconds_left": max(0.0, round(state.assistant_guard_until - now_ts, 2)),
        "ignore_speaker_seconds_left": max(0.0, round(state.ignore_speaker_until - now_ts, 2)),
        "hard_idle_mode": state.hard_idle_mode,
        "hard_idle_interrupt_after_seconds_left": max(
            0.0, round(state.hard_idle_interrupt_after - now_ts, 2),
        ),
        "last_transcript": state.last_transcript,
        "last_forwarded_text": state.last_forwarded_text,
        "wake_count": state.wake_count,
        "forwarded_count": state.forwarded_count,
        "ignored_count": state.ignored_count,
        "worker_queue_size": state.worker_queue_size,
        "latency_ms": {
            "stt_last": state.last_stt_ms,
            "barge_in_stt_last": state.last_barge_in_stt_ms,
            "speaker_state_last": state.last_speaker_state_ms,
            "wake_http_last": state.last_wake_http_ms,
            "turn_http_last": state.last_turn_http_ms,
            "interrupt_http_last": state.last_interrupt_http_ms,
        },
        "updated_at_epoch": round(now_ts, 3),
    }


def _write_status(state: ListenerState, phase: str, note: str = "") -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _status_payload(state, phase, note)
    tmp_path = STATUS_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(STATUS_PATH)


def _normalize_text(text: str) -> str:
    cleaned = text.strip().lower()
    for c in ",.;:!?()[]{}\"'":
        cleaned = cleaned.replace(c, " ")
    return " ".join(cleaned.split())


def _extract_wake_phrase(text: str) -> tuple[bool, str, str]:
    cleaned = _normalize_text(text)
    for alias in WAKE_ALIASES:
        if cleaned == alias:
            return True, WAKE_CANONICAL, ""
        prefix = f"{alias} "
        if cleaned.startswith(prefix):
            remainder = cleaned[len(prefix) :].strip()
            return True, WAKE_CANONICAL, remainder

    # Token heuristic: "hej/hey" + word that starts with cod/kod.
    tokens = cleaned.split()
    if tokens and tokens[0] in {"hej", "hey"}:
        if len(tokens) >= 2:
            t1 = tokens[1]
            sim_codex = SequenceMatcher(None, t1, "codex").ratio()
            sim_kodex = SequenceMatcher(None, t1, "kodex").ratio()
            if max(sim_codex, sim_kodex) >= WAKE_SECOND_TOKEN_MIN_SIM:
                remainder = " ".join(tokens[2:]).strip()
                return True, WAKE_CANONICAL, remainder

        match_idx = -1
        for i, tok in enumerate(tokens[1:4], start=1):
            if tok.startswith(("cod", "kod", "cord", "kord", "cort", "kort")):
                match_idx = i
                break
        if match_idx >= 1:
            remainder = " ".join(tokens[match_idx + 1 :]).strip()
            return True, WAKE_CANONICAL, remainder

    if WAKE_ALLOW_FUZZY_MATCH:
        # Fuzzy fallback for common STT misspellings.
        head = " ".join(cleaned.split()[:3])
        for alias in WAKE_ALIASES:
            if SequenceMatcher(None, head, alias).ratio() >= 0.86:
                remainder = cleaned[len(head) :].strip() if len(cleaned) > len(head) else ""
                return True, WAKE_CANONICAL, remainder

    return False, "", text.strip()


def _is_stop_phrase(text: str) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return False
    for p in STOP_PHRASES:
        if cleaned == p:
            return True
        if cleaned.startswith(f"{p} "):
            return True
    return False


def _is_idle_phrase(text: str) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return False
    if _is_stop_phrase(cleaned):
        return True
    for p in IDLE_PHRASES:
        p_norm = _normalize_text(p)
        if not p_norm:
            continue
        if cleaned == p_norm:
            return True
        if cleaned.startswith(f"{p_norm} "):
            return True
    return False


def _extract_correction_text(text: str) -> tuple[bool, str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return False, ""
    for prefix in CORRECTION_PREFIXES:
        pref = _normalize_text(prefix)
        if not pref:
            continue
        match = re.search(rf"(^|\s){re.escape(pref)}(\s|$)", cleaned)
        if not match:
            continue
        remainder = cleaned[match.end() :].strip()
        return True, remainder
    return False, ""


def _is_interrupt_phrase(text: str) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return False
    if _is_idle_phrase(cleaned):
        return True
    correction_hit, _ = _extract_correction_text(cleaned)
    if correction_hit:
        return True
    wake_hit, _, _ = _extract_wake_phrase(cleaned)
    if wake_hit:
        return True
    # Allow camera-directed corrections during playback without forcing wake phrase.
    if re.search(
        r"\b(följ mig|folj mig|spåra mig|spara mig|kolla .*på mig|kollar .*på mig|titta .*på mig|tittar .*på mig|vad ser du|vad har jag på mig)\b",
        cleaned,
    ):
        return True
    for p in INTERRUPT_PHRASES:
        p_norm = _normalize_text(p)
        if not p_norm:
            continue
        if re.search(rf"(^|\s){re.escape(p_norm)}(\s|$)", cleaned):
            return True
    return False


def _set_conversation_inactive(state: ListenerState) -> None:
    state.active_conversation_id = ""
    state.active_until = 0.0


def _enter_hard_idle(
    state: ListenerState,
    worker: "ResponseWorker",
    *,
    reason: str,
    ack_text: str = "",
) -> None:
    _set_conversation_inactive(state)
    state.hard_idle_mode = True
    state.last_assistant_text = ""
    state.assistant_guard_until = 0.0
    state.ignore_speaker_until = 0.0
    dropped = worker.preempt_pending()
    ok_interrupt, reason_interrupt = worker.client.interrupt_speaker(reason)
    state.last_interrupt_http_ms = worker.client.last_interrupt_http_ms
    worker.client._speaker_cache = (time.time(), False)
    grace_sec = HARD_IDLE_ACK_GRACE_SEC if ack_text else 0.0
    state.hard_idle_interrupt_after = time.time() + max(0.0, grace_sec)
    state.last_hard_idle_interrupt_ts = 0.0
    if ack_text:
        worker.submit_announce(ack_text, event="reply")
    logger.info(
        "Hard idle activated: dropped=%d interrupt_ok=%s reason=%s",
        dropped,
        ok_interrupt,
        reason_interrupt,
    )


def _word_count(text: str) -> int:
    return len(_normalize_text(text).split())


def _is_filler_text(text: str) -> bool:
    cleaned = _normalize_text(text)
    return cleaned in FILLER_WORDS


_KNOWN_HALLUCINATIONS = [
    "tack så mycket",
    "tack till elever och personal vid värmlands",
    "tack till elever och personal",
    "tack för att ni tittade",
    "tack för att du tittade",
    "tack för att ni lyssnade",
    "tack för att du lyssnade",
    "varsågod",
    "textning nu",
    "textning stina hedin",
    "undertextad av",
    "undertexter av",
    "textat av",
    "textning av",
    "copyright",
    "www",
]


def _looks_like_hallucination(text: str) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return True
    # Check known Whisper hallucination patterns.
    for pattern in _KNOWN_HALLUCINATIONS:
        if pattern in cleaned:
            return True
    tokens = cleaned.split()
    if len(tokens) >= 20:
        uniq_ratio = len(set(tokens)) / max(1, len(tokens))
        if uniq_ratio < 0.35:
            return True
        joined = " ".join(tokens)
        for n in range(4, 9):
            if len(tokens) < n * 3:
                continue
            chunk = " ".join(tokens[:n])
            if chunk and joined.count(chunk) >= 3:
                return True
    letters = len(re.sub(r"[^a-zA-ZåäöÅÄÖ]", "", cleaned))
    if letters <= 1:
        return True
    return False


def _directed_score(state: ListenerState, text: str, now_ts: float) -> float:
    cleaned = _normalize_text(text)
    if not cleaned:
        return 0.0
    score = 0.0

    if any(h in cleaned for h in DIRECTED_HINT_WORDS):
        score += 1.1

    if _word_count(cleaned) >= 4:
        score += 0.35

    # Strong weight if semantically close to recent assistant turn.
    if state.last_assistant_text:
        sim = SequenceMatcher(None, cleaned, _normalize_text(state.last_assistant_text)).ratio()
        if sim >= 0.45:
            score += 0.8
        elif sim >= 0.30:
            score += 0.4

    # If user speaks soon after assistant reply, likely still directed.
    time_since = now_ts - state.last_assistant_ts if state.last_assistant_ts > 0 else -1
    if state.last_assistant_ts > 0 and time_since <= 12:
        score += 0.35

    # Penalize obvious fillers.
    if _is_filler_text(cleaned):
        score -= 0.8

    logger.debug(
        "directed_score: words=%d hint=%s asst_ts=%.1f time_since=%.1f conv_active=%s score=%.2f text=%s",
        _word_count(cleaned),
        any(h in cleaned for h in DIRECTED_HINT_WORDS),
        state.last_assistant_ts,
        time_since,
        state.conversation_active(now_ts),
        score,
        cleaned,
    )
    return score


def _looks_like_assistant_echo(
    state: ListenerState,
    text: str,
    now_ts: float,
    *,
    ignore_time_guard: bool = False,
) -> bool:
    if not ignore_time_guard and now_ts < state.assistant_guard_until:
        return True
    if not state.last_assistant_text:
        return False
    a = _normalize_text(text)
    b = _normalize_text(state.last_assistant_text)
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= ECHO_SIMILARITY_THRESHOLD


class AIHubClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.headers = {"Content-Type": "application/json"}
        if AIHUB_TOKEN:
            self.headers["Authorization"] = f"Bearer {AIHUB_TOKEN}"
        self._speaker_cache: tuple[float, bool] = (0.0, False)
        self._speaker_cache_ttl = 0.5  # 500ms cache
        self.last_speaker_state_ms = 0.0
        self.last_wake_http_ms = 0.0
        self.last_turn_http_ms = 0.0
        self.last_interrupt_http_ms = 0.0

    def speaker_playing(self) -> bool:
        """Check if the camera speaker is currently playing TTS (cached 500ms)."""
        now = time.time()
        if now - self._speaker_cache[0] < self._speaker_cache_ttl:
            return self._speaker_cache[1]
        started = time.monotonic()
        try:
            resp = self.session.get(
                f"{AIHUB_URL}/v1/speaker/state",
                headers=self.headers,
                timeout=_timeout_pair(SPEAKER_STATE_TIMEOUT_SEC),
            )
            resp.raise_for_status()
            playing = bool(resp.json().get("speaker_playing", False))
        except Exception:
            playing = False
        self.last_speaker_state_ms = _ms_since(started)
        _warn_if_slow(
            "speaker_state_http",
            self.last_speaker_state_ms,
            LATENCY_WARN_SPEAKER_STATE_MS,
        )
        self._speaker_cache = (now, playing)
        return playing

    def wake(self, wake_phrase: str) -> tuple[bool, dict[str, Any]]:
        url = f"{AIHUB_URL}/v1/events/audio/wake"
        payload = {"device": DEVICE_ID, "wake_phrase": wake_phrase}
        started = time.monotonic()
        try:
            resp = self.session.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=_timeout_pair(WAKE_TIMEOUT_SEC),
            )
            resp.raise_for_status()
            self.last_wake_http_ms = _ms_since(started)
            _warn_if_slow("wake_http", self.last_wake_http_ms, LATENCY_WARN_WAKE_HTTP_MS)
            return True, resp.json()
        except Exception as exc:  # pragma: no cover
            self.last_wake_http_ms = _ms_since(started)
            _warn_if_slow("wake_http", self.last_wake_http_ms, LATENCY_WARN_WAKE_HTTP_MS)
            return False, {"error": f"wake_failed:{type(exc).__name__}"}

    def turn(
        self,
        conversation_id: str,
        text: str,
        timestamp: str | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        url = f"{AIHUB_URL}/v1/conversation/turn"
        payload = {
            "conversation_id": conversation_id,
            "source": "audio",
            "text": text,
            "allow_codex": ALLOW_CODEX,
        }
        if timestamp:
            payload["timestamp"] = timestamp
        started = time.monotonic()
        try:
            resp = self.session.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=_timeout_pair(TURN_TIMEOUT_SEC),
            )
            resp.raise_for_status()
            self.last_turn_http_ms = _ms_since(started)
            _warn_if_slow("turn_http", self.last_turn_http_ms, LATENCY_WARN_TURN_HTTP_MS)
            return True, resp.json()
        except Exception as exc:  # pragma: no cover
            self.last_turn_http_ms = _ms_since(started)
            _warn_if_slow("turn_http", self.last_turn_http_ms, LATENCY_WARN_TURN_HTTP_MS)
            return False, {"error": f"turn_failed:{type(exc).__name__}"}

    def interrupt_speaker(self, reason: str = "barge_in") -> tuple[bool, str]:
        url = f"{AIHUB_URL}/v1/speaker/interrupt"
        payload = {"reason": reason}
        started = time.monotonic()
        try:
            resp = self.session.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=_timeout_pair(INTERRUPT_TIMEOUT_SEC),
            )
            resp.raise_for_status()
            self._speaker_cache = (time.time(), False)
            self.last_interrupt_http_ms = _ms_since(started)
            _warn_if_slow(
                "interrupt_http",
                self.last_interrupt_http_ms,
                LATENCY_WARN_INTERRUPT_HTTP_MS,
            )
            return True, "ok"
        except Exception as exc:  # pragma: no cover
            self.last_interrupt_http_ms = _ms_since(started)
            _warn_if_slow(
                "interrupt_http",
                self.last_interrupt_http_ms,
                LATENCY_WARN_INTERRUPT_HTTP_MS,
            )
            return False, f"interrupt_failed:{type(exc).__name__}"

    def announce(self, text: str, *, event: str = "reply") -> tuple[bool, str]:
        url = f"{AIHUB_URL}/v1/speaker/announce"
        payload = {
            "text": text,
            "source": "audio",
            "event": event,
        }
        try:
            resp = self.session.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=_timeout_pair(ANNOUNCE_TIMEOUT_SEC),
            )
            resp.raise_for_status()
            data = resp.json()
            return bool(data.get("ok", False)), str(data.get("reason", "ok"))
        except Exception as exc:  # pragma: no cover
            return False, f"announce_failed:{type(exc).__name__}"


class ResponseWorker:
    """Background thread that handles aihub HTTP calls without blocking the audio loop."""

    def __init__(self, client: AIHubClient, state: ListenerState) -> None:
        self.client = client
        self.state = state
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=20)
        self._enqueue_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _sync_client_latency(self) -> None:
        self.state.last_speaker_state_ms = self.client.last_speaker_state_ms
        self.state.last_wake_http_ms = self.client.last_wake_http_ms
        self.state.last_turn_http_ms = self.client.last_turn_http_ms
        self.state.last_interrupt_http_ms = self.client.last_interrupt_http_ms

    def _update_queue_size(self) -> None:
        self.state.worker_queue_size = self._queue.qsize()

    def _run(self) -> None:
        while True:
            try:
                action, payload = self._queue.get()
                self._update_queue_size()
                if action == "wake":
                    self._do_wake(**payload)
                elif action == "turn":
                    self._do_turn(**payload)
                elif action == "announce":
                    self._do_announce(**payload)
            except Exception as exc:
                logger.warning("ResponseWorker error: %s", exc)
            finally:
                self._queue.task_done()
                self._update_queue_size()

    def submit_wake(self, wake_phrase: str, initial_text: str = "") -> None:
        now_ts = time.time()
        if now_ts - self.state.last_wake_ts < WAKE_COOLDOWN_SEC:
            self.state.ignored_count += 1
            return
        # Immediately mark conversation active so main loop switches to STT.
        self.state.active_conversation_id = "pending"
        self.state.active_until = now_ts + CONVERSATION_TTL_SEC
        self.state.hard_idle_mode = False
        self.state.hard_idle_interrupt_after = 0.0
        self.state.last_hard_idle_interrupt_ts = 0.0
        self.state.last_wake_ts = now_ts
        self.state.wake_count += 1
        try:
            self._queue.put_nowait(("wake", {"wake_phrase": wake_phrase, "initial_text": initial_text}))
            self._update_queue_size()
        except queue.Full:
            logger.warning("Response queue full, dropping wake")
            _set_conversation_inactive(self.state)

    def submit_turn(self, text: str, captured_at: str | None = None) -> None:
        now_ts = time.time()
        self.state.last_transcript = text
        self.state.last_sent_text = text
        self.state.last_sent_ts = now_ts
        sent_ts = captured_at or datetime.now(timezone.utc).isoformat()
        with self._enqueue_lock:
            dropped = 0
            kept: list[tuple[str, dict[str, Any]]] = []
            while True:
                try:
                    action, payload = self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
                if action == "turn":
                    dropped += 1
                    continue
                kept.append((action, payload))
            for item in kept:
                try:
                    self._queue.put_nowait(item)
                except queue.Full:
                    logger.warning("Response queue full while restoring non-turn item")
                    break
            if dropped:
                logger.info("Dropped %d queued turn(s) (latest-turn-wins)", dropped)
            try:
                self._queue.put_nowait(("turn", {"text": text, "captured_at": sent_ts}))
            except queue.Full:
                logger.warning("Response queue full, dropping latest turn")
            self._update_queue_size()

    def submit_announce(self, text: str, *, event: str = "reply") -> None:
        if not text.strip():
            return
        try:
            self._queue.put_nowait(("announce", {"text": text.strip(), "event": event}))
        except queue.Full:
            logger.warning("Response queue full, dropping announce")
        self._update_queue_size()

    def preempt_pending(self) -> int:
        """Drop queued wake/turn/announce actions so barge-in is handled first."""
        dropped = 0
        with self._enqueue_lock:
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                    dropped += 1
                except queue.Empty:
                    break
            self._update_queue_size()
        return dropped

    def _do_wake(self, wake_phrase: str, initial_text: str = "") -> None:
        state = self.state
        ok, wake_resp = self.client.wake(wake_phrase)
        self._sync_client_latency()
        if not ok:
            logger.warning("Wake trigger failed: %s", wake_resp.get("error", "unknown"))
            _set_conversation_inactive(state)
            state.ignored_count += 1
            return

        conversation_id = str(wake_resp.get("conversation_id", "")).strip()
        ttl = float(wake_resp.get("ttl_seconds", CONVERSATION_TTL_SEC))
        if not conversation_id:
            logger.warning("Wake response missing conversation_id")
            _set_conversation_inactive(state)
            state.ignored_count += 1
            return

        now_ts = time.time()
        state.active_conversation_id = conversation_id
        state.active_until = now_ts + ttl

        text_to_send = initial_text if initial_text else wake_phrase
        if _should_drop_duplicate(state, text_to_send, now_ts):
            return

        ok_turn, turn_resp = self.client.turn(
            conversation_id,
            text_to_send,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._sync_client_latency()
        if ok_turn:
            now_ts = time.time()
            state.forwarded_count += 1
            state.last_forwarded_text = text_to_send
            state.last_forwarded_ts = now_ts
            state.last_sent_text = text_to_send
            state.last_sent_ts = now_ts
            assistant_text = str(turn_resp.get("assistant_text", "")).strip()
            if assistant_text:
                state.last_assistant_text = assistant_text
                state.last_assistant_ts = now_ts
                state.assistant_guard_until = now_ts + ASSISTANT_ECHO_GUARD_SEC
                logger.info("Wake handled -> %s", assistant_text)
        else:
            logger.warning("Turn failed after wake: %s", turn_resp.get("error", "unknown"))

    def _do_turn(self, text: str, captured_at: str | None = None) -> None:
        state = self.state
        now_ts = time.time()
        if not state.conversation_active(now_ts):
            return
        conv_id = state.active_conversation_id
        if not conv_id or conv_id == "pending":
            logger.debug("Turn waiting for wake to complete")
            for _ in range(100):
                time.sleep(0.1)
                conv_id = state.active_conversation_id
                if conv_id and conv_id != "pending":
                    break
            if not conv_id or conv_id == "pending":
                logger.warning("Turn dropped: wake never completed")
                return

        ok_turn, turn_resp = self.client.turn(conv_id, text, timestamp=captured_at)
        self._sync_client_latency()
        if ok_turn:
            now_ts = time.time()
            state.forwarded_count += 1
            state.last_forwarded_text = text
            state.last_forwarded_ts = now_ts
            state.active_until = now_ts + CONVERSATION_TTL_SEC
            assistant_text = str(turn_resp.get("assistant_text", "")).strip()
            if assistant_text:
                state.last_assistant_text = assistant_text
                state.last_assistant_ts = now_ts
                state.assistant_guard_until = now_ts + ASSISTANT_ECHO_GUARD_SEC
                logger.info("Assistant -> %s", assistant_text)
        else:
            logger.warning("Turn failed: %s", turn_resp.get("error", "unknown"))

    def _do_announce(self, text: str, event: str = "reply") -> None:
        ok, reason = self.client.announce(text, event=event)
        if not ok:
            logger.debug("Announce failed: %s", reason)


def _load_model(model_name: str, device: str, compute_type: str, language: str, label: str) -> WhisperModel:
    logger.info(
        "Loading %s model=%s device=%s compute_type=%s language=%s",
        label,
        model_name,
        device,
        compute_type,
        language,
    )
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=MODEL_DIR,
    )
    logger.info("%s model loaded", label)
    return model


_silero_vad_ready = False


def _load_silero_vad() -> None:
    """Pre-load Silero VAD ONNX model (cached via get_vad_model)."""
    global _silero_vad_ready
    try:
        from faster_whisper.vad import get_vad_model

        get_vad_model()  # lru_cached — loads once
        _silero_vad_ready = True
        logger.info("Silero VAD speech gate loaded (threshold=%.2f)", SILERO_VAD_THRESHOLD)
    except Exception as exc:
        logger.warning("Failed to load Silero VAD: %s (speech gate disabled)", exc)


def _contains_speech(pcm_s16le: bytes) -> bool:
    """Neural speech gate: returns True only if audio contains human speech.

    Uses Silero VAD (ONNX) to distinguish real speech from keyboard clicks,
    ambient noise, and other non-speech sounds. Runs in ~2ms per segment.
    """
    if not _silero_vad_ready:
        return True  # fallback: assume speech if model not loaded
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        audio = np.frombuffer(pcm_s16le, dtype=np.int16).astype(np.float32) / 32768.0
        opts = VadOptions(
            threshold=SILERO_VAD_THRESHOLD,
            min_speech_duration_ms=150,
            min_silence_duration_ms=100,
        )
        timestamps = get_speech_timestamps(audio, vad_options=opts)
        has_speech = len(timestamps) > 0
        if not has_speech and DEBUG_TRANSCRIPTS:
            logger.debug("Silero VAD: no speech detected, skipping Whisper")
        return has_speech
    except Exception as exc:
        logger.debug("Silero VAD check failed: %s", exc)
        return True  # fallback on error


def _save_debug_audio(wav_path: str, transcript: str) -> None:
    """Copy a WAV segment to the debug audio directory for manual inspection."""
    if not DEBUG_AUDIO_DIR:
        return
    try:
        debug_dir = Path(DEBUG_AUDIO_DIR)
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%H%M%S")
        safe_text = re.sub(r"[^a-zA-ZåäöÅÄÖ0-9 ]", "", transcript)[:40].strip().replace(" ", "_")
        dest = debug_dir / f"{ts}_{safe_text}.wav"
        import shutil
        shutil.copy2(wav_path, str(dest))
        logger.info("Debug audio saved: %s", dest.name)
    except Exception as exc:
        logger.debug("Failed to save debug audio: %s", exc)


def _transcribe_chunk(
    model: WhisperModel,
    pcm_s16le: bytes,
    *,
    language: str,
    beam_size: int,
    best_of: int,
    no_speech_threshold: float,
    log_prob_threshold: float,
    segment_min_avg_logprob: float,
    segment_max_no_speech_prob: float,
) -> str:
    if not pcm_s16le:
        return ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(BYTES_PER_SAMPLE)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm_s16le)
        segments, _ = model.transcribe(
            tmp_path,
            language=language or None,
            vad_filter=False,
            beam_size=beam_size,
            best_of=best_of,
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=no_speech_threshold,
            log_prob_threshold=log_prob_threshold,
            initial_prompt=INITIAL_PROMPT,
        )
        parts: list[str] = []
        for seg in segments:
            seg_text = str(getattr(seg, "text", "")).strip()
            if not seg_text:
                continue
            seg_avg_logprob = float(getattr(seg, "avg_logprob", -10.0))
            seg_no_speech_prob = float(getattr(seg, "no_speech_prob", 1.0))
            if seg_avg_logprob < segment_min_avg_logprob:
                if DEBUG_TRANSCRIPTS:
                    logger.info(
                        "Drop low-confidence segment avg_logprob=%.2f text=%s",
                        seg_avg_logprob,
                        seg_text,
                    )
                continue
            if seg_no_speech_prob > segment_max_no_speech_prob:
                if DEBUG_TRANSCRIPTS:
                    logger.info(
                        "Drop no-speech segment no_speech_prob=%.2f text=%s",
                        seg_no_speech_prob,
                        seg_text,
                    )
                continue
            parts.append(seg_text)
        result = _normalize_text(" ".join(parts))
        if result and DEBUG_AUDIO_DIR:
            _save_debug_audio(tmp_path, result)
        return result
    except Exception as exc:  # pragma: no cover
        logger.warning("STT failed: %s", type(exc).__name__)
        return ""
    finally:
        if tmp_path and not DEBUG_AUDIO_DIR:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _transcribe_google(pcm_s16le: bytes, *, language: str) -> str:
    """Transcribe audio using Google Web Speech API (free, no key)."""
    if not pcm_s16le:
        return ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(BYTES_PER_SAMPLE)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm_s16le)
        recognizer = sr.Recognizer()
        with sr.AudioFile(tmp_path) as source:
            audio = recognizer.record(source)
        lang_code = language if "-" in language else f"{language}-SE" if language == "sv" else language
        text = recognizer.recognize_google(audio, language=lang_code)
        result = _normalize_text(text)
        if result and DEBUG_AUDIO_DIR:
            _save_debug_audio(tmp_path, result)
        return result
    except sr.UnknownValueError:
        logger.debug("Google STT: no speech detected")
        return ""
    except sr.RequestError as exc:
        logger.warning("Google STT request failed: %s", exc)
        return ""
    except Exception as exc:
        logger.warning("Google STT failed: %s", type(exc).__name__)
        return ""
    finally:
        if tmp_path and not DEBUG_AUDIO_DIR:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _should_drop_duplicate(state: ListenerState, text: str, now_ts: float) -> bool:
    if not state.last_sent_text:
        return False
    if text != state.last_sent_text:
        return False
    return (now_ts - state.last_sent_ts) < DUPLICATE_WINDOW_SEC


def _open_audio_pipe() -> subprocess.Popen[bytes]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-rtsp_transport",
        "tcp",
        "-i",
        RTSP_URL,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-af",
        FFMPEG_AUDIO_FILTER,
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "pipe:1",
    ]
    logger.info("Opening camera audio stream")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)


class AudioReader:
    """Background thread that continuously drains ffmpeg stdout into a deque.

    This prevents the pipe buffer from filling up during slow Whisper processing,
    which would cause ffmpeg to block and the RTSP connection to die.
    """

    def __init__(self, stream, chunk_size: int = 4096, max_chunks: int = 200) -> None:
        self._stream = stream
        self._chunk_size = chunk_size
        self._buf: collections.deque[bytes] = collections.deque(maxlen=max_chunks)
        self._stopped = False
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        try:
            while not self._stopped:
                data = self._stream.read(self._chunk_size)
                if not data:
                    break
                self._buf.append(data)
        except Exception:
            pass

    def read(self, timeout: float = 5.0) -> bytes:
        """Return the next chunk, blocking up to timeout seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._buf:
                return self._buf.popleft()
            time.sleep(0.01)
        return b""

    def stop(self) -> None:
        self._stopped = True


def _pcm_dbfs(pcm_s16le: bytes) -> float:
    if not pcm_s16le:
        return -120.0
    rms = audioop.rms(pcm_s16le, BYTES_PER_SAMPLE)
    if rms <= 0:
        return -120.0
    return 20.0 * math.log10(rms / 32768.0)


class SpeechSegmenter:
    def __init__(self) -> None:
        self.vad = webrtcvad.Vad(max(0, min(3, VAD_MODE)))
        self.buf = bytearray()
        self.preroll: list[bytes] = []
        self.active = False
        self.start_count = 0
        self.end_count = 0
        self.segment = bytearray()

    def _is_speech(self, frame: bytes) -> bool:
        try:
            return self.vad.is_speech(frame, SAMPLE_RATE)
        except Exception:
            return False

    def _append_preroll(self) -> None:
        if not self.preroll:
            return
        for fr in self.preroll:
            self.segment.extend(fr)
        self.preroll.clear()

    def _finalize(self) -> bytes | None:
        if not self.segment:
            return None
        out = bytes(self.segment)
        self.segment.clear()
        self.active = False
        self.start_count = 0
        self.end_count = 0
        if len(out) < VAD_MIN_SPEECH_BYTES:
            return None
        return out

    def feed(self, pcm: bytes) -> list[bytes]:
        self.buf.extend(pcm)
        out: list[bytes] = []
        while len(self.buf) >= VAD_FRAME_BYTES:
            frame = bytes(self.buf[:VAD_FRAME_BYTES])
            del self.buf[:VAD_FRAME_BYTES]

            speech = self._is_speech(frame)
            if not self.active:
                self.preroll.append(frame)
                if len(self.preroll) > max(1, VAD_PREROLL_FRAMES):
                    self.preroll.pop(0)
                if speech:
                    self.start_count += 1
                else:
                    self.start_count = 0
                if self.start_count >= max(1, VAD_START_FRAMES):
                    self.active = True
                    self.end_count = 0
                    self._append_preroll()
                continue

            self.segment.extend(frame)
            if speech:
                self.end_count = 0
            else:
                self.end_count += 1

            if len(self.segment) >= VAD_MAX_SPEECH_BYTES:
                seg = self._finalize()
                if seg:
                    out.append(seg)
                continue

            if self.end_count >= max(1, VAD_END_FRAMES):
                seg = self._finalize()
                if seg:
                    out.append(seg)

        return out


class WakeWordDetector:
    """Lightweight openwakeword-based wake word detector.

    Buffers raw PCM s16le and feeds 1280-sample (80ms @ 16kHz) chunks to the
    openwakeword model. Returns True from feed() when the detection score
    exceeds the configured threshold.
    """

    OWW_CHUNK_SAMPLES = 1280  # 80ms at 16kHz — required by openwakeword

    def __init__(self, model_name: str, threshold: float) -> None:
        if not OWW_AVAILABLE:
            raise RuntimeError("openwakeword is not installed")
        self.model_name = model_name
        self.threshold = threshold
        self.buf = bytearray()
        logger.info(
            "Loading openwakeword model=%s threshold=%.2f",
            model_name,
            threshold,
        )
        # Download built-in models if not already present.
        oww_download_models()
        self.model = OWWModel(wakeword_models=[model_name], inference_framework="onnx")
        # Discover the actual key the model uses for scores.
        self._score_key = model_name
        for key in self.model.prediction_buffer.keys():
            if model_name.replace("-", "_") in key.replace("-", "_"):
                self._score_key = key
                break
        logger.info(
            "WakeWordDetector loaded (score_key=%s)", self._score_key,
        )

    def feed(self, pcm_s16le: bytes, *, threshold: float | None = None) -> bool:
        """Feed raw PCM bytes. Returns True once when wake word is detected."""
        self.buf.extend(pcm_s16le)
        chunk_bytes = self.OWW_CHUNK_SAMPLES * BYTES_PER_SAMPLE
        triggered = False
        max_score = 0.0
        threshold_to_use = self.threshold if threshold is None else threshold
        while len(self.buf) >= chunk_bytes:
            raw = bytes(self.buf[:chunk_bytes])
            del self.buf[:chunk_bytes]
            # Convert s16le bytes to int16 numpy array.
            samples = np.frombuffer(raw, dtype=np.int16)
            self.model.predict(samples)
            score = self.model.prediction_buffer.get(self._score_key, [0])[-1]
            if score > max_score:
                max_score = score
            if score >= threshold_to_use:
                triggered = True
        if DEBUG_TRANSCRIPTS and max_score > 0.01:
            logger.info("OWW score=%.3f (threshold=%.2f)", max_score, threshold_to_use)
        return triggered

    def reset(self) -> None:
        """Clear internal state after a detection to avoid re-triggers."""
        self.buf.clear()
        self.model.reset()


def _handle_transcript(
    state: ListenerState,
    worker: ResponseWorker,
    text: str,
    *,
    ignore_echo_time_guard: bool = False,
) -> None:
    """Filter and dispatch transcript to background worker (non-blocking)."""
    if not text or len(text) < MIN_TEXT_LEN:
        return

    now_ts = time.time()
    wake_hit, wake_phrase, remainder = _extract_wake_phrase(text)

    if wake_hit:
        state.hard_idle_mode = False
        state.hard_idle_interrupt_after = 0.0
        state.last_hard_idle_interrupt_ts = 0.0
        initial = text if remainder else ""
        worker.submit_wake(wake_phrase, initial_text=initial)
        return

    if _is_idle_phrase(text):
        _enter_hard_idle(
            state,
            worker,
            reason="idle_phrase",
            ack_text=IDLE_ACK_TEXT or STOP_ACK_TEXT,
        )
        state.ignored_count += 1
        logger.info("Conversation set to hard idle by idle phrase")
        return

    correction_hit, correction_text = _extract_correction_text(text)
    if correction_hit and state.conversation_active(now_ts):
        if correction_text:
            logger.info("Correction -> %s", correction_text)
            worker.submit_turn(
                correction_text,
                captured_at=datetime.now(timezone.utc).isoformat(),
            )
            return
        state.ignored_count += 1
        if CORRECTION_ACK_TEXT:
            worker.submit_announce(CORRECTION_ACK_TEXT, event="reply")
        logger.info("Correction prefix without content")
        return

    if not state.conversation_active(now_ts):
        state.ignored_count += 1
        logger.debug("Filter: no active conversation")
        return

    if _looks_like_hallucination(text):
        state.ignored_count += 1
        logger.info("Filter: hallucination -> %s", text)
        return

    if now_ts - state.last_sent_ts < MIN_TURN_INTERVAL_SEC:
        state.ignored_count += 1
        logger.info("Filter: rate limit (%.1fs < %.1fs)", now_ts - state.last_sent_ts, MIN_TURN_INTERVAL_SEC)
        return
    if _should_drop_duplicate(state, text, now_ts):
        state.ignored_count += 1
        logger.info("Filter: duplicate -> %s", text)
        return
    if _looks_like_assistant_echo(state, text, now_ts, ignore_time_guard=ignore_echo_time_guard):
        state.ignored_count += 1
        logger.info("Filter: echo guard -> %s", text)
        return
    if _word_count(text) < MIN_WORDS_FORWARD:
        state.ignored_count += 1
        logger.info("Filter: too few words (%d) -> %s", _word_count(text), text)
        return
    if _is_filler_text(text):
        state.ignored_count += 1
        logger.info("Filter: filler -> %s", text)
        return
    if not state.conversation_active(now_ts):
        dscore = _directed_score(state, text, now_ts)
        if dscore < DIRECTED_MIN_SCORE:
            state.ignored_count += 1
            logger.info("Filter: directed score %.2f < %.2f -> %s", dscore, DIRECTED_MIN_SCORE, text)
            return

    logger.info("Dispatching to worker: %s", text)
    worker.submit_turn(text, captured_at=datetime.now(timezone.utc).isoformat())


def run() -> None:
    state = ListenerState()
    _write_status(state, "starting")
    if not ENABLED:
        logger.info("Listener disabled (CAMERA_LISTENER_ENABLED=0)")
        while True:
            _write_status(state, "disabled")
            time.sleep(10)

    # --- Decide wakeword engine ---
    use_oww = (
        WAKEWORD_ENGINE == "openwakeword"
        and WAKE_ONLY_MODE
        and OWW_AVAILABLE
    )
    oww_detector: WakeWordDetector | None = None
    if use_oww:
        try:
            oww_detector = WakeWordDetector(OWW_MODEL_NAME, OWW_THRESHOLD)
        except Exception as exc:
            logger.warning("Failed to load openwakeword, falling back to whisper: %s", exc)
            use_oww = False

    if not use_oww and WAKEWORD_ENGINE == "openwakeword":
        logger.warning(
            "openwakeword requested but unavailable (OWW_AVAILABLE=%s); falling back to whisper wake",
            OWW_AVAILABLE,
        )

    _load_silero_vad()

    conversation_model = _load_model(STT_MODEL, STT_DEVICE, STT_COMPUTE_TYPE, STT_LANGUAGE, "conversation STT")

    # Only load a separate wake STT model when NOT using openwakeword.
    wake_model = conversation_model
    if not use_oww and WAKE_ONLY_MODE and (
        WAKE_STT_MODEL != STT_MODEL
        or WAKE_STT_DEVICE != STT_DEVICE
        or WAKE_STT_COMPUTE_TYPE != STT_COMPUTE_TYPE
    ):
        wake_model = _load_model(
            WAKE_STT_MODEL,
            WAKE_STT_DEVICE,
            WAKE_STT_COMPUTE_TYPE,
            WAKE_STT_LANGUAGE,
            "wake STT",
        )

    if use_oww:
        logger.info("Wakeword engine: openwakeword (model=%s, threshold=%.2f)", OWW_MODEL_NAME, OWW_THRESHOLD)
    else:
        logger.info("Wakeword engine: whisper (model=%s)", WAKE_STT_MODEL if WAKE_ONLY_MODE else STT_MODEL)

    logger.info("Conversation STT backend: %s", STT_BACKEND)
    client = AIHubClient()
    worker = ResponseWorker(client, state)
    segmenter = SpeechSegmenter()
    logger.info("Pipeline: non-blocking ResponseWorker started")

    while True:
        proc: subprocess.Popen[bytes] | None = None
        reader: AudioReader | None = None
        try:
            proc = _open_audio_pipe()
            if proc.stdout is None:
                raise RuntimeError("ffmpeg stdout unavailable")
            reader = AudioReader(proc.stdout)
            _write_status(state, "stream_connected")
            next_status_heartbeat = time.time() + max(0.5, STATUS_HEARTBEAT_SEC)
            while True:
                chunk = reader.read(timeout=10.0)
                if not chunk:
                    raise RuntimeError("camera_audio_stream_ended")

                now_ts = time.time()
                in_conversation = state.conversation_active(now_ts)

                speaker_playing = client.speaker_playing()
                state.last_speaker_state_ms = client.last_speaker_state_ms
                if now_ts < state.ignore_speaker_until:
                    speaker_playing = False
                if now_ts >= next_status_heartbeat:
                    _write_status(state, "running")
                    next_status_heartbeat = now_ts + max(0.5, STATUS_HEARTBEAT_SEC)

                if (
                    state.hard_idle_mode
                    and speaker_playing
                    and now_ts >= state.hard_idle_interrupt_after
                    and (now_ts - state.last_hard_idle_interrupt_ts) >= HARD_IDLE_INTERRUPT_COOLDOWN_SEC
                ):
                    ok_interrupt, reason_interrupt = client.interrupt_speaker("hard_idle_guard")
                    state.last_interrupt_http_ms = client.last_interrupt_http_ms
                    state.last_hard_idle_interrupt_ts = now_ts
                    client._speaker_cache = (time.time(), False)
                    logger.info(
                        "Hard idle guard interrupt: ok=%s reason=%s",
                        ok_interrupt,
                        reason_interrupt,
                    )
                    speaker_playing = False

                # --- IDLE + OWW: feed raw PCM directly to openwakeword ---
                if use_oww and oww_detector and not in_conversation:
                    if speaker_playing:
                        if WAKE_INTERRUPT_DURING_PLAYBACK and oww_detector.feed(
                            chunk,
                            threshold=OWW_PLAYBACK_THRESHOLD,
                        ):
                            logger.info("Interrupt: wake word during playback (idle)")
                            if BARGE_IN_INTERRUPT_SPEAKER:
                                ok_interrupt, reason_interrupt = client.interrupt_speaker("wake_during_playback")
                                state.last_interrupt_http_ms = client.last_interrupt_http_ms
                                if not ok_interrupt:
                                    logger.debug("Speaker interrupt failed: %s", reason_interrupt)
                            oww_detector.reset()
                            client._speaker_cache = (time.time(), False)
                            _write_status(state, "running", "interrupted")
                        continue  # skip wake detection during TTS playback
                    if oww_detector.feed(chunk):
                        logger.info("Wake word detected (openwakeword, model=%s)", OWW_MODEL_NAME)
                        state.hard_idle_mode = False
                        state.hard_idle_interrupt_after = 0.0
                        state.last_hard_idle_interrupt_ts = 0.0
                        worker.submit_wake(WAKE_CANONICAL)
                        oww_detector.reset()
                        _write_status(state, "running")
                    continue  # skip VAD+STT entirely in idle

                # --- CONVERSATION + SPEAKER PLAYING: interrupt / barge-in ---
                if use_oww and oww_detector and speaker_playing:
                    if WAKE_INTERRUPT_DURING_PLAYBACK and oww_detector.feed(
                        chunk,
                        threshold=OWW_PLAYBACK_THRESHOLD,
                    ):
                        logger.info("Interrupt: wake word during playback — stopping conversation")
                        if BARGE_IN_INTERRUPT_SPEAKER:
                            ok_interrupt, reason_interrupt = client.interrupt_speaker("wake_during_playback")
                            state.last_interrupt_http_ms = client.last_interrupt_http_ms
                            if not ok_interrupt:
                                logger.debug("Speaker interrupt failed: %s", reason_interrupt)
                        _set_conversation_inactive(state)
                        oww_detector.reset()
                        # Clear speaker state so echo suppression lifts immediately.
                        client._speaker_cache = (time.time(), False)
                        _write_status(state, "running", "interrupted")
                        continue

                    allow_barge_in = (
                        BARGE_IN_ENABLED
                        and (
                            in_conversation
                            or not BARGE_IN_REQUIRE_ACTIVE_CONVERSATION
                        )
                    )
                    if allow_barge_in:
                        for pcm in segmenter.feed(chunk):
                            seg_dbfs = _pcm_dbfs(pcm)
                            if seg_dbfs < BARGE_IN_MIN_DBFS:
                                if DEBUG_TRANSCRIPTS and seg_dbfs > BARGE_IN_MIN_DBFS - 12:
                                    logger.debug("Barge-in energy gate: %.1f dBFS < %.1f", seg_dbfs, BARGE_IN_MIN_DBFS)
                                continue
                            if not _contains_speech(pcm):
                                continue
                            stt_started = time.monotonic()
                            if STT_BACKEND == "google":
                                transcript = _transcribe_google(
                                    pcm, language=STT_LANGUAGE,
                                )
                            else:
                                transcript = _transcribe_chunk(
                                    conversation_model,
                                    pcm,
                                    language=STT_LANGUAGE,
                                    beam_size=STT_BEAM_SIZE,
                                    best_of=STT_BEST_OF,
                                    no_speech_threshold=STT_NO_SPEECH_THRESHOLD,
                                    log_prob_threshold=STT_LOGPROB_THRESHOLD,
                                    segment_min_avg_logprob=SEGMENT_MIN_AVG_LOGPROB,
                                    segment_max_no_speech_prob=SEGMENT_MAX_NO_SPEECH_PROB,
                                )
                            state.last_barge_in_stt_ms = _ms_since(stt_started)
                            _warn_if_slow(
                                "barge_in_stt",
                                state.last_barge_in_stt_ms,
                                LATENCY_WARN_BARGE_STT_MS,
                            )
                            if not transcript:
                                continue
                            logger.info("Barge-in transcript: %s", transcript)
                            if BARGE_IN_REQUIRE_INTERRUPT_PHRASE and not _is_interrupt_phrase(transcript):
                                in_post_wake_window = (
                                    state.last_wake_ts > 0
                                    and (time.time() - state.last_wake_ts) <= BARGE_IN_FREE_TURN_AFTER_WAKE_SEC
                                )
                                if not in_post_wake_window:
                                    logger.info("Barge-in ignored (no interrupt phrase): %s", transcript)
                                    continue
                                logger.info(
                                    "Barge-in accepted without interrupt phrase (post-wake window %.1fs): %s",
                                    BARGE_IN_FREE_TURN_AFTER_WAKE_SEC,
                                    transcript,
                                )
                            dropped = worker.preempt_pending()
                            if dropped:
                                logger.info("Preempted %d pending worker actions", dropped)
                            if BARGE_IN_INTERRUPT_SPEAKER:
                                ok_interrupt, reason_interrupt = client.interrupt_speaker("barge_in")
                                state.last_interrupt_http_ms = client.last_interrupt_http_ms
                                if not ok_interrupt:
                                    logger.debug("Speaker interrupt failed: %s", reason_interrupt)
                            _handle_transcript(
                                state,
                                worker,
                                transcript,
                                ignore_echo_time_guard=True,
                            )
                            state.ignore_speaker_until = time.time() + BARGE_IN_IGNORE_SPEAKER_SEC
                            client._speaker_cache = (time.time(), False)
                            _write_status(state, "running", "barge_in")
                            break
                    continue  # skip normal Whisper flow while speaker is active

                # --- ACTIVE CONVERSATION: VAD -> Silero -> Whisper pipeline ---
                for pcm in segmenter.feed(chunk):
                    seg_dbfs = _pcm_dbfs(pcm)
                    if seg_dbfs < MIN_DBFS:
                        state.ignored_count += 1
                        if DEBUG_TRANSCRIPTS and seg_dbfs > MIN_DBFS - 15:
                            logger.debug("Energy gate: %.1f dBFS < %.1f", seg_dbfs, MIN_DBFS)
                        continue

                    # Neural speech gate: reject keyboard clicks, noise, non-speech
                    if not _contains_speech(pcm):
                        state.ignored_count += 1
                        continue

                    now_ts = time.time()
                    in_conversation = state.conversation_active(now_ts)

                    if not use_oww and WAKE_ONLY_MODE and not in_conversation:
                        stt_started = time.monotonic()
                        transcript = _transcribe_chunk(
                            wake_model,
                            pcm,
                            language=WAKE_STT_LANGUAGE,
                            beam_size=WAKE_STT_BEAM_SIZE,
                            best_of=WAKE_STT_BEST_OF,
                            no_speech_threshold=WAKE_STT_NO_SPEECH_THRESHOLD,
                            log_prob_threshold=WAKE_STT_LOGPROB_THRESHOLD,
                            segment_min_avg_logprob=WAKE_SEGMENT_MIN_AVG_LOGPROB,
                            segment_max_no_speech_prob=WAKE_SEGMENT_MAX_NO_SPEECH_PROB,
                        )
                        state.last_stt_ms = _ms_since(stt_started)
                        _warn_if_slow("wake_stt", state.last_stt_ms, LATENCY_WARN_STT_MS)
                        if not transcript:
                            state.ignored_count += 1
                            continue
                        wake_hit, _, _ = _extract_wake_phrase(transcript)
                        if DEBUG_TRANSCRIPTS:
                            logger.info("Idle transcript: %s", transcript)
                        if not wake_hit:
                            state.ignored_count += 1
                            continue
                        logger.info("Wake phrase matched: %s", transcript)
                    else:
                        stt_started = time.monotonic()
                        if STT_BACKEND == "google":
                            transcript = _transcribe_google(
                                pcm, language=STT_LANGUAGE,
                            )
                        else:
                            transcript = _transcribe_chunk(
                                conversation_model,
                                pcm,
                                language=STT_LANGUAGE,
                                beam_size=STT_BEAM_SIZE,
                                best_of=STT_BEST_OF,
                                no_speech_threshold=STT_NO_SPEECH_THRESHOLD,
                                log_prob_threshold=STT_LOGPROB_THRESHOLD,
                                segment_min_avg_logprob=SEGMENT_MIN_AVG_LOGPROB,
                                segment_max_no_speech_prob=SEGMENT_MAX_NO_SPEECH_PROB,
                            )
                        state.last_stt_ms = _ms_since(stt_started)
                        _warn_if_slow("conversation_stt", state.last_stt_ms, LATENCY_WARN_STT_MS)
                    if transcript:
                        if DEBUG_TRANSCRIPTS:
                            logger.info("Heard: %s", transcript)
                        _handle_transcript(state, worker, transcript)
                    else:
                        state.ignored_count += 1
                    _write_status(state, "running")
        except Exception as exc:  # pragma: no cover
            logger.warning("Listener loop error: %s", exc)
            _write_status(state, "reconnecting", str(exc))
            time.sleep(RECONNECT_DELAY_SEC)
        finally:
            if reader:
                reader.stop()
            if proc and proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass


if __name__ == "__main__":
    run()
