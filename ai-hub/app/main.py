from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
import uuid
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)
log = logging.getLogger("aihub")
log.setLevel(logging.INFO)

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import db
from .actions import (
    control_air_purifier,
    control_lights,
    control_tv,
    execute_route_actions,
    get_ha_state,
    get_current_track,
    interrupt_camera_speaker,
    load_ha_config,
    next_track,
    pause_spotify,
    play_spotify,
    play_spotify_uri,
    prev_track,
    speak_to_camera,
)
from .spotify_client import (
    search_spotify,
    build_auth_url,
    exchange_code,
    find_user_playlist,
    play_liked_songs,
    play_context_uri,
    has_user_auth,
    is_liked_songs_uri,
)
from .codex_client import ask_codex, build_system_prompt, should_send_processing_ack
from . import response_pool
from .response_pool import PoolContext
from .intent_detector import detect_camera_intent
from .follow_tracker import SoftFollowController
from .live_video import LiveVideoFeed
from .ollama_client import ask_vision_model, classify_as_vision
from .policy import evaluate_candidate_egress, should_use_codex
from .rep_counter import SimpleVerticalRepCounter
from .reolink_client import execute_camera_intent
from .snapshot_client import fetch_snapshot



APP_VERSION = "0.1.0"
TOKEN = os.getenv("AIHUB_TOKEN", "").strip()
CONVERSATION_TTL_SEC = int(os.getenv("AIHUB_CONVERSATION_TTL_SEC", "90"))
STICKY_CONVERSATION = os.getenv("AIHUB_STICKY_CONVERSATION", "1").strip() == "1"
STICKY_CONVERSATION_SOURCE = os.getenv("AIHUB_STICKY_CONVERSATION_SOURCE", "audio").strip().lower()
WAKE_PHRASES = [
    p.strip().lower()
    for p in os.getenv("AIHUB_WAKE_PHRASES", "hej codex,hey codex").split(",")
    if p.strip()
]
WAKE_ACK_TEXT = os.getenv("AIHUB_WAKE_ACK_TEXT", "Hej! Hur kan jag hjälpa dig?")
AUDIO_REQUIRE_WAKE_OR_ACTIVE = (
    os.getenv("AIHUB_AUDIO_REQUIRE_WAKE_OR_ACTIVE", "1").strip() == "1"
)
ALLOW_AUDIO_CAMERA_LOOK = (
    os.getenv("AIHUB_ALLOW_AUDIO_CAMERA_LOOK", "0").strip() == "1"
)
PROCESSING_ACK_ENABLED = os.getenv("AIHUB_PROCESSING_ACK_ENABLED", "1").strip() == "1"
PROCESSING_ACK_TEXT = os.getenv(
    "AIHUB_PROCESSING_ACK_TEXT",
    "Ja självklart, ge mig en sekund.",
).strip()
MEMORY_RELEVANT_K = int(os.getenv("AIHUB_MEMORY_RELEVANT_K", "8"))
MEMORY_LOOKBACK = int(os.getenv("AIHUB_MEMORY_LOOKBACK", "5000"))
MEMORY_RECALL_HOURS = int(os.getenv("AIHUB_MEMORY_RECALL_HOURS", "24"))
MEMORY_RECALL_LIMIT = int(os.getenv("AIHUB_MEMORY_RECALL_LIMIT", "20"))
CODEX_DB_CONTEXT_DEFAULT = os.getenv("AIHUB_CODEX_DB_CONTEXT_DEFAULT", "0").strip() == "1"
CODEX_DB_CONTEXT_ON_MEMORY_QUERY = (
    os.getenv("AIHUB_CODEX_DB_CONTEXT_ON_MEMORY_QUERY", "1").strip() == "1"
)
CODEX_DB_CONTEXT_ON_PROFILE_QUERY = (
    os.getenv("AIHUB_CODEX_DB_CONTEXT_ON_PROFILE_QUERY", "1").strip() == "1"
)
CODEX_DB_CONTEXT_LIMIT = int(os.getenv("AIHUB_CODEX_DB_CONTEXT_LIMIT", "10"))
CODEX_DB_CONTEXT_LIMIT_SEARCH = int(os.getenv("AIHUB_CODEX_DB_CONTEXT_LIMIT_SEARCH", "6"))
IDENTITY_RESOLVE_MIN_SCORE = float(os.getenv("AIHUB_IDENTITY_RESOLVE_MIN_SCORE", "0.82"))
VISION_LOOP_ENABLED = os.getenv("AIHUB_VISION_LOOP_ENABLED", "1").strip() == "1"
VISION_LOOP_TICK_SEC = float(os.getenv("AIHUB_VISION_LOOP_TICK_SEC", "1.4"))
VISION_QUERY_OLLAMA_TIMEOUT_SEC = int(os.getenv("AIHUB_VISION_QUERY_OLLAMA_TIMEOUT_SEC", "14"))
VISION_LOOP_OLLAMA_TIMEOUT_SEC = int(os.getenv("AIHUB_VISION_LOOP_OLLAMA_TIMEOUT_SEC", "22"))
VISION_QUERY_ACK_TEXT = os.getenv("AIHUB_VISION_QUERY_ACK_TEXT", "Jag tittar nu.").strip()
VISION_VIDEO_ENABLED = os.getenv("AIHUB_VISION_VIDEO_ENABLED", "1").strip() == "1"
VISION_VIDEO_RTSP_URL = (
    os.getenv("AIHUB_VISION_VIDEO_RTSP_URL", "")
    or os.getenv("CAMERA_LISTENER_RTSP_URL", "rtsp://frigate:8554/reolink_e1pro_main")
).strip()
VISION_VIDEO_TARGET_FPS = float(os.getenv("AIHUB_VISION_VIDEO_TARGET_FPS", "9"))
VISION_VIDEO_MAX_STALE_SEC = float(os.getenv("AIHUB_VISION_VIDEO_MAX_STALE_SEC", "1.8"))
VISION_VIDEO_RECONNECT_SEC = float(os.getenv("AIHUB_VISION_VIDEO_RECONNECT_SEC", "1.0"))
VISION_VIDEO_JPEG_QUALITY = int(os.getenv("AIHUB_VISION_VIDEO_JPEG_QUALITY", "80"))
VISION_ANALYZER_MODE = os.getenv("AIHUB_VISION_ANALYZER_MODE", "auto").strip().lower()
VISION_CV_ENABLED = os.getenv("AIHUB_VISION_CV_ENABLED", "1").strip() == "1"
VISION_CV_MIN_AMPLITUDE = float(os.getenv("AIHUB_VISION_CV_MIN_AMPLITUDE", "0.09"))
VISION_CV_MIN_REP_INTERVAL_SEC = float(os.getenv("AIHUB_VISION_CV_MIN_REP_INTERVAL_SEC", "0.45"))
VISION_IDENTITY_PROMPT_COOLDOWN_SEC = float(
    os.getenv("AIHUB_VISION_IDENTITY_PROMPT_COOLDOWN_SEC", "12")
)
VISION_PENDING_IDENTITY_TTL_SEC = float(
    os.getenv("AIHUB_VISION_PENDING_IDENTITY_TTL_SEC", "90")
)
VISION_TTS_MIN_INTERVAL_SEC = float(os.getenv("AIHUB_VISION_TTS_MIN_INTERVAL_SEC", "1.6"))
VISION_ACTIVITY_DEFAULT = os.getenv("AIHUB_VISION_ACTIVITY_DEFAULT", "workout").strip() or "workout"
CAMERA_LOOK_PERSON_SEARCH_ENABLED = (
    os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_ENABLED", "1").strip() == "1"
)
CAMERA_LOOK_PERSON_SEARCH_SWEEP = [
    x.strip().lower()
    for x in os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_SWEEP", "left,right,up,down").split(",")
    if x.strip()
]
CAMERA_LOOK_PERSON_SEARCH_RECENTER_EACH_STEP = (
    os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_RECENTER_EACH_STEP", "1").strip() == "1"
)
CAMERA_LOOK_PERSON_SEARCH_RECENTER_SETTLE_SEC = float(
    os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_RECENTER_SETTLE_SEC", "1.1")
)
CAMERA_LOOK_PERSON_SEARCH_SETTLE_SEC = float(
    os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_SETTLE_SEC", "0.55")
)
CAMERA_LOOK_PERSON_SEARCH_MIN_CONF = float(
    os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_MIN_CONF", "0.45")
)
CAMERA_LOOK_PERSON_SEARCH_RESET = (
    os.getenv("AIHUB_CAMERA_LOOK_PERSON_SEARCH_RESET", "1").strip() == "1"
)
CAMERA_LOOK_SKIP_CODEX_REWRITE = (
    os.getenv("AIHUB_CAMERA_LOOK_SKIP_CODEX_REWRITE", "1").strip() == "1"
)
CAMERA_FOLLOW_CENTER_ON_START = (
    os.getenv("AIHUB_CAMERA_FOLLOW_CENTER_ON_START", "1").strip() == "1"
)
CAMERA_FOLLOW_CENTER_VISION_TIMEOUT_SEC = int(
    os.getenv("AIHUB_CAMERA_FOLLOW_CENTER_VISION_TIMEOUT_SEC", "8")
)
SOFT_FOLLOW_ENABLED = os.getenv("AIHUB_SOFT_FOLLOW_ENABLED", "1").strip() == "1"
SOFT_FOLLOW_USE_CAMERA_AUTOTRACK = (
    os.getenv("AIHUB_SOFT_FOLLOW_USE_CAMERA_AUTOTRACK", "0").strip() == "1"
)
SOFT_FOLLOW_TICK_SEC = float(os.getenv("AIHUB_SOFT_FOLLOW_TICK_SEC", "0.34"))
SOFT_FOLLOW_MOVE_COOLDOWN_SEC = float(os.getenv("AIHUB_SOFT_FOLLOW_MOVE_COOLDOWN_SEC", "0.45"))
SOFT_FOLLOW_X_DEADZONE = float(os.getenv("AIHUB_SOFT_FOLLOW_X_DEADZONE", "0.14"))
SOFT_FOLLOW_Y_DEADZONE = float(os.getenv("AIHUB_SOFT_FOLLOW_Y_DEADZONE", "0.20"))
SOFT_FOLLOW_FRAME_MAX_AGE_SEC = float(os.getenv("AIHUB_SOFT_FOLLOW_FRAME_MAX_AGE_SEC", "5.0"))
SOFT_FOLLOW_ENABLE_TILT = os.getenv("AIHUB_SOFT_FOLLOW_ENABLE_TILT", "1").strip() == "1"
SOFT_FOLLOW_INVERT_X = os.getenv("AIHUB_SOFT_FOLLOW_INVERT_X", "0").strip() == "1"
SOFT_FOLLOW_INVERT_Y = os.getenv("AIHUB_SOFT_FOLLOW_INVERT_Y", "0").strip() == "1"
SOFT_FOLLOW_MOTION_FALLBACK = os.getenv("AIHUB_SOFT_FOLLOW_MOTION_FALLBACK", "1").strip() == "1"
SOFT_FOLLOW_MOTION_MIN_AREA_RATIO = float(
    os.getenv("AIHUB_SOFT_FOLLOW_MOTION_MIN_AREA_RATIO", "0.004")
)
SOFT_FOLLOW_LOST_SWEEP_AFTER_SEC = float(
    os.getenv("AIHUB_SOFT_FOLLOW_LOST_SWEEP_AFTER_SEC", "2.0")
)
SOFT_FOLLOW_LOST_SWEEP_COOLDOWN_SEC = float(
    os.getenv("AIHUB_SOFT_FOLLOW_LOST_SWEEP_COOLDOWN_SEC", "1.1")
)
SOFT_FOLLOW_LOST_SWEEP_PATTERN = [
    x.strip().lower()
    for x in os.getenv("AIHUB_SOFT_FOLLOW_LOST_SWEEP_PATTERN", "left,right,up,down").split(",")
    if x.strip()
]
SOFT_FOLLOW_LOCK_LOST_AFTER_SEC = float(
    os.getenv("AIHUB_SOFT_FOLLOW_LOCK_LOST_AFTER_SEC", "3.0")
)
SOFT_FOLLOW_LOCK_REQUIRE_CONSECUTIVE = int(
    os.getenv("AIHUB_SOFT_FOLLOW_LOCK_REQUIRE_CONSECUTIVE", "3")
)
SOFT_FOLLOW_LOCK_ACK_AFTER_CONSECUTIVE = int(
    os.getenv("AIHUB_SOFT_FOLLOW_LOCK_ACK_AFTER_CONSECUTIVE", "5")
)
SOFT_FOLLOW_SWEEP_MAX_MOVES = int(
    os.getenv("AIHUB_SOFT_FOLLOW_SWEEP_MAX_MOVES", "6")
)
SOFT_FOLLOW_SWEEP_PAUSE_SEC = float(
    os.getenv("AIHUB_SOFT_FOLLOW_SWEEP_PAUSE_SEC", "8.0")
)
SOFT_FOLLOW_RECOVER_MAX_MOVES = int(
    os.getenv("AIHUB_SOFT_FOLLOW_RECOVER_MAX_MOVES", "4")
)
SOFT_FOLLOW_FULL_PAN_STEPS = int(
    os.getenv("AIHUB_SOFT_FOLLOW_FULL_PAN_STEPS", "20"),
)
SOFT_FOLLOW_SMOOTHING_ALPHA = float(
    os.getenv("AIHUB_SOFT_FOLLOW_SMOOTHING_ALPHA", "0.35")
)
SOFT_FOLLOW_LOCK_ACK_TEXT = os.getenv("AIHUB_SOFT_FOLLOW_LOCK_ACK_TEXT", "Jag hittade dig.").strip()
LATENCY_BUDGET_STT_TO_AIHUB_MS = float(
    os.getenv("AIHUB_LATENCY_BUDGET_STT_TO_AIHUB_MS", "1200")
)
LATENCY_BUDGET_CODEX_MS = float(
    os.getenv("AIHUB_LATENCY_BUDGET_CODEX_MS", "4500")
)
LATENCY_BUDGET_CAMERA_ACTIONS_MS = float(
    os.getenv("AIHUB_LATENCY_BUDGET_CAMERA_ACTIONS_MS", "1200")
)
LATENCY_BUDGET_TURN_TOTAL_MS = float(
    os.getenv("AIHUB_LATENCY_BUDGET_TURN_TOTAL_MS", "6000")
)
LATENCY_BUDGET_TTS_REQUEST_MS = float(
    os.getenv("AIHUB_LATENCY_BUDGET_TTS_REQUEST_MS", "1500")
)

# Follow-up remark config (T021)
FOLLOWUP_DELAY_SEC = float(os.getenv("AIHUB_FOLLOWUP_DELAY_SEC", "1.5"))
FOLLOWUP_PROBABILITY = float(os.getenv("AIHUB_FOLLOWUP_PROBABILITY", "0.30"))

# Minimal mode verbal confirmations (T032)
MINIMAL_MODE_ON_ACK_TEXT = os.getenv(
    "AIHUB_MINIMAL_MODE_ON_ACK_TEXT", "Okej, jag svarar kortare."
).strip()
MINIMAL_MODE_OFF_ACK_TEXT = os.getenv(
    "AIHUB_MINIMAL_MODE_OFF_ACK_TEXT", "Okej, jag svarar som vanligt igen."
).strip()

# Minimal mode detection patterns (T031)
_MINIMAL_MODE_ON = re.compile(
    r"\b(svara|prata|var)\b.{0,20}\b(kort(are)?|enkelt|koncist|direkt|kortfattat)\b",
    re.IGNORECASE,
)
_MINIMAL_MODE_OFF = re.compile(
    r"\b(svara|prata|var)\b.{0,20}\b(normalt?|som vanligt|utf(ö|o)rligt)\b",
    re.IGNORECASE,
)

_LIGHT_TARGET = re.compile(
    r"\b(lamporn?a?|ljuset|kronan?|takkronan?|belysning(en)?|lyset)\b",
    re.IGNORECASE,
)
_LIGHT_ON_VERB = re.compile(r"\b(tänd|slå på|sätt på|aktivera)\b", re.IGNORECASE)
_LIGHT_OFF_VERB = re.compile(r"\b(släck|slå av|stäng av|avaktivera)\b", re.IGNORECASE)
_LIGHT_DIM_PCT = re.compile(
    r"\b(dimma|sätt|ändra|justera)\b.{0,25}?(?P<pct>\d+)\s*(%|procent)"
    r"|\b(?P<pct2>\d+)\s*(%|procent)\s*(ljus|lampa|belysning|dimmer)\b",
    re.IGNORECASE,
)
_LIGHT_FULL = re.compile(r"\b(full(t)?|hundra|max)\s*(ljus|lampor|belysning)\b", re.IGNORECASE)
_LIGHT_HALF = re.compile(r"\b(halv(t)?)\s*(ljus|lampor|belysning)\b", re.IGNORECASE)

_LIGHT_COLORS: list[tuple[re.Pattern[str], tuple[int, int, int]]] = [
    (re.compile(r"\brö(d|tt?)\b", re.IGNORECASE), (255, 0, 0)),
    (re.compile(r"\bblå\b", re.IGNORECASE), (0, 0, 255)),
    (re.compile(r"\bgrö(n|nt?)\b", re.IGNORECASE), (0, 200, 0)),
    (re.compile(r"\blila\b|\bviolett?\b", re.IGNORECASE), (128, 0, 200)),
    (re.compile(r"\borange\b", re.IGNORECASE), (255, 100, 0)),
    (re.compile(r"\brosa\b|\bpink\b", re.IGNORECASE), (255, 20, 130)),
    (re.compile(r"\bgul\b", re.IGNORECASE), (255, 220, 0)),
    (re.compile(r"\bturkos\b|\bcyan\b", re.IGNORECASE), (0, 220, 200)),
]
_LIGHT_WARM = re.compile(r"\b(varm)\s*(vit|ljus|belysning)\b", re.IGNORECASE)
_LIGHT_COOL = re.compile(r"\b(kall|cool|kallvit)\s*(vit|ljus|belysning)?\b", re.IGNORECASE)
_LIGHT_NEUTRAL = re.compile(r"\bneutralt?\s*(vit|ljus|belysning)?\b", re.IGNORECASE)


def _detect_light_intent(text: str) -> dict | None:
    """Parse Swedish light control commands. Returns kwargs for control_lights() or None."""
    has_target = bool(_LIGHT_TARGET.search(text))

    if _LIGHT_OFF_VERB.search(text) and has_target:
        return {"command": "off"}

    # Brightness: "dimma till 40%" / "sätt lamporna på 80 procent"
    m = _LIGHT_DIM_PCT.search(text)
    if m:
        raw_pct = m.group("pct") or m.group("pct2")
        if raw_pct:
            return {"command": "on", "brightness_pct": max(1, min(100, int(raw_pct)))}

    if _LIGHT_FULL.search(text):
        return {"command": "on", "brightness_pct": 100}
    if _LIGHT_HALF.search(text):
        return {"command": "on", "brightness_pct": 50}

    # Color temperature (need light context)
    if has_target or _LIGHT_ON_VERB.search(text):
        if _LIGHT_WARM.search(text):
            return {"command": "on", "color_temp_kelvin": 2700}
        if _LIGHT_COOL.search(text):
            return {"command": "on", "color_temp_kelvin": 5000}
        if _LIGHT_NEUTRAL.search(text):
            return {"command": "on", "color_temp_kelvin": 3500}

    # RGB colors — require a light target to avoid false positives
    if has_target:
        for pattern, rgb in _LIGHT_COLORS:
            if pattern.search(text):
                return {"command": "on", "rgb_color": rgb}

    if _LIGHT_ON_VERB.search(text) and has_target:
        return {"command": "on"}

    return None


_AIR_TARGET = re.compile(
    r"\b(luftrenaren?|luftfuktaren?|fläkten?|renaren?|fuktaren?|philips)\b",
    re.IGNORECASE,
)
_AIR_ON = re.compile(r"\b(sätt på|slå på|starta|aktivera|tänd)\b", re.IGNORECASE)
_AIR_OFF = re.compile(r"\b(stäng av|slå av|stäng|stoppa|avaktivera|släck)\b", re.IGNORECASE)
_AIR_TURBO = re.compile(r"\b(turbo|full(t)?|max(imum)?)\b", re.IGNORECASE)
_AIR_SLEEP = re.compile(r"\b(natt(läge)?|sömn(läge)?|tyst(läge)?|sleep)\b", re.IGNORECASE)
_AIR_AUTO = re.compile(r"\b(auto(läge)?|normal(läge)?)\b", re.IGNORECASE)

_AIR_QUERY_QUALITY = re.compile(
    r"\b(luftkvalitet|luftkval|luft kvalitet|pm2|pm 2|partikel|föroreningar?)\b",
    re.IGNORECASE,
)
_AIR_QUERY_HUMIDITY = re.compile(
    r"\b(luftfuktighe(t|ten)|fuktighet|hur fuktigt)\b",
    re.IGNORECASE,
)
_AIR_QUERY_TEMP = re.compile(
    r"\b(temperatur(en)?|hur varmt|hur kallt|grader)\b.{0,20}\b(sovrum|rum|inne|här)\b"
    r"|\b(sovrum|rum|inne|här)\b.{0,20}\b(temperatur(en)?|hur varmt|hur kallt|grader)\b",
    re.IGNORECASE,
)


def _detect_air_intent(text: str) -> dict | None:
    """Detect air purifier control/query commands. Returns dict or None."""
    has_target = bool(_AIR_TARGET.search(text))

    # Queries — don't require air target word (natural phrasing)
    if _AIR_QUERY_QUALITY.search(text):
        return {"kind": "query", "sensor": "sensor.sovrum_pm2_5", "unit": "µg/m³", "label": "PM2.5-nivån i sovrummet"}
    if _AIR_QUERY_HUMIDITY.search(text):
        return {"kind": "query", "sensor": "sensor.sovrum_humidity", "unit": "%", "label": "Luftfuktigheten i sovrummet"}
    if _AIR_QUERY_TEMP.search(text):
        return {"kind": "query", "sensor": "sensor.sovrum_temperature", "unit": "°C", "label": "Temperaturen i sovrummet"}

    if not has_target:
        return None

    # Control commands
    if _AIR_OFF.search(text):
        return {"kind": "control", "command": "off"}
    if _AIR_TURBO.search(text):
        return {"kind": "control", "command": "turbo"}
    if _AIR_SLEEP.search(text):
        return {"kind": "control", "command": "sleep"}
    if _AIR_AUTO.search(text):
        return {"kind": "control", "command": "auto"}
    if _AIR_ON.search(text):
        return {"kind": "control", "command": "on"}

    return None


app = FastAPI(title="ai-hub", version=APP_VERSION)


_vision_loop_started = False
# Cooldown to prevent echo loops after Ollama-classified vision queries.
_last_ollama_vision_at: float = 0.0
_ollama_vision_lock = threading.Lock()
_OLLAMA_VISION_COOLDOWN_SEC: float = float(os.getenv("AIHUB_OLLAMA_VISION_COOLDOWN_SEC", "20.0"))
_live_video_started = False
_live_video_feed: LiveVideoFeed | None = None
_rep_counter: SimpleVerticalRepCounter | None = None
_soft_follow: SoftFollowController | None = None
_PENDING_IDENTITY_TASK_KEY = "pending_identity_task_session_id"
_PENDING_IDENTITY_CONV_KEY = "pending_identity_conversation_id"
_PENDING_IDENTITY_EMBED_KEY = "pending_identity_embedding_json"
_PENDING_IDENTITY_SET_AT_KEY = "pending_identity_set_at"
_PENDING_IDENTITY_PROMPT_AT_KEY = "pending_identity_prompt_at"

# Follow-up scheduler state (T021)
_followup_cancel = threading.Event()
_followup_lock = threading.Lock()
_pending_followup_timer: threading.Timer | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_time_of_day() -> str:
    """Returns morning/afternoon/evening/night based on local hour. (T010)"""
    hour = datetime.now().hour
    if 6 <= hour < 11:
        return "morning"
    elif 11 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 23:
        return "evening"
    else:
        return "night"


def _build_pool_context(conversation_id: str) -> PoolContext:
    """Resolve identity + companion pref + recency for the given conversation. (T011)"""
    identity = db.get_conversation_identity(conversation_id)
    person_id: int | None = int(identity["person_id"]) if identity else None
    identity_name: str | None = str(identity["athlete_name"]).strip() if identity else None

    companion_pref = db.get_companion_pref(person_id) if person_id is not None else "full"
    companion_mode = companion_pref != "minimal"

    last_at = db.get_last_interaction_at(person_id)
    recency = False
    if last_at is not None:
        diff = datetime.now(timezone.utc) - last_at
        recency = diff.total_seconds() < 600  # < 10 minutes

    return PoolContext(
        time_of_day=_get_time_of_day(),
        recency=recency,
        identity_name=identity_name or None,
        companion_mode=companion_mode,
        last_action=None,
    )


def _build_wake_response(pool_ctx: PoolContext) -> str:
    """Select wake greeting pool based on recency and time of day. (T012)"""
    if pool_ctx.recency:
        return response_pool.pick("wake_continuity", pool_ctx)
    return response_pool.pick(f"wake_{pool_ctx.time_of_day}", pool_ctx)


def _detect_minimal_mode_switch(text: str) -> str | None:
    """Returns 'minimal_mode_on', 'minimal_mode_off', or None. (T033)"""
    if _MINIMAL_MODE_ON.search(text):
        return "minimal_mode_on"
    if _MINIMAL_MODE_OFF.search(text):
        return "minimal_mode_off"
    return None


def schedule_followup(text: str, source: str, delay_sec: float = FOLLOWUP_DELAY_SEC) -> None:
    """Schedule a deferred follow-up remark; cancels any pending timer. (T022)"""
    global _pending_followup_timer
    with _followup_lock:
        if _pending_followup_timer is not None:
            _pending_followup_timer.cancel()
        _followup_cancel.clear()
        _text = text
        _source = source

        def _deliver() -> None:
            if _followup_cancel.is_set():
                return
            try:
                speak_to_camera(_text, _source, event="reply")
                log.info("followup delivered: %r", _text)
            except Exception as exc:
                log.error("Follow-up TTS failed: %s", exc)

        _pending_followup_timer = threading.Timer(delay_sec, _deliver)
        _pending_followup_timer.daemon = True
        _pending_followup_timer.start()


def cancel_followup() -> None:
    """Cancel any pending deferred follow-up remark. (T023)"""
    global _pending_followup_timer
    _followup_cancel.set()
    with _followup_lock:
        if _pending_followup_timer is not None:
            _pending_followup_timer.cancel()


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


def _parse_mode() -> dict[str, Any]:
    state = db.get_mode_state()
    return {
        "current_mode": state.get("current_mode", "idle"),
        "privacy_mode": db.db_to_bool(state.get("privacy_mode")),
        "task_session_mode": db.db_to_bool(state.get("task_session_mode")),
        "conversation_id": state.get("conversation_id", ""),
        "task_session_id": state.get("task_session_id", ""),
        "conversation_expires_at": state.get("conversation_expires_at", ""),
    }


def _set_mode(
    *,
    current_mode: str | None = None,
    privacy_mode: bool | None = None,
    task_session_mode: bool | None = None,
    conversation_id: str | None = None,
    task_session_id: str | None = None,
    conversation_expires_at: str | None = None,
) -> None:
    payload: dict[str, str] = {}
    if current_mode is not None:
        payload["current_mode"] = current_mode
    if privacy_mode is not None:
        payload["privacy_mode"] = db.bool_to_db(privacy_mode)
    if task_session_mode is not None:
        payload["task_session_mode"] = db.bool_to_db(task_session_mode)
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    if task_session_id is not None:
        payload["task_session_id"] = task_session_id
    if conversation_expires_at is not None:
        payload["conversation_expires_at"] = conversation_expires_at
    if payload:
        db.set_mode_state(payload)


def _extract_wake_text(text: str) -> tuple[bool, str]:
    lowered = text.strip().lower()
    for phrase in WAKE_PHRASES:
        if lowered == phrase:
            return True, ""
        if lowered.startswith(phrase):
            remainder = text.strip()[len(phrase) :].lstrip(" ,:;-")
            return True, remainder
    return False, text


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_active_audio_conversation(conversation_id: str, mode: dict[str, Any]) -> tuple[bool, str]:
    current_conversation_id = mode.get("conversation_id", "")
    if not current_conversation_id:
        return False, "missing_conversation"
    if current_conversation_id != conversation_id:
        return False, "conversation_mismatch"

    expires_at = _parse_iso(mode.get("conversation_expires_at", ""))
    if not expires_at:
        return False, "missing_or_invalid_expiry"
    if expires_at <= datetime.now(timezone.utc):
        next_mode = "task_session_mode" if mode.get("task_session_mode") else "idle"
        _set_mode(
            current_mode=next_mode,
            conversation_id="",
            conversation_expires_at="",
        )
        return False, "conversation_expired"
    return True, "active"


def _to_ms(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000.0, 1)


def _warn_if_over_budget(stage: str, elapsed_ms: float | None, budget_ms: float) -> None:
    if elapsed_ms is None or budget_ms <= 0:
        return
    if elapsed_ms > budget_ms:
        log.warning(
            "Latency budget exceeded: %s=%.1fms (budget=%.1fms)",
            stage,
            elapsed_ms,
            budget_ms,
        )


def _is_memory_recall_query(text: str) -> bool:
    lowered = text.lower()
    recall_markers = (
        "kommer du ihåg",
        "minns du",
        "vad pratade vi",
        "vad sa vi",
        "vad sa jag",
        "vad snackade vi om",
        "förra veckan",
        "igår",
        "idag",
        "nyss",
    )
    return any(marker in lowered for marker in recall_markers)


def _is_profile_memory_query(text: str) -> bool:
    lowered = text.lower()
    profile_markers = (
        "jag heter",
        "vad heter jag",
        "vem är jag",
        "min adress",
        "vart bor jag",
        "kom ihåg att jag",
        "min fru",
        "min frus",
        "min man",
    )
    return any(marker in lowered for marker in profile_markers)


def _should_attach_db_context_for_codex(text: str) -> bool:
    if CODEX_DB_CONTEXT_DEFAULT:
        return True
    if CODEX_DB_CONTEXT_ON_MEMORY_QUERY and _is_memory_recall_query(text):
        return True
    if CODEX_DB_CONTEXT_ON_PROFILE_QUERY and _is_profile_memory_query(text):
        return True
    return False


def _codex_db_context_limit(text: str) -> int:
    if should_send_processing_ack(text):
        return max(1, CODEX_DB_CONTEXT_LIMIT_SEARCH)
    return max(1, CODEX_DB_CONTEXT_LIMIT)


def _clean_athlete_name(name: str | None) -> str:
    return " ".join(str(name or "").strip().split())


def _resolve_athlete_name(
    *,
    explicit_name: str | None = None,
    conversation_id: str | None = None,
    task_session_id: str | None = None,
) -> str:
    explicit = _clean_athlete_name(explicit_name)
    if explicit:
        return explicit

    if task_session_id:
        task_identity = db.get_task_identity(task_session_id)
        if task_identity:
            from_task = _clean_athlete_name(task_identity.get("athlete_name"))
            if from_task:
                return from_task

    if conversation_id:
        conv_identity = db.get_conversation_identity(conversation_id)
        if conv_identity:
            from_conv = _clean_athlete_name(conv_identity.get("athlete_name"))
            if from_conv:
                return from_conv

    return ""


def _identity_required_response(scope: str) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": "identity_required",
        "scope": scope,
        "prompt_sv": "Vem tränar nu? Säg till exempel: Det är <namn>.",
    }


def _clamp01(value: float | int | None, default: float = 0.0) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _extract_json_object(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    return match.group(0).strip() if match else ""


def _parse_vision_tick_payload(raw_text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "activity": VISION_ACTIVITY_DEFAULT,
        "rep_count": None,
        "form_flags": [],
        "fatigue_score": 0.0,
        "confidence": 0.0,
        "summary_sv": str(raw_text or "").strip()[:240],
    }
    chunk = _extract_json_object(raw_text)
    if not chunk:
        # Fallback: first integer in free text as rep_count if present.
        match = re.search(r"\b(\d{1,4})\b", str(raw_text or ""))
        if match:
            try:
                payload["rep_count"] = int(match.group(1))
            except ValueError:
                payload["rep_count"] = None
        return payload
    try:
        parsed = json.loads(chunk)
    except json.JSONDecodeError:
        return payload

    activity = str(parsed.get("activity", "")).strip()
    payload["activity"] = activity or VISION_ACTIVITY_DEFAULT

    rep_raw = parsed.get("rep_count")
    try:
        rep_val = int(rep_raw) if rep_raw is not None else None
    except (TypeError, ValueError):
        rep_val = None
    payload["rep_count"] = rep_val if rep_val is None or rep_val >= 0 else None

    flags_raw = parsed.get("form_flags", [])
    if isinstance(flags_raw, list):
        payload["form_flags"] = [str(x).strip() for x in flags_raw if str(x).strip()][:8]

    payload["fatigue_score"] = _clamp01(parsed.get("fatigue_score"), 0.0)
    payload["confidence"] = _clamp01(parsed.get("confidence"), 0.0)
    summary = str(parsed.get("summary_sv", "")).strip()
    if summary:
        payload["summary_sv"] = summary[:240]
    return payload


def _build_face_embedding(image_bytes: bytes) -> list[float]:
    if not image_bytes or Image is None:
        return []
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img = img.convert("L")
            width, height = img.size
            if width <= 0 or height <= 0:
                return []
            # Center crop to bias towards person in the middle.
            side = min(width, height)
            left = (width - side) // 2
            top = (height - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((32, 32))
            pixels = list(img.getdata())
    except Exception:
        return []

    if not pixels:
        return []
    # Compress 32x32 -> 16x8 (128 dims) by averaging 2x4 blocks.
    embedding: list[float] = []
    for by in range(8):
        for bx in range(16):
            acc = 0.0
            n = 0
            for iy in range(by * 4, by * 4 + 4):
                for ix in range(bx * 2, bx * 2 + 2):
                    acc += float(pixels[iy * 32 + ix])
                    n += 1
            embedding.append((acc / max(1, n)) / 255.0)

    mean = sum(embedding) / max(1, len(embedding))
    normed = [round(v - mean, 6) for v in embedding]
    return normed


def _pending_identity_get() -> dict[str, Any] | None:
    state = db.get_mode_state()
    task_session_id = str(state.get(_PENDING_IDENTITY_TASK_KEY, "")).strip()
    conversation_id = str(state.get(_PENDING_IDENTITY_CONV_KEY, "")).strip()
    raw_embedding = str(state.get(_PENDING_IDENTITY_EMBED_KEY, "")).strip()
    if not task_session_id or not conversation_id or not raw_embedding:
        return None
    set_at = _parse_iso(str(state.get(_PENDING_IDENTITY_SET_AT_KEY, "")).strip())
    if not set_at:
        return None
    age_sec = max(0.0, (datetime.now(timezone.utc) - set_at).total_seconds())
    if age_sec > VISION_PENDING_IDENTITY_TTL_SEC:
        _pending_identity_clear()
        return None
    try:
        embedding = json.loads(raw_embedding)
    except Exception:
        _pending_identity_clear()
        return None
    prompt_at = _parse_iso(str(state.get(_PENDING_IDENTITY_PROMPT_AT_KEY, "")).strip())
    return {
        "task_session_id": task_session_id,
        "conversation_id": conversation_id,
        "embedding": embedding,
        "set_at": set_at,
        "prompt_at": prompt_at,
    }


def _pending_identity_set(*, task_session_id: str, conversation_id: str, embedding: list[float]) -> None:
    db.set_mode_state(
        {
            _PENDING_IDENTITY_TASK_KEY: str(task_session_id).strip(),
            _PENDING_IDENTITY_CONV_KEY: str(conversation_id).strip(),
            _PENDING_IDENTITY_EMBED_KEY: db.dump_json(embedding),
            _PENDING_IDENTITY_SET_AT_KEY: now_iso(),
        }
    )


def _pending_identity_mark_prompted() -> None:
    db.set_mode_state({_PENDING_IDENTITY_PROMPT_AT_KEY: now_iso()})


def _pending_identity_clear() -> None:
    db.set_mode_state(
        {
            _PENDING_IDENTITY_TASK_KEY: "",
            _PENDING_IDENTITY_CONV_KEY: "",
            _PENDING_IDENTITY_EMBED_KEY: "",
            _PENDING_IDENTITY_SET_AT_KEY: "",
            _PENDING_IDENTITY_PROMPT_AT_KEY: "",
        }
    )


def _extract_identity_name(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    patterns = (
        r"^(?:det är|det ar|jag heter|mitt namn är|mitt namn ar)\s+(.+)$",
        r"^(?:it's|it is|i am|my name is)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, lowered)
        if not match:
            continue
        original_start = len(cleaned) - len(match.group(1))
        candidate = cleaned[original_start:].strip(" .,!?:;")
        candidate = _clean_athlete_name(candidate)
        if 2 <= len(candidate) <= 48:
            return candidate

    # Fallback: if user says only a short name.
    candidate = _clean_athlete_name(cleaned.strip(" .,!?:;"))
    if not re.fullmatch(r"[A-Za-zÅÄÖåäö' -]{2,48}", candidate):
        return ""
    if len(candidate.split()) <= 3:
        return candidate
    return ""


def _is_training_start_command(text: str) -> bool:
    t = str(text or "").lower()
    has_training_signal = bool(
        re.search(
            r"\b(reps?|repetitioner|armhäv|armhav|pushups?|squats?|knäböj|knaboj|situps?|planka|träning|traning|coacha)\b",
            t,
        )
    )
    has_start_signal = bool(
        re.search(r"\b(starta|börja|borja|kör|kor|räkna|rakna|hjälp mig|hjalp mig)\b", t)
    )
    return has_training_signal and has_start_signal


def _is_training_stop_command(text: str) -> bool:
    t = str(text or "").lower()
    return bool(
        re.search(
            r"\b(stopp|stop|paus|klart|avsluta|sluta|räcker|racker|stoppa träning|stoppa traning)\b",
            t,
        )
    )


def _derive_training_goal(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return "Räkna reps och ge kort coachning."
    return cleaned[:180]


def _reply_local_turn(
    *,
    conversation_id: str,
    source: str,
    user_text: str,
    assistant_text: str,
    route_id: str,
    intent: str,
    decision_reason: str,
    req_started: float,
    stt_to_aihub_ms: float | None,
    tts_event: str = "reply",
) -> dict[str, Any]:
    used_brain = "local"
    egress = "none"
    db.insert_turn(conversation_id, "user", user_text, source, used_brain=used_brain)
    db.insert_turn(
        conversation_id,
        "assistant",
        assistant_text,
        "aihub",
        used_brain=used_brain,
    )
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
    _set_mode(
        current_mode="conversation_mode",
        conversation_id=conversation_id,
        conversation_expires_at=expires_at,
    )
    db.log_route(route_id, source, intent, used_brain, egress, decision_reason)
    metric_id = db.insert_turn_metric(
        conversation_id=conversation_id,
        source=source,
        user_text=user_text,
        used_brain=used_brain,
        stt_to_aihub_ms=stt_to_aihub_ms,
        codex_ms=None,
        codex_search_used=None,
        camera_actions_ms=0.0,
        aihub_total_ms=_to_ms(time.monotonic() - req_started),
    )
    _tts_text = assistant_text
    _tts_source = source

    def _bg_local_speak() -> None:
        try:
            t_s = time.monotonic()
            ok, reason = speak_to_camera(_tts_text, _tts_source, event=tts_event)
            db.update_turn_metric_tts(
                metric_id,
                tts_request_ms=_to_ms(time.monotonic() - t_s),
                tts_ok=ok,
                tts_reason=reason,
            )
        except Exception as _exc:
            log.error("TTS background (_bg_local_speak) failed: %s", _exc)

    threading.Thread(target=_bg_local_speak, daemon=True).start()
    return {
        "ok": True,
        "assistant_text": assistant_text,
        "used_brain": used_brain,
        "actions": [],
        "egress": egress,
        "memory_items_used": 0,
        "camera_speak": {"ok": True, "reason": "async"},
    }


def _normalize_person_name_candidate(raw: str) -> str:
    candidate = _clean_athlete_name(raw.strip(" .,!?:;"))
    # Remove common trailing filler words.
    candidate = re.sub(r"\b(just nu|nu|snälla|snalla|tack)\b$", "", candidate, flags=re.IGNORECASE).strip()
    if not re.fullmatch(r"[A-Za-zÅÄÖåäö' -]{2,48}", candidate):
        return ""
    words = candidate.split()
    if not words or len(words) > 4:
        return ""
    return candidate


def _detect_person_search_name(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if re.search(r"\b(hitta|find|leta efter|letar efter|kolla på|titta på|ser du)\s+(mig|me|myself)\b", lowered):
        return "__self__"
    if re.search(r"\b(var är jag|var ar jag|where am i)\b", lowered):
        return "__self__"
    known_names = [k for k in db.list_athlete_names(100) if k.strip()]
    known_names_sorted = sorted(known_names, key=len, reverse=True)
    patterns = (
        r"(?:hitta|find)\s+personen\s+([A-Za-zÅÄÖåäö' -]{2,48})",
        r"(?:var är|var ar|where is|find|hitta|leta efter|letar efter|ser du)\s+([A-Za-zÅÄÖåäö' -]{2,48})",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if not match:
            continue
        start = raw.lower().find(match.group(1).lower())
        sliced = raw[start:] if start >= 0 else match.group(1)
        picked = _normalize_person_name_candidate(sliced)
        if picked:
            if picked.lower() in {"mig", "me", "myself", "jag"}:
                return "__self__"
            picked_lower = picked.lower()
            for known in known_names_sorted:
                kl = known.lower()
                if picked_lower == kl or picked_lower.startswith(f"{kl} "):
                    return known
            words = picked.split()
            if words and words[0].lower() in {"personen", "person"} and len(words) >= 2:
                picked = " ".join(words[1:])
                words = picked.split()
            if len(words) > 2:
                return words[0]
            if len(words) == 2 and words[1].lower() in {
                "nu",
                "now",
                "här",
                "har",
                "here",
            }:
                return words[0]
            return picked

    # Fallback: match against known athlete names in DB.
    lowered_text = lowered
    best = ""
    for known in known_names_sorted:
        k = known.strip()
        if not k:
            continue
        if k.lower() in lowered_text and len(k) > len(best):
            best = k
    return best


def _ptz_intent_for_direction(direction: str) -> str | None:
    mapping = {
        "left": "camera_ptz_left",
        "right": "camera_ptz_right",
        "up": "camera_ptz_up",
        "down": "camera_ptz_down",
        "center": "camera_reset",
        "reset": "camera_reset",
        "home": "camera_reset",
    }
    return mapping.get(str(direction or "").strip().lower())


def _vision_find_person_in_image(
    person_name: str,
    image_bytes: bytes,
    *,
    timeout_sec: int | None = None,
) -> tuple[bool, bool, str, float]:
    if str(person_name).strip() == "__self__":
        prompt = (
            "Du analyserar en kamerabild. "
            "Finns en person i bild? Om ja, var i bilden syns personen (vänster/höger/mitten, nära/långt bort). "
            "Svara ENDAST JSON: "
            "{\"found\":true/false,\"where\":\"kort platsbeskrivning\",\"confidence\":0.0-1.0}."
        )
    else:
        prompt = (
            f"Du analyserar en kamerabild. Leta efter personen med namn '{person_name}'. "
            "Svara ENDAST JSON: "
            "{\"found\":true/false,\"where\":\"kort platsbeskrivning\",\"confidence\":0.0-1.0}."
        )
    ok, text = ask_vision_model(
        prompt,
        image_bytes,
        timeout_sec=(
            timeout_sec
            if timeout_sec is not None and timeout_sec > 0
            else VISION_QUERY_OLLAMA_TIMEOUT_SEC
        ),
        num_predict=90,
    )
    if not ok:
        return False, False, "", 0.0
    chunk = _extract_json_object(text)
    if not chunk:
        # Minimal fallback if model ignores JSON constraint.
        lowered = text.lower()
        if "found" in lowered or "hitt" in lowered:
            return True, ("inte" not in lowered and "ej" not in lowered), text[:120], 0.5
        return True, False, "", 0.0
    try:
        parsed = json.loads(chunk)
    except json.JSONDecodeError:
        return True, False, "", 0.0
    found = bool(parsed.get("found", False))
    where = str(parsed.get("where", "")).strip()
    conf = _clamp01(parsed.get("confidence"), 0.0)
    return True, found, where, conf


def _camera_search_person(
    person_name: str,
    *,
    sweep_dirs: list[str] | None = None,
    settle_sec: float | None = None,
    min_conf: float | None = None,
    reset_after_search: bool | None = None,
    vision_timeout_sec: int | None = None,
) -> tuple[bool, str, float, bool, str]:
    found = False
    found_where = ""
    found_conf = 0.0
    had_frame = False
    last_frame_err = ""
    moved_camera = False
    sweep = [d for d in (sweep_dirs or CAMERA_LOOK_PERSON_SEARCH_SWEEP) if _ptz_intent_for_direction(d)]
    settle = (
        settle_sec
        if settle_sec is not None and settle_sec >= 0
        else CAMERA_LOOK_PERSON_SEARCH_SETTLE_SEC
    )
    conf_floor = (
        min_conf
        if min_conf is not None and min_conf >= 0
        else CAMERA_LOOK_PERSON_SEARCH_MIN_CONF
    )

    for direction in [""] + sweep:
        if direction:
            if CAMERA_LOOK_PERSON_SEARCH_RECENTER_EACH_STEP and moved_camera:
                execute_camera_intent("camera_reset")
                time.sleep(max(0.0, max(settle, CAMERA_LOOK_PERSON_SEARCH_RECENTER_SETTLE_SEC)))
            intent = _ptz_intent_for_direction(direction)
            if intent:
                if intent != "camera_reset":
                    moved_camera = True
                execute_camera_intent(intent)
                time.sleep(max(0.0, settle))
        frame_ok, frame_data, _frame_bgr, frame_source = _fetch_vision_frame()
        if not frame_ok:
            last_frame_err = frame_source
            continue
        had_frame = True
        ok_find, found_step, where_step, conf_step = _vision_find_person_in_image(
            person_name,
            frame_data,
            timeout_sec=vision_timeout_sec,
        )
        if not ok_find:
            continue
        if found_step and conf_step >= conf_floor:
            found = True
            found_where = where_step
            found_conf = conf_step
            break

    do_reset = (
        reset_after_search
        if reset_after_search is not None
        else CAMERA_LOOK_PERSON_SEARCH_RESET
    )
    if moved_camera and do_reset:
        execute_camera_intent("camera_reset")
    return found, found_where, found_conf, had_frame, last_frame_err


def _camera_look_answer(
    *,
    user_text: str,
    source: str,
    conversation_id: str,
    context: list[dict[str, Any]] | None = None,
    allow_codex_rewrite: bool = False,
    skip_person_search: bool = False,
) -> tuple[str, list[str], float]:
    executed_actions: list[str] = []
    codex_ms_added = 0.0

    if source == "audio" and not ALLOW_AUDIO_CAMERA_LOOK:
        executed_actions.append("camera_look_skipped_audio")
        return (
            "Jag kan titta via kameran när du ber explicit att jag ska titta.",
            executed_actions,
            codex_ms_added,
        )

    executed_actions.append("camera_look")
    person_name = (
        _detect_person_search_name(user_text)
        if CAMERA_LOOK_PERSON_SEARCH_ENABLED and not skip_person_search
        else ""
    )

    if person_name:
        executed_actions.append("camera_look_person_search")
        found, found_where, found_conf, had_frame, last_frame_err = _camera_search_person(
            person_name,
            reset_after_search=False,  # Don't reset — stay framed on person for VLM
        )
        subject = "dig" if person_name == "__self__" else person_name
        log.info(
            "Direct CAMERA_LOOK person_search: name=%s found=%s conf=%.2f",
            person_name,
            found,
            found_conf,
        )
        if not found:
            if had_frame:
                return f"Jag hittar inte {subject} just nu.", executed_actions, codex_ms_added
            else:
                reason = f": {last_frame_err}" if last_frame_err else ""
                return f"Jag kunde inte ta bild just nu{reason}.", executed_actions, codex_ms_added
        # Person found — fall through to VLM so we can answer the actual question

    # Collect 5 frames ~0.3s apart to give Qwen temporal context for motion.
    _MULTI_FRAME_COUNT = 5
    _MULTI_FRAME_INTERVAL = 0.3
    frame_ok, frame_data, _frame_bgr, frame_source = _fetch_vision_frame()
    if not frame_ok:
        return (
            "Jag kunde inte ta en bild just nu."
            if not frame_source
            else f"Jag kunde inte ta en bild just nu: {frame_source}",
            executed_actions,
            codex_ms_added,
        )
    extra_frames: list[bytes] = []
    for _ in range(_MULTI_FRAME_COUNT - 1):
        time.sleep(_MULTI_FRAME_INTERVAL)
        ok_f, data_f, _bgr_f, _src_f = _fetch_vision_frame()
        if ok_f:
            extra_frames.append(data_f)

    n_frames = 1 + len(extra_frames)
    span_sec = round(n_frames * _MULTI_FRAME_INTERVAL, 1)
    vlm_prompt = (
        f"Du analyserar {n_frames} bilder från en kamera tagna {_MULTI_FRAME_INTERVAL}s isär "
        f"(täcker {span_sec}s rörelse).\n"
        f"Fråga från användaren: \"{user_text}\"\n"
        "Svara på svenska. Beskriv vad personen gör och hur de rör sig. "
        "Var konkret om kläder, position och rörelse. Om osäker, säg det."
    )
    vlm_ok, vlm_text = ask_vision_model(
        vlm_prompt,
        frame_data,
        extra_frames=extra_frames,
        timeout_sec=VISION_QUERY_OLLAMA_TIMEOUT_SEC,
    )
    if not vlm_ok:
        return f"Jag kunde inte se just nu: {vlm_text}", executed_actions, codex_ms_added

    assistant_text = vlm_text
    if allow_codex_rewrite and not CAMERA_LOOK_SKIP_CODEX_REWRITE:
        vision_prompt = (
            f"Användaren frågade: \"{user_text}\"\n"
            f"Du tittade genom kameran och såg: {vlm_text}\n"
            f"Ge ett kort svar baserat på vad du ser."
        )
        codex2_started = time.monotonic()
        ok2, codex_text2, codex_meta2 = ask_codex(
            vision_prompt,
            conversation_id,
            context or [],
        )
        codex2_ms = float(codex_meta2.get("elapsed_sec", 0.0) or 0.0) * 1000.0
        if codex2_ms <= 0:
            codex2_ms = _to_ms(time.monotonic() - codex2_started)
        codex_ms_added += codex2_ms
        if ok2:
            assistant_text = codex_text2
    return assistant_text, executed_actions, codex_ms_added


def _execute_follow_intent(intent: str) -> tuple[str, list[str]]:
    """Execute follow start/stop using the software follow controller."""
    executed_actions: list[str] = []

    if intent == "camera_follow_stop":
        executed_actions.append("camera_follow_stop")
        if _soft_follow is not None:
            _soft_follow.stop()
        return "Följning avaktiverad.", executed_actions

    if intent == "camera_follow_start":
        executed_actions.append("camera_follow_start")
        if _soft_follow is None:
            return "Följning är inte tillgänglig.", executed_actions
        ok, reason = _soft_follow.start()
        if not ok and reason != "already_running":
            return f"Kunde inte starta följning: {reason}", executed_actions
        return "Automatisk följning aktiverad.", executed_actions

    return execute_camera_intent(intent), executed_actions


def _is_fitness_task(task_type: str, task_goal: str) -> bool:
    text = f"{task_type} {task_goal}".lower()
    return bool(
        re.search(
            r"\b(fitness|träning|traning|reps?|repetitioner|armhäv|armhav|pushups?|squats?|knäböj|knaboj|situps?)\b",
            text,
        )
    )


def _start_live_video_once() -> None:
    global _live_video_started, _live_video_feed, _rep_counter, _soft_follow
    if _live_video_started:
        return
    _live_video_started = True

    _rep_counter = SimpleVerticalRepCounter(
        min_amplitude=VISION_CV_MIN_AMPLITUDE,
        min_rep_interval_sec=VISION_CV_MIN_REP_INTERVAL_SEC,
    )

    if not VISION_VIDEO_ENABLED:
        log.info("Live vision video disabled by env")
        return

    _live_video_feed = LiveVideoFeed(
        rtsp_url=VISION_VIDEO_RTSP_URL,
        target_fps=VISION_VIDEO_TARGET_FPS,
        max_stale_sec=VISION_VIDEO_MAX_STALE_SEC,
        reconnect_sec=VISION_VIDEO_RECONNECT_SEC,
        jpeg_quality=VISION_VIDEO_JPEG_QUALITY,
    )
    _live_video_feed.start()

    if SOFT_FOLLOW_ENABLED:
        _soft_follow = SoftFollowController(
            frame_provider=_soft_follow_frame_provider,
            move_callback=_soft_follow_move_callback,
            on_lock_callback=_soft_follow_on_lock_callback,
            tick_sec=SOFT_FOLLOW_TICK_SEC,
            move_cooldown_sec=SOFT_FOLLOW_MOVE_COOLDOWN_SEC,
            x_deadzone=SOFT_FOLLOW_X_DEADZONE,
            y_deadzone=SOFT_FOLLOW_Y_DEADZONE,
            enable_tilt=SOFT_FOLLOW_ENABLE_TILT,
            invert_x=SOFT_FOLLOW_INVERT_X,
            invert_y=SOFT_FOLLOW_INVERT_Y,
            motion_fallback=SOFT_FOLLOW_MOTION_FALLBACK,
            motion_min_area_ratio=SOFT_FOLLOW_MOTION_MIN_AREA_RATIO,
            lost_sweep_after_sec=SOFT_FOLLOW_LOST_SWEEP_AFTER_SEC,
            lost_sweep_cooldown_sec=SOFT_FOLLOW_LOST_SWEEP_COOLDOWN_SEC,
            lost_sweep_pattern=[
                f"camera_ptz_{d}"
                for d in SOFT_FOLLOW_LOST_SWEEP_PATTERN
                if d in {"left", "right", "up", "down"}
            ],
            lock_lost_after_sec=SOFT_FOLLOW_LOCK_LOST_AFTER_SEC,
            lock_require_consecutive=SOFT_FOLLOW_LOCK_REQUIRE_CONSECUTIVE,
            lock_ack_after_consecutive=SOFT_FOLLOW_LOCK_ACK_AFTER_CONSECUTIVE,
            sweep_max_moves=SOFT_FOLLOW_SWEEP_MAX_MOVES,
            sweep_pause_sec=SOFT_FOLLOW_SWEEP_PAUSE_SEC,
            recover_max_moves=SOFT_FOLLOW_RECOVER_MAX_MOVES,
            smoothing_alpha=SOFT_FOLLOW_SMOOTHING_ALPHA,
            full_pan_steps=SOFT_FOLLOW_FULL_PAN_STEPS,
        )
        log.info("Soft follow initialized (enabled=%s, available=%s)", SOFT_FOLLOW_ENABLED, _soft_follow.available())


def _soft_follow_frame_provider() -> Any | None:
    if _live_video_feed is None:
        return None
    ok, _jpeg, frame_bgr, _reason = _live_video_feed.get_latest(SOFT_FOLLOW_FRAME_MAX_AGE_SEC)
    if not ok:
        return None
    return frame_bgr


def _soft_follow_move_callback(intent: str) -> str:
    return execute_camera_intent(intent)


def _soft_follow_on_lock_callback(source: str) -> None:
    if source != "person":
        return
    if not SOFT_FOLLOW_LOCK_ACK_TEXT:
        return

    def _speak_lock_ack() -> None:
        ok, reason = speak_to_camera(SOFT_FOLLOW_LOCK_ACK_TEXT, "audio", event="reply")
        if ok:
            log.info("Soft follow lock ack spoken")
        else:
            log.info("Soft follow lock ack skipped: %s", reason)

    threading.Thread(target=_speak_lock_ack, daemon=True).start()


def _fetch_vision_frame() -> tuple[bool, bytes, Any | None, str]:
    """Return (ok, image_bytes, frame_bgr, source)."""
    if _live_video_feed is not None:
        ok_live, img_live, frame_live, reason = _live_video_feed.get_latest(VISION_VIDEO_MAX_STALE_SEC)
        if ok_live:
            return True, img_live, frame_live, "live"
        if reason:
            log.debug("Live frame unavailable: %s", reason)

    snap_ok, snap_data = fetch_snapshot()
    if snap_ok:
        return True, snap_data, None, "snapshot"
    return False, snap_data, None, "snapshot_error"


def _use_cv_analyzer(task_type: str, task_goal: str) -> bool:
    if not VISION_CV_ENABLED:
        return False
    if _rep_counter is None or not _rep_counter.available():
        return False
    if VISION_ANALYZER_MODE == "vlm":
        return False
    if VISION_ANALYZER_MODE == "cv":
        return True
    # auto
    return _is_fitness_task(task_type, task_goal)


def _build_vision_tick_prompt(task_type: str, task_goal: str) -> str:
    return (
        "Du är en realtids-träningsanalysator. "
        "Analysera bilden och svara ENDAST JSON utan markdown.\n"
        "Schema:\n"
        "{"
        "\"activity\":\"kort id\","
        "\"rep_count\":heltal_eller_null,"
        "\"form_flags\":[\"kort flagga\"],"
        "\"fatigue_score\":0.0-1.0,"
        "\"confidence\":0.0-1.0,"
        "\"summary_sv\":\"kort svensk feedback\""
        "}\n"
        f"task_type={task_type}; task_goal={task_goal}.\n"
        "Sätt rep_count till null om ingen tydlig rep syns."
    )


def _run_vision_loop() -> None:
    last_tts_at = 0.0
    while True:
        try:
            if not VISION_LOOP_ENABLED:
                time.sleep(2.0)
                continue

            mode = _parse_mode()
            if mode.get("privacy_mode") or not mode.get("task_session_mode"):
                time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                continue

            task_session_id = str(mode.get("task_session_id", "")).strip()
            if not task_session_id:
                time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                continue

            task = db.get_task_session(task_session_id)
            if not task or not bool(task.get("active", 0)):
                time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                continue

            conversation_id = str(task.get("conversation_id", "")).strip()
            task_type = str(task.get("task_type", "")).strip() or "fitness_coach"
            task_goal = str(task.get("task_goal", "")).strip()

            frame_ok, frame_data, frame_bgr, frame_source = _fetch_vision_frame()
            if not frame_ok:
                time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                continue

            face_embedding = _build_face_embedding(frame_data)
            tick: dict[str, Any] = {}
            used_cv = False

            if frame_bgr is not None and _use_cv_analyzer(task_type, task_goal):
                tick = _rep_counter.process(  # type: ignore[union-attr]
                    frame_bgr,
                    task_goal=task_goal,
                    task_type=task_type,
                )
                used_cv = True
            else:
                prompt = _build_vision_tick_prompt(task_type, task_goal)
                vlm_ok, vlm_text = ask_vision_model(
                    prompt,
                    frame_data,
                    timeout_sec=VISION_LOOP_OLLAMA_TIMEOUT_SEC,
                    num_predict=120,
                )
                if not vlm_ok:
                    log.debug("Vision loop VLM failed (%s): %s", frame_source, vlm_text)
                    time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                    continue
                tick = _parse_vision_tick_payload(vlm_text)

            if (
                tick.get("rep_count") is None
                and not tick.get("form_flags")
                and float(tick.get("confidence", 0.0) or 0.0) < 0.35
            ):
                time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                continue

            result = vision_event(
                VisionEventRequest(
                    task_session_id=task_session_id,
                    activity=str(tick.get("activity") or VISION_ACTIVITY_DEFAULT),
                    rep_count=tick.get("rep_count"),
                    form_flags=list(tick.get("form_flags") or []),
                    fatigue_score=float(tick.get("fatigue_score") or 0.0),
                    confidence=float(tick.get("confidence") or 0.0),
                    summary_sv=str(tick.get("summary_sv") or ""),
                    face_embedding=face_embedding or None,
                    identity_min_score=IDENTITY_RESOLVE_MIN_SCORE,
                    identity_source="vision_loop_cv" if used_cv else "vision_loop_vlm",
                    depth_score=tick.get("depth_score"),
                    tempo_ms=tick.get("tempo_ms"),
                )
            )

            if not bool(result.get("ok", False)):
                if (
                    str(result.get("reason", "")) == "unknown_identity"
                    and face_embedding
                    and conversation_id
                ):
                    _pending_identity_set(
                        task_session_id=task_session_id,
                        conversation_id=conversation_id,
                        embedding=face_embedding,
                    )
                    pending = _pending_identity_get()
                    prompt_due = True
                    if pending and pending.get("prompt_at"):
                        age = (datetime.now(timezone.utc) - pending["prompt_at"]).total_seconds()
                        prompt_due = age >= VISION_IDENTITY_PROMPT_COOLDOWN_SEC
                    if prompt_due:
                        expires_at = (
                            datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)
                        ).isoformat()
                        _set_mode(
                            current_mode="conversation_mode",
                            conversation_id=conversation_id,
                            conversation_expires_at=expires_at,
                        )
                        speak_to_camera(
                            str(result.get("prompt_sv", "Vem tränar nu?")),
                            "audio",
                            event="reply",
                        )
                        _pending_identity_mark_prompted()
                time.sleep(max(0.5, VISION_LOOP_TICK_SEC))
                continue

            # Identity resolved / tracked successfully.
            _pending_identity_clear()
            tts_text = str(result.get("tts_text", "")).strip()
            now_ts = time.monotonic()
            if tts_text and (now_ts - last_tts_at) >= VISION_TTS_MIN_INTERVAL_SEC:
                speak_to_camera(tts_text, "audio", event="reply")
                last_tts_at = now_ts

        except Exception:
            log.exception("Vision loop crash")
        time.sleep(max(0.5, VISION_LOOP_TICK_SEC))


def _start_vision_loop_once() -> None:
    global _vision_loop_started
    if _vision_loop_started:
        return
    _vision_loop_started = True
    threading.Thread(target=_run_vision_loop, daemon=True).start()
    log.info("Vision loop started (enabled=%s, tick=%.2fs)", VISION_LOOP_ENABLED, VISION_LOOP_TICK_SEC)


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    response_pool.load_lru_from_db()
    if Image is None:
        log.warning("Pillow not available; face embedding disabled")
    _start_live_video_once()
    _start_vision_loop_once()


@app.get("/v1/health", dependencies=[Depends(_require_auth)])
def health() -> dict[str, Any]:
    video_status: dict[str, Any] = {"enabled": VISION_VIDEO_ENABLED, "started": _live_video_started}
    if _live_video_feed is not None:
        video_status.update(_live_video_feed.status())
    rep_status = {
        "enabled": VISION_CV_ENABLED,
        "mode": VISION_ANALYZER_MODE,
        "available": bool(_rep_counter is not None and _rep_counter.available()),
    }
    follow_status: dict[str, Any] = {
        "enabled": SOFT_FOLLOW_ENABLED,
        "autotrack_enabled": SOFT_FOLLOW_USE_CAMERA_AUTOTRACK,
    }
    if _soft_follow is not None:
        follow_status.update(_soft_follow.status())
    return {
        "ok": True,
        "service": "aihub",
        "version": APP_VERSION,
        "vision_video": video_status,
        "vision_rep_counter": rep_status,
        "soft_follow": follow_status,
    }


@app.get("/v1/integrations/ha/status", dependencies=[Depends(_require_auth)])
def ha_status() -> dict[str, Any]:
    cfg = load_ha_config()
    return {
        "ok": True,
        "ha_base_url": cfg.base_url,
        "ha_token_set": bool(cfg.token),
        "notify_service": cfg.notify_service,
        "spotify_entity_configured": bool(cfg.spotify_entity_id),
        "dance_uri_configured": bool(cfg.dance_spotify_uri),
    }


@app.get("/v1/spotify/auth")
def spotify_auth() -> RedirectResponse:
    """Redirect the browser to the Spotify authorization page."""
    url = build_auth_url()
    return RedirectResponse(url=url)


@app.get("/v1/spotify/callback")
def spotify_callback(code: str = Query(...), state: str = Query(...)) -> dict[str, Any]:
    """Handle the OAuth callback from Spotify and exchange the code for tokens."""
    ok = exchange_code(code, state)
    if not ok:
        raise HTTPException(status_code=400, detail="Authorization failed: state mismatch or token exchange error.")
    return {"ok": True, "message": "Authorization complete. You can close this tab."}


@app.get("/login")
def ha_oauth_proxy(code: str = Query(...), state: str = Query(...)) -> RedirectResponse:
    """Proxy Spotify OAuth callback to Home Assistant's auth endpoint.

    Spotcast uses http://127.0.0.1:8080/login as its redirect_uri (registered
    in spotcast's Spotify app). This endpoint receives the code+state from
    Spotify and forwards them to HA's local auth callback so HA can complete
    the PKCE OAuth flow.
    """
    ha_callback = f"http://127.0.0.1:8123/auth/external/callback?code={code}&state={state}"
    return RedirectResponse(url=ha_callback)


@app.get("/v1/spotify/status", dependencies=[Depends(_require_auth)])
def spotify_status() -> dict[str, Any]:
    return {"ok": True, "authorized": has_user_auth()}


class _SpotifyPlayBody(BaseModel):
    uri: str
    device_name: str = ""


@app.get("/v1/spotify/devices")
def spotify_devices() -> dict[str, Any]:
    """List available Spotify Connect devices."""
    from .spotify_client import _get_user_token
    import json, urllib.request
    token = _get_user_token()
    if not token:
        raise HTTPException(status_code=401, detail="no_user_token")
    req = urllib.request.Request(
        "https://api.spotify.com/v1/me/player/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


@app.post("/v1/spotify/play")
def spotify_play(body: _SpotifyPlayBody) -> dict[str, Any]:
    """Play a Spotify context URI on a named device via the Spotify Web API."""
    if not body.uri:
        raise HTTPException(status_code=400, detail="uri is required")
    ok, reason = play_context_uri(body.uri, body.device_name or None)
    if not ok:
        raise HTTPException(status_code=502, detail=reason)
    return {"ok": True}


@app.get("/v1/integrations/codex/status", dependencies=[Depends(_require_auth)])
def codex_status() -> dict[str, Any]:
    # This endpoint checks only routing intention in aihub.
    # Upstream codex-gateway health can be tested directly via its /v1/health.
    return {
        "ok": True,
        "routing_profile": os.getenv("AIHUB_ROUTING_PROFILE", "codex_first"),
        "codex_url": os.getenv("AIHUB_CODEX_URL", "http://codex-gateway:8090/v1/ask"),
        "codex_token_set": bool(os.getenv("AIHUB_CODEX_TOKEN", "").strip()),
    }


@app.get("/v1/mode", dependencies=[Depends(_require_auth)])
def get_mode() -> dict[str, Any]:
    mode = _parse_mode()
    return {
        "current_mode": mode["current_mode"],
        "privacy_mode": mode["privacy_mode"],
        "task_session_mode": mode["task_session_mode"],
        "conversation_id": mode["conversation_id"],
        "task_session_id": mode["task_session_id"],
    }


class ModeSetPayload(BaseModel):
    privacy_mode: bool | None = None
    task_session_mode: bool | None = None


class ModeUpdateRequest(BaseModel):
    set: ModeSetPayload
    reason: str = Field(default="manual_update")


@app.post("/v1/mode", dependencies=[Depends(_require_auth)])
def set_mode(req: ModeUpdateRequest) -> dict[str, Any]:
    mode_before = _parse_mode()
    mode_after = {
        "privacy_mode": mode_before["privacy_mode"]
        if req.set.privacy_mode is None
        else req.set.privacy_mode,
        "task_session_mode": mode_before["task_session_mode"]
        if req.set.task_session_mode is None
        else req.set.task_session_mode,
    }

    next_current_mode = mode_before["current_mode"]
    if mode_after["task_session_mode"]:
        next_current_mode = "task_session_mode"
    elif mode_before["conversation_id"]:
        next_current_mode = "conversation_mode"
    else:
        next_current_mode = "idle"

    _set_mode(
        current_mode=next_current_mode,
        privacy_mode=mode_after["privacy_mode"],
        task_session_mode=mode_after["task_session_mode"],
    )
    return {"ok": True, "applied": mode_after, "reason": req.reason}


class CameraEventRefs(BaseModel):
    clip_path: str | None = None
    snapshot_path: str | None = None


class CameraEventRequest(BaseModel):
    event_id: str
    type: str
    camera: str
    confidence: float = 0.0
    zone: str | None = None
    timestamp: str | None = None
    refs: CameraEventRefs | None = None


@app.post("/v1/events/camera", dependencies=[Depends(_require_auth)])
def camera_event(req: CameraEventRequest) -> dict[str, Any]:
    mode = _parse_mode()
    if mode["privacy_mode"]:
        route_id = "R10"
        actions = ["log_minimal"]
        egress = "none"
        db.log_route(route_id, "camera", req.type, "local", egress, "privacy_mode_on")
        return {
            "ok": True,
            "route_id": route_id,
            "actions": actions,
            "egress": egress,
            "executed_actions": [],
            "skipped_actions": ["privacy_mode_on"],
        }

    event_type = req.type.lower()
    if "dog" in event_type:
        route_id, actions, egress = "R1", ["save_clip", "notify_phone"], "none"
    elif "dance" in event_type:
        route_id, actions, egress = "R2", ["start_spotify_track"], "none"
    elif "morning" in event_type or "presence" in event_type:
        route_id, actions, egress = (
            "R3",
            ["tts_greeting", "open_short_conversation_window"],
            "text-only",
        )
    elif "person" in event_type:
        route_id, actions, egress = "R4a", ["play_arrival_track"], "none"
    elif "workout" in event_type:
        route_id, actions, egress = "R4b", ["play_workout_track"], "none"
    else:
        route_id, actions, egress = "R0", ["log_only"], "none"
    db.log_route(route_id, "camera", req.type, "local", egress, "camera_route")
    executed_actions, skipped_actions = execute_route_actions(
        route_id,
        {"camera": req.camera, "event_type": req.type},
    )
    return {
        "ok": True,
        "route_id": route_id,
        "actions": actions,
        "egress": egress,
        "executed_actions": executed_actions,
        "skipped_actions": skipped_actions,
    }


class AudioWakeRequest(BaseModel):
    device: str
    wake_phrase: str
    timestamp: str | None = None


@app.post("/v1/events/audio/wake", dependencies=[Depends(_require_auth)])
def audio_wake(req: AudioWakeRequest) -> dict[str, Any]:
    cancel_followup()  # T024: suppress any pending follow-up on new turn
    reused = False
    conversation_id = ""
    if STICKY_CONVERSATION:
        mode = _parse_mode()
        current_id = str(mode.get("conversation_id", "")).strip()
        if current_id:
            conversation_id = current_id
        else:
            source_filter = None if STICKY_CONVERSATION_SOURCE in {"", "any"} else STICKY_CONVERSATION_SOURCE
            conversation_id = db.get_latest_conversation_id(source_filter)
        reused = bool(conversation_id)
    if not conversation_id:
        conversation_id = f"conv-{uuid.uuid4().hex[:12]}"

    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
    _set_mode(
        current_mode="conversation_mode",
        conversation_id=conversation_id,
        conversation_expires_at=expires_at,
    )
    db.log_route(
        "R4",
        "audio",
        "wake_word",
        "local",
        "none",
        "wake_word_reused" if reused else "wake_word_opened",
    )
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "mode": "conversation_mode",
        "ttl_seconds": CONVERSATION_TTL_SEC,
        "reused_conversation": reused,
    }


class ConversationTurnRequest(BaseModel):
    conversation_id: str
    source: Literal["audio", "text"] = "audio"
    text: str
    allow_codex: bool = True
    contains_camera_derived_text: bool = False
    timestamp: str | None = None


@app.post("/v1/conversation/turn", dependencies=[Depends(_require_auth)])
def conversation_turn(req: ConversationTurnRequest) -> dict[str, Any]:
    cancel_followup()  # T024: suppress any pending follow-up on new turn
    global _last_ollama_vision_at
    req_started = time.monotonic()
    req_received_at = datetime.now(timezone.utc)
    wake_hit, text_without_wake = _extract_wake_text(req.text)
    mode = _parse_mode()
    if req.source == "audio" and AUDIO_REQUIRE_WAKE_OR_ACTIVE and not wake_hit:
        is_active, reason = _is_active_audio_conversation(req.conversation_id, mode)
        if not is_active:
            db.log_route("R11", "audio", "audio_ignored", "local", "none", f"audio_gate:{reason}")
            return {
                "ok": True,
                "ignored": True,
                "reason": f"audio_gate:{reason}",
                "assistant_text": "",
                "used_brain": "local",
                "actions": [],
                "egress": "none",
                "memory_items_used": 0,
                "camera_speak": {"ok": False, "reason": "ignored"},
            }

    user_text = text_without_wake.strip() if wake_hit else req.text.strip()
    if not user_text:
        user_text = req.text.strip()

    stt_to_aihub_ms: float | None = None
    if req.timestamp:
        ts = _parse_iso(req.timestamp)
        if ts:
            stt_to_aihub_ms = _to_ms((req_received_at - ts).total_seconds())
            _warn_if_over_budget(
                "stt_to_aihub",
                stt_to_aihub_ms,
                LATENCY_BUDGET_STT_TO_AIHUB_MS,
            )

    codex_ms_total: float | None = None
    codex_search_used: bool | None = None

    # Saying only the wake phrase should provide a clear spoken acknowledgement.
    if wake_hit and text_without_wake.strip() == "":
        used_brain = "local"
        egress = "none"
        pool_ctx = _build_pool_context(req.conversation_id)  # T013
        assistant_text = _build_wake_response(pool_ctx)  # T013
        db.insert_turn(req.conversation_id, "user", req.text, req.source, used_brain=used_brain)
        db.insert_turn(
            req.conversation_id,
            "assistant",
            assistant_text,
            "aihub",
            used_brain=used_brain,
        )
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
        _set_mode(
            current_mode="conversation_mode",
            conversation_id=req.conversation_id,
            conversation_expires_at=expires_at,
        )
        db.log_route("R5", "audio", "wake_ack", used_brain, egress, "wake_ack")
        metric_id = db.insert_turn_metric(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            used_brain=used_brain,
            stt_to_aihub_ms=stt_to_aihub_ms,
            codex_ms=None,
            codex_search_used=None,
            camera_actions_ms=0.0,
            aihub_total_ms=_to_ms(time.monotonic() - req_started),
        )
        _ack_text = assistant_text
        _ack_source = req.source
        def _bg_wake_ack_speak() -> None:
            try:
                t_s = time.monotonic()
                ok, reason = speak_to_camera(_ack_text, _ack_source, event="wake_ack")
                db.update_turn_metric_tts(
                    metric_id,
                    tts_request_ms=_to_ms(time.monotonic() - t_s),
                    tts_ok=ok,
                    tts_reason=reason,
                )
            except Exception as _exc:
                log.error("TTS background (_bg_wake_ack_speak) failed: %s", _exc)
        threading.Thread(target=_bg_wake_ack_speak, daemon=True).start()
        return {
            "ok": True,
            "assistant_text": assistant_text,
            "used_brain": used_brain,
            "actions": [],
            "egress": egress,
            "memory_items_used": 0,
            "camera_speak": {"ok": True, "reason": "async"},
        }

    pending_identity = _pending_identity_get()
    if (
        req.source == "audio"
        and pending_identity
        and str(pending_identity.get("conversation_id", "")) == req.conversation_id
    ):
        candidate_name = _extract_identity_name(user_text)
        if candidate_name:
            try:
                db.remember_identity(
                    athlete_name=candidate_name,
                    embedding=list(pending_identity.get("embedding") or []),
                    source="voice_identity",
                )
            except ValueError:
                _pending_identity_clear()
                candidate_name = ""
        if candidate_name:
            db.bind_identity_to_conversation(
                conversation_id=req.conversation_id,
                athlete_name=candidate_name,
                confidence=1.0,
                source="voice_identity",
            )
            task_session_id = str(pending_identity.get("task_session_id", "")).strip()
            if task_session_id:
                db.bind_identity_to_task(
                    task_session_id=task_session_id,
                    athlete_name=candidate_name,
                    confidence=1.0,
                    source="voice_identity",
                )
            _pending_identity_clear()

            used_brain = "local"
            egress = "none"
            _bind_ctx = PoolContext(  # T018
                time_of_day=_get_time_of_day(),
                recency=False,
                identity_name=candidate_name,
                companion_mode=True,
                last_action="identity_bind",
            )
            assistant_text = response_pool.pick("identity_bind", _bind_ctx)  # T018
            db.insert_turn(req.conversation_id, "user", user_text, req.source, used_brain=used_brain)
            db.insert_turn(
                req.conversation_id,
                "assistant",
                assistant_text,
                "aihub",
                used_brain=used_brain,
            )
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
            _set_mode(
                current_mode="conversation_mode",
                conversation_id=req.conversation_id,
                conversation_expires_at=expires_at,
            )
            db.log_route("R9", "audio", "identity_bind", used_brain, egress, "voice_identity_bound")
            metric_id = db.insert_turn_metric(
                conversation_id=req.conversation_id,
                source=req.source,
                user_text=user_text,
                used_brain=used_brain,
                stt_to_aihub_ms=stt_to_aihub_ms,
                codex_ms=None,
                codex_search_used=None,
                camera_actions_ms=0.0,
                aihub_total_ms=_to_ms(time.monotonic() - req_started),
            )
            _ack_text = assistant_text
            _ack_source = req.source

            def _bg_identity_ack_speak() -> None:
                try:
                    t_s = time.monotonic()
                    ok, reason = speak_to_camera(_ack_text, _ack_source, event="reply")
                    db.update_turn_metric_tts(
                        metric_id,
                        tts_request_ms=_to_ms(time.monotonic() - t_s),
                        tts_ok=ok,
                        tts_reason=reason,
                    )
                except Exception as _exc:
                    log.error("TTS background (_bg_identity_ack_speak) failed: %s", _exc)

            threading.Thread(target=_bg_identity_ack_speak, daemon=True).start()
            return {
                "ok": True,
                "assistant_text": assistant_text,
                "used_brain": used_brain,
                "actions": ["identity_bound"],
                "egress": egress,
                "memory_items_used": 0,
                "camera_speak": {"ok": True, "reason": "async"},
            }

    mode = _parse_mode()
    if mode.get("task_session_mode") and _is_training_stop_command(user_text):
        task_session_id = str(mode.get("task_session_id", "")).strip()
        if task_session_id:
            try:
                task_stop(TaskStopRequest(task_session_id=task_session_id, reason="voice_command"))
            except HTTPException:
                pass
        _workout_uri = os.getenv("AIHUB_SPOTIFY_WORKOUT_URI", "").strip()
        if _workout_uri:
            threading.Thread(
                target=lambda: pause_spotify(load_ha_config()), daemon=True
            ).start()
        _stop_ctx = _build_pool_context(req.conversation_id)  # T016, T025
        _stop_text = response_pool.pick("training_stop", _stop_ctx)  # T016
        if _stop_ctx.companion_mode and random.random() < FOLLOWUP_PROBABILITY:  # T025
            _followup_text = response_pool.pick("workout_followup", _stop_ctx)
            schedule_followup(_followup_text, req.source)
        return _reply_local_turn(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            assistant_text=_stop_text,
            route_id="R7",
            intent="task_stop",
            decision_reason="voice_task_stop",
            req_started=req_started,
            stt_to_aihub_ms=stt_to_aihub_ms,
        )

    if not mode.get("task_session_mode") and _is_training_start_command(user_text):
        explicit_name = _extract_identity_name(user_text)
        athlete_name = _resolve_athlete_name(
            explicit_name=explicit_name or None,
            conversation_id=req.conversation_id,
        )
        if not athlete_name:
            return _reply_local_turn(
                conversation_id=req.conversation_id,
                source=req.source,
                user_text=user_text,
                assistant_text="Absolut. Vem tränar nu? Säg till exempel: det är Sebastian.",
                route_id="R6",
                intent="task_start",
                decision_reason="identity_required_for_task_start",
                req_started=req_started,
                stt_to_aihub_ms=stt_to_aihub_ms,
            )
        started = task_start(
            TaskStartRequest(
                conversation_id=req.conversation_id,
                task_type="fitness_coach",
                task_goal=_derive_training_goal(user_text),
                athlete_name=athlete_name,
            )
        )
        if not bool(started.get("ok", False)):
            return _reply_local_turn(
                conversation_id=req.conversation_id,
                source=req.source,
                user_text=user_text,
                assistant_text=str(started.get("prompt_sv", "Jag behöver veta vem som tränar.")),
                route_id="R6",
                intent="task_start",
                decision_reason="task_start_rejected",
                req_started=req_started,
                stt_to_aihub_ms=stt_to_aihub_ms,
            )
        _workout_uri = os.getenv("AIHUB_SPOTIFY_WORKOUT_URI", "").strip()
        if _workout_uri:
            threading.Thread(
                target=lambda: play_spotify_uri(load_ha_config(), _workout_uri), daemon=True
            ).start()
        _start_ctx = _build_pool_context(req.conversation_id)  # T017
        _start_ctx = PoolContext(
            time_of_day=_start_ctx.time_of_day,
            recency=_start_ctx.recency,
            identity_name=athlete_name,
            companion_mode=_start_ctx.companion_mode,
            last_action="training_start",
        )
        return _reply_local_turn(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            assistant_text=response_pool.pick("training_start_named", _start_ctx),  # T017
            route_id="R6",
            intent="task_start",
            decision_reason="voice_task_start",
            req_started=req_started,
            stt_to_aihub_ms=stt_to_aihub_ms,
        )

    # Minimal mode pre-flight: detect verbal mode switch before any intent routing (T034)
    _mode_switch = _detect_minimal_mode_switch(user_text)
    if _mode_switch is not None:
        _identity = db.get_conversation_identity(req.conversation_id)
        _person_id = int(_identity["person_id"]) if _identity else None
        if _person_id is not None:
            _new_pref = "minimal" if _mode_switch == "minimal_mode_on" else "full"
            db.set_companion_pref(_person_id, _new_pref)
        _ack_mode_text = MINIMAL_MODE_ON_ACK_TEXT if _mode_switch == "minimal_mode_on" else MINIMAL_MODE_OFF_ACK_TEXT
        log.info("Minimal mode switch: %s (person_id=%s)", _mode_switch, _person_id)
        return _reply_local_turn(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            assistant_text=_ack_mode_text,
            route_id="R14",
            intent=_mode_switch,
            decision_reason="minimal_mode_switch",
            req_started=req_started,
            stt_to_aihub_ms=stt_to_aihub_ms,
        )

    # Light control pre-flight (R15) — before camera intent to avoid ambiguity
    _light_intent = _detect_light_intent(user_text)
    if _light_intent is not None:
        _ha_cfg = load_ha_config()
        _light_ok, _light_reason = control_lights(_ha_cfg, **_light_intent)
        _cmd = _light_intent.get("command", "on")
        if not _light_ok:
            _light_ack = response_pool.pick("error_generic", _build_pool_context(req.conversation_id))
            log.warning("Light control failed (%s): %s", _cmd, _light_reason)
        elif _cmd == "off":
            _light_ack = "Lamporna är släckta."
        elif "brightness_pct" in _light_intent:
            _light_ack = f"Ljuset är satt till {_light_intent['brightness_pct']} procent."
        elif "rgb_color" in _light_intent:
            _light_ack = "Färgen är ändrad."
        elif "color_temp_kelvin" in _light_intent:
            _k = _light_intent["color_temp_kelvin"]
            _light_ack = "Varmt ljus." if _k <= 3000 else "Svalt ljus." if _k >= 4500 else "Neutralt ljus."
        else:
            _light_ack = "Lamporna är tända."
        return _reply_local_turn(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            assistant_text=_light_ack,
            route_id="R15",
            intent="light_control",
            decision_reason=f"light:{_cmd}",
            req_started=req_started,
            stt_to_aihub_ms=stt_to_aihub_ms,
        )

    # Air purifier control/query (R16)
    _air_intent = _detect_air_intent(user_text)
    if _air_intent is not None:
        _ha_cfg = load_ha_config()
        if _air_intent["kind"] == "query":
            _val, _reason = get_ha_state(_ha_cfg, _air_intent["sensor"])
            if _val is not None:
                _air_ack = f"{_air_intent['label']} är {_val} {_air_intent['unit']}."
            else:
                _air_ack = response_pool.pick("error_generic", _build_pool_context(req.conversation_id))
        else:
            _ok, _reason = control_air_purifier(_ha_cfg, _air_intent["command"])
            _cmd = _air_intent["command"]
            if not _ok:
                _air_ack = response_pool.pick("error_generic", _build_pool_context(req.conversation_id))
                log.warning("Air purifier control failed (%s): %s", _cmd, _reason)
            elif _cmd == "off":
                _air_ack = "Luftrenaren är avstängd."
            elif _cmd == "on":
                _air_ack = "Luftrenaren är påslagen."
            elif _cmd == "turbo":
                _air_ack = "Luftrenaren körs på full effekt."
            elif _cmd == "sleep":
                _air_ack = "Luftrenaren är i nattläge."
            else:
                _air_ack = "Klart."
        return _reply_local_turn(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            assistant_text=_air_ack,
            route_id="R16",
            intent="air_purifier",
            decision_reason=f"air:{_air_intent['kind']}",
            req_started=req_started,
            stt_to_aihub_ms=stt_to_aihub_ms,
        )

    camera_intent = detect_camera_intent(user_text)
    # If no fast-path intent matched, ask Ollama to decide whether a camera look
    # is needed.  This catches natural-language vision queries ("vad tycker du om
    # min dans?", "är jag snygg?") without a brittle keyword list.
    # A cooldown prevents echo loops where the TTS answer is picked up by the
    # microphone and re-classified as a new vision query.
    _ollama_classified_vision = False
    if camera_intent == "none":
        with _ollama_vision_lock:
            now = time.monotonic()
            _cooldown_remaining = _OLLAMA_VISION_COOLDOWN_SEC - (now - _last_ollama_vision_at)
        if _cooldown_remaining <= 0:
            if classify_as_vision(user_text):
                log.debug("Ollama classified %r as vision_query", user_text)
                camera_intent = "vision_query"
                _ollama_classified_vision = True
        else:
            log.debug(
                "Ollama vision cooldown active (%.0fs left), skipping classify",
                _cooldown_remaining,
            )
    if camera_intent in {"camera_follow_start", "camera_follow_stop"}:
        actions_started = time.monotonic()
        cam_result, follow_actions = _execute_follow_intent(camera_intent)
        camera_actions_ms = _to_ms(time.monotonic() - actions_started)
        used_brain = "local"
        egress = "none"
        _follow_ctx = _build_pool_context(req.conversation_id)  # T015
        if camera_intent == "camera_follow_start":
            assistant_text = response_pool.pick("follow_start", _follow_ctx)
        else:
            assistant_text = response_pool.pick("follow_stop", _follow_ctx)
        db.insert_turn(req.conversation_id, "user", user_text, req.source, used_brain=used_brain)
        db.insert_turn(
            req.conversation_id,
            "assistant",
            assistant_text,
            "aihub",
            used_brain=used_brain,
        )
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
        _set_mode(
            current_mode="conversation_mode",
            conversation_id=req.conversation_id,
            conversation_expires_at=expires_at,
        )
        db.log_route("R12", req.source, camera_intent, used_brain, egress, "direct_camera_intent")
        metric_id = db.insert_turn_metric(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            used_brain=used_brain,
            stt_to_aihub_ms=stt_to_aihub_ms,
            codex_ms=None,
            codex_search_used=None,
            camera_actions_ms=camera_actions_ms,
            aihub_total_ms=_to_ms(time.monotonic() - req_started),
        )
        _tts_text = assistant_text
        _tts_source = req.source

        def _bg_follow_speak() -> None:
            try:
                t_s = time.monotonic()
                ok, reason = speak_to_camera(_tts_text, _tts_source, event="reply")
                db.update_turn_metric_tts(
                    metric_id,
                    tts_request_ms=_to_ms(time.monotonic() - t_s),
                    tts_ok=ok,
                    tts_reason=reason,
                )
            except Exception as _exc:
                log.error("TTS background (_bg_follow_speak) failed: %s", _exc)

        threading.Thread(target=_bg_follow_speak, daemon=True).start()
        return {
            "ok": True,
            "assistant_text": assistant_text,
            "used_brain": used_brain,
            "actions": follow_actions,
            "egress": egress,
            "memory_items_used": 0,
            "camera_speak": {"ok": True, "reason": "async"},
        }

    if camera_intent in {"spotify_play", "spotify_pause", "spotify_next", "spotify_prev", "spotify_status"}:
        actions_started = time.monotonic()
        _ha_cfg = load_ha_config()
        _spot_ctx = _build_pool_context(req.conversation_id)  # T014
        if camera_intent == "spotify_play":
            ok, reason = play_spotify(_ha_cfg)
            assistant_text = response_pool.pick("spotify_play", _spot_ctx) if ok else response_pool.pick("error_generic", _spot_ctx)
        elif camera_intent == "spotify_pause":
            ok, reason = pause_spotify(_ha_cfg)
            assistant_text = response_pool.pick("spotify_pause", _spot_ctx) if ok else response_pool.pick("error_generic", _spot_ctx)
        elif camera_intent == "spotify_next":
            ok, reason = next_track(_ha_cfg)
            assistant_text = response_pool.pick("spotify_next", _spot_ctx) if ok else response_pool.pick("error_generic", _spot_ctx)
        elif camera_intent == "spotify_prev":
            ok, reason = prev_track(_ha_cfg)
            assistant_text = response_pool.pick("spotify_prev", _spot_ctx) if ok else response_pool.pick("error_generic", _spot_ctx)
        elif camera_intent == "spotify_status":
            track = get_current_track(_ha_cfg)
            assistant_text = f"Det spelas {track}." if track else "Ingenting spelas just nu."
        else:
            assistant_text = "Okänt Spotify-kommando."
        camera_actions_ms = _to_ms(time.monotonic() - actions_started)
        used_brain = "local"
        egress = "none"
        db.insert_turn(req.conversation_id, "user", user_text, req.source, used_brain=used_brain)
        db.insert_turn(req.conversation_id, "assistant", assistant_text, "aihub", used_brain=used_brain)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
        _set_mode(
            current_mode="conversation_mode",
            conversation_id=req.conversation_id,
            conversation_expires_at=expires_at,
        )
        db.log_route("R13", req.source, camera_intent, used_brain, egress, "direct_spotify_intent")
        metric_id = db.insert_turn_metric(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            used_brain=used_brain,
            stt_to_aihub_ms=stt_to_aihub_ms,
            codex_ms=None,
            codex_search_used=None,
            camera_actions_ms=camera_actions_ms,
            aihub_total_ms=_to_ms(time.monotonic() - req_started),
        )
        _tts_text = assistant_text
        _tts_source = req.source

        def _bg_spotify_speak() -> None:
            try:
                t_s = time.monotonic()
                ok2, reason2 = speak_to_camera(_tts_text, _tts_source, event="reply")
                db.update_turn_metric_tts(
                    metric_id,
                    tts_request_ms=_to_ms(time.monotonic() - t_s),
                    tts_ok=ok2,
                    tts_reason=reason2,
                )
            except Exception as _exc:
                log.error("TTS background (_bg_spotify_speak) failed: %s", _exc)

        threading.Thread(target=_bg_spotify_speak, daemon=True).start()
        return {
            "ok": True,
            "assistant_text": assistant_text,
            "used_brain": used_brain,
            "actions": [camera_intent],
            "egress": egress,
            "memory_items_used": 0,
            "camera_speak": {"ok": True, "reason": "async"},
        }

    if camera_intent == "vision_query":
        if req.source == "audio" and VISION_QUERY_ACK_TEXT:
            _ack_text_vision = VISION_QUERY_ACK_TEXT
            _ack_source_vision = req.source
            def _bg_vision_ack() -> None:
                try:
                    speak_to_camera(_ack_text_vision, _ack_source_vision, event="processing_ack")
                except Exception as _exc:
                    log.error("TTS background (_bg_vision_ack) failed: %s", _exc)
            threading.Thread(target=_bg_vision_ack, daemon=True).start()
        actions_started = time.monotonic()
        assistant_text, executed_actions, _ = _camera_look_answer(
            user_text=user_text,
            source=req.source,
            conversation_id=req.conversation_id,
            context=[],
            allow_codex_rewrite=False,
            # Ollama-classified queries skip PTZ person-search — avoids 60s sweeps
            # that outlast the echo guard and cause TTS→mic feedback loops.
            skip_person_search=_ollama_classified_vision,
        )
        if _ollama_classified_vision:
            with _ollama_vision_lock:
                _last_ollama_vision_at = time.monotonic()
        camera_actions_ms = _to_ms(time.monotonic() - actions_started)
        used_brain = "local"
        egress = "none"
        db.insert_turn(req.conversation_id, "user", user_text, req.source, used_brain=used_brain)
        db.insert_turn(
            req.conversation_id,
            "assistant",
            assistant_text,
            "aihub",
            used_brain=used_brain,
        )
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
        _set_mode(
            current_mode="conversation_mode",
            conversation_id=req.conversation_id,
            conversation_expires_at=expires_at,
        )
        db.log_route("R13", req.source, "vision_query", used_brain, egress, "vision_query")
        metric_id = db.insert_turn_metric(
            conversation_id=req.conversation_id,
            source=req.source,
            user_text=user_text,
            used_brain=used_brain,
            stt_to_aihub_ms=stt_to_aihub_ms,
            codex_ms=None,
            codex_search_used=None,
            camera_actions_ms=camera_actions_ms,
            aihub_total_ms=_to_ms(time.monotonic() - req_started),
        )
        _tts_text = assistant_text
        _tts_source = req.source

        def _bg_vision_speak() -> None:
            try:
                t_s = time.monotonic()
                ok, reason = speak_to_camera(_tts_text, _tts_source, event="reply")
                db.update_turn_metric_tts(
                    metric_id,
                    tts_request_ms=_to_ms(time.monotonic() - t_s),
                    tts_ok=ok,
                    tts_reason=reason,
                )
            except Exception as _exc:
                log.error("TTS background (_bg_vision_speak) failed: %s", _exc)

        threading.Thread(target=_bg_vision_speak, daemon=True).start()
        return {
            "ok": True,
            "assistant_text": assistant_text,
            "used_brain": used_brain,
            "actions": executed_actions,
            "egress": egress,
            "memory_items_used": 0,
            "camera_speak": {"ok": True, "reason": "async"},
        }

    # If wake phrase is present with a following query, force Codex path (if allowed).
    force_codex = wake_hit and req.allow_codex
    use_codex = force_codex or should_use_codex(
        text=user_text,
        allow_codex=req.allow_codex,
        contains_camera_derived_text=req.contains_camera_derived_text,
    )

    used_brain = "codex" if use_codex else "local"
    egress = "text-only" if use_codex else "none"

    db.insert_turn(req.conversation_id, "user", user_text, req.source, used_brain=used_brain)
    context: list[dict[str, Any]] = []
    attach_db_context = bool(use_codex and _should_attach_db_context_for_codex(user_text))
    if attach_db_context:
        base_context = db.get_memory_context(req.conversation_id, 6)
        extra_relevant = db.search_relevant_memory(
            user_text,
            k=MEMORY_RELEVANT_K,
            current_conversation_id=req.conversation_id,
            lookback=MEMORY_LOOKBACK,
        )
        extra_recent: list[dict[str, Any]] = []
        if _is_memory_recall_query(user_text):
            extra_recent = db.get_recent_turns(
                hours=MEMORY_RECALL_HOURS,
                limit=MEMORY_RECALL_LIMIT,
                current_conversation_id=req.conversation_id,
            )

        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in extra_recent + extra_relevant + base_context:
            key = (
                str(item.get("timestamp", "")),
                str(item.get("role", "")),
                str(item.get("text", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        context = merged[-_codex_db_context_limit(user_text):]
        log.info("Codex context mode: db+thread (items=%d)", len(context))
    else:
        log.info("Codex context mode: thread_only (items=0)")

    t0 = time.monotonic()
    if use_codex:
        if (
            PROCESSING_ACK_ENABLED
            and req.source == "audio"
            and should_send_processing_ack(user_text)
        ):
            _proc_ctx = _build_pool_context(req.conversation_id)  # T019
            _proc_ack_text = response_pool.pick("processing_ack", _proc_ctx)
            _proc_src = req.source
            threading.Thread(
                target=lambda: speak_to_camera(
                    _proc_ack_text,
                    _proc_src,
                    event="processing_ack",
                ),
                daemon=True,
            ).start()

        codex_call_started = time.monotonic()
        _codex_pool_ctx = _build_pool_context(req.conversation_id)  # T030
        _session_ctx = {
            "identity_name": _codex_pool_ctx.identity_name,
            "time_of_day": _codex_pool_ctx.time_of_day,
            "recent_activity": None,
            "companion_mode": _codex_pool_ctx.companion_mode,
        }
        ok, codex_text, codex_meta = ask_codex(user_text, req.conversation_id, context, session_ctx=_session_ctx)
        t_codex = time.monotonic() - t0
        codex_ms = float(codex_meta.get("elapsed_sec", 0.0) or 0.0) * 1000.0
        if codex_ms <= 0:
            codex_ms = _to_ms(time.monotonic() - codex_call_started)
        codex_ms_total = codex_ms if codex_ms_total is None else codex_ms_total + codex_ms
        _warn_if_over_budget("codex_call", codex_ms, LATENCY_BUDGET_CODEX_MS)
        codex_search_used = bool(codex_meta.get("search_used", False))
        log.info(
            "Codex call took %.1fs (ok=%s, backend=%s, search=%s)",
            t_codex,
            ok,
            codex_meta.get("backend", ""),
            codex_search_used,
        )
        if ok:
            assistant_text = codex_text
        else:
            used_brain = "local"
            egress = "none"
            _err_ctx = _build_pool_context(req.conversation_id)  # T020
            assistant_text = response_pool.pick("error_generic", _err_ctx) + f" Detalj: {codex_text}"
    else:
        assistant_text = "Jag kör lokalt läge."

    actions_started = time.monotonic()
    # ------------------------------------------------------------------
    # Tool-tag execution: parse Codex response for action tags.
    # ------------------------------------------------------------------
    executed_actions: list[str] = []

    # PTZ: [PTZ:left], [PTZ:right], [PTZ:up], [PTZ:down]
    ptz_map = {
        "left": "camera_ptz_left",
        "right": "camera_ptz_right",
        "up": "camera_ptz_up",
        "down": "camera_ptz_down",
    }
    for ptz_match in re.finditer(r"\[PTZ:(\w+)\]", assistant_text, re.IGNORECASE):
        direction = ptz_match.group(1).lower()
        intent = ptz_map.get(direction)
        if intent:
            result = execute_camera_intent(intent)
            executed_actions.append(f"ptz_{direction}")
            log.info("Tool PTZ:%s -> %s", direction, result)

    # ZOOM: [ZOOM:in], [ZOOM:out]
    for zoom_match in re.finditer(r"\[ZOOM:(\w+)\]", assistant_text, re.IGNORECASE):
        direction = zoom_match.group(1).lower()
        intent = "camera_zoom_in" if direction == "in" else "camera_zoom_out"
        result = execute_camera_intent(intent)
        executed_actions.append(f"zoom_{direction}")
        log.info("Tool ZOOM:%s -> %s", direction, result)

    # FOLLOW: [FOLLOW:on], [FOLLOW:off]
    for follow_match in re.finditer(r"\[FOLLOW:(\w+)\]", assistant_text, re.IGNORECASE):
        mode = follow_match.group(1).lower()
        intent = "camera_follow_start" if mode == "on" else "camera_follow_stop"
        result, follow_actions = _execute_follow_intent(intent)
        for action in follow_actions:
            if action not in executed_actions:
                executed_actions.append(action)
        executed_actions.append(f"follow_{mode}")
        log.info("Tool FOLLOW:%s -> %s", mode, result)

    # CAMERA_RESET: [CAMERA_RESET]
    if re.search(r"\[CAMERA_RESET\]", assistant_text, re.IGNORECASE):
        result = execute_camera_intent("camera_reset")
        executed_actions.append("camera_reset")
        log.info("Tool CAMERA_RESET -> %s", result)

    # SPOTIFY_SEARCH: [SPOTIFY_SEARCH:query] — search Spotify and play
    _spotify_tag = re.search(r"\[SPOTIFY_SEARCH:([^\]]+)\]", assistant_text, re.IGNORECASE)
    if _spotify_tag:
        _spotify_query = _spotify_tag.group(1).strip()
        _ha_cfg = load_ha_config()
        _result = search_spotify(_spotify_query)
        if _result:
            _uri, _title = _result
            if is_liked_songs_uri(_uri):
                _play_ok, _reason = play_liked_songs()
                _replacement = "Spelar dina gillade låtar." if _play_ok else f"Kunde inte spela gillade låtar: {_reason}."
            else:
                _play_ok, _ = play_spotify_uri(_ha_cfg, _uri)
                _replacement = f"Spelar {_title}." if _play_ok else f"Hittade {_title} men kunde inte starta uppspelning."
        else:
            # Fallback: check the user's own playlists
            _playlist = find_user_playlist(_spotify_query)
            if _playlist:
                _uri, _title = _playlist
                _play_ok, _ = play_spotify_uri(_ha_cfg, _uri)
                _replacement = f"Spelar {_title}." if _play_ok else f"Hittade {_title} men kunde inte starta uppspelning."
            else:
                _replacement = f"Hittade inget för '{_spotify_query}'."
        assistant_text = re.sub(
            r"\[SPOTIFY_SEARCH:[^\]]+\]", _replacement, assistant_text, flags=re.IGNORECASE
        ).strip()
        executed_actions.append("spotify_search")
        log.info("Tool SPOTIFY_SEARCH query=%r result=%r", _spotify_query, _result)

    # LIGHTS: [LIGHTS:on/off/dim:N/warm/cool/neutral/color:NAME]
    for _lights_match in re.finditer(r"\[LIGHTS:([^\]]+)\]", assistant_text, re.IGNORECASE):
        _lights_arg = _lights_match.group(1).strip().lower()
        _ha_cfg = load_ha_config()
        if _lights_arg == "off":
            control_lights(_ha_cfg, "off")
        elif _lights_arg == "on":
            control_lights(_ha_cfg, "on")
        elif _lights_arg.startswith("dim:"):
            try:
                _pct = max(1, min(100, int(_lights_arg.split(":")[1])))
                control_lights(_ha_cfg, "on", brightness_pct=_pct)
            except ValueError:
                pass
        elif _lights_arg == "warm":
            control_lights(_ha_cfg, "on", color_temp_kelvin=2700)
        elif _lights_arg == "cool":
            control_lights(_ha_cfg, "on", color_temp_kelvin=5000)
        elif _lights_arg == "neutral":
            control_lights(_ha_cfg, "on", color_temp_kelvin=3500)
        elif _lights_arg.startswith("color:"):
            _color_name = _lights_arg.split(":", 1)[1]
            _color_map = {
                "röd": (255, 0, 0), "blå": (0, 0, 255), "grön": (0, 200, 0),
                "lila": (128, 0, 200), "orange": (255, 100, 0), "rosa": (255, 20, 130),
                "gul": (255, 220, 0), "turkos": (0, 220, 200),
            }
            if _color_name in _color_map:
                control_lights(_ha_cfg, "on", rgb_color=_color_map[_color_name])
        executed_actions.append(f"lights:{_lights_arg}")
        log.info("Tool LIGHTS:%s", _lights_arg)

    # AIR: [AIR:on/off/sleep/turbo/auto]
    for _air_match in re.finditer(r"\[AIR:(\w+)\]", assistant_text, re.IGNORECASE):
        _air_cmd = _air_match.group(1).strip().lower()
        _ha_cfg = load_ha_config()
        control_air_purifier(_ha_cfg, _air_cmd)
        executed_actions.append(f"air:{_air_cmd}")
        log.info("Tool AIR:%s", _air_cmd)

    # HA_QUERY: [HA_QUERY:entity_id] — replace tag with live sensor value
    for _haq_match in re.finditer(r"\[HA_QUERY:([^\]]+)\]", assistant_text, re.IGNORECASE):
        _entity = _haq_match.group(1).strip()
        _ha_cfg = load_ha_config()
        _val, _ = get_ha_state(_ha_cfg, _entity)
        _unit_map = {
            "sensor.sovrum_temperature": "°C",
            "sensor.sovrum_humidity": "%",
            "sensor.sovrum_pm2_5": "µg/m³",
            "sensor.sovrum_water_level": "%",
        }
        _unit = _unit_map.get(_entity, "")
        _replacement = f"{_val} {_unit}".strip() if _val else "okänt"
        assistant_text = assistant_text.replace(_haq_match.group(0), _replacement)
        executed_actions.append(f"ha_query:{_entity}")
        log.info("Tool HA_QUERY:%s -> %s", _entity, _val)

    # SPOTIFY simple controls: [SPOTIFY:pause/next/prev]
    for _sp_match in re.finditer(r"\[SPOTIFY:(\w+)\]", assistant_text, re.IGNORECASE):
        _sp_cmd = _sp_match.group(1).strip().lower()
        _ha_cfg = load_ha_config()
        if _sp_cmd == "pause":
            pause_spotify(_ha_cfg)
        elif _sp_cmd == "next":
            next_track(_ha_cfg)
        elif _sp_cmd == "prev":
            prev_track(_ha_cfg)
        executed_actions.append(f"spotify:{_sp_cmd}")
        log.info("Tool SPOTIFY:%s", _sp_cmd)

    # TV: [TV:pause/play/stop/mute/volume:up|down|N/app:NAME]
    for _tv_match in re.finditer(r"\[TV:([^\]]+)\]", assistant_text, re.IGNORECASE):
        _tv_cmd = _tv_match.group(1).strip().lower()
        _ha_cfg = load_ha_config()
        _tv_ok, _tv_reason = control_tv(_ha_cfg, _tv_cmd)
        executed_actions.append(f"tv:{_tv_cmd}:{_tv_reason}")
        log.info("Tool TV:%s ok=%s reason=%s", _tv_cmd, _tv_ok, _tv_reason)

    # CAMERA_LOOK: [CAMERA_LOOK] — snapshot + VLM, then second Codex call
    if re.search(r"\[CAMERA_LOOK\]", assistant_text, re.IGNORECASE):
        cam_answer, cam_actions, codex_added = _camera_look_answer(
            user_text=user_text,
            source=req.source,
            conversation_id=req.conversation_id,
            context=context,
            allow_codex_rewrite=True,
        )
        assistant_text = cam_answer
        executed_actions.extend(cam_actions)
        if codex_added > 0:
            codex_ms_total = codex_added if codex_ms_total is None else codex_ms_total + codex_added

    # Strip all tool tags from the text before TTS
    assistant_text = re.sub(
        r"\[(?:PTZ|ZOOM|FOLLOW):\w+\]"
        r"|\[CAMERA_LOOK\]|\[CAMERA_RESET\]"
        r"|\[SPOTIFY_SEARCH:[^\]]+\]|\[SPOTIFY:\w+\]"
        r"|\[LIGHTS:[^\]]+\]|\[AIR:\w+\]|\[HA_QUERY:[^\]]+\]"
        r"|\[TV:[^\]]+\]",
        "",
        assistant_text,
        flags=re.IGNORECASE,
    ).strip()
    # Clean up double spaces
    assistant_text = re.sub(r"  +", " ", assistant_text)
    camera_actions_ms = _to_ms(time.monotonic() - actions_started)
    _warn_if_over_budget(
        "camera_actions",
        camera_actions_ms,
        LATENCY_BUDGET_CAMERA_ACTIONS_MS,
    )

    db.insert_turn(
        req.conversation_id,
        "assistant",
        assistant_text,
        "aihub",
        used_brain=used_brain,
    )

    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=CONVERSATION_TTL_SEC)).isoformat()
    _set_mode(
        current_mode="conversation_mode",
        conversation_id=req.conversation_id,
        conversation_expires_at=expires_at,
    )
    db.log_route("R5", "audio", "conversation_turn", used_brain, egress, "conversation_turn")

    # Fire TTS in background so the HTTP response returns immediately.
    _tts_text = assistant_text
    _tts_source = req.source
    metric_id = db.insert_turn_metric(
        conversation_id=req.conversation_id,
        source=req.source,
        user_text=user_text,
        used_brain=used_brain,
        stt_to_aihub_ms=stt_to_aihub_ms,
        codex_ms=codex_ms_total,
        codex_search_used=codex_search_used,
        camera_actions_ms=camera_actions_ms,
        aihub_total_ms=_to_ms(time.monotonic() - req_started),
    )
    total_ms_for_budget = _to_ms(time.monotonic() - req_started)
    _warn_if_over_budget(
        "conversation_turn_total",
        total_ms_for_budget,
        LATENCY_BUDGET_TURN_TOTAL_MS,
    )

    def _bg_speak() -> None:
        try:
            t_s = time.monotonic()
            ok, reason = speak_to_camera(_tts_text, _tts_source, event="reply")
            t_tts_ms = _to_ms(time.monotonic() - t_s)
            _warn_if_over_budget(
                "tts_request",
                t_tts_ms,
                LATENCY_BUDGET_TTS_REQUEST_MS,
            )
            db.update_turn_metric_tts(
                metric_id,
                tts_request_ms=t_tts_ms,
                tts_ok=ok,
                tts_reason=reason,
            )
            log.info("TTS background: %.1fs (ok=%s, reason=%s)", t_tts_ms / 1000.0, ok, reason)
        except Exception as _exc:
            log.error("TTS background (_bg_speak) failed: %s", _exc)

    threading.Thread(target=_bg_speak, daemon=True).start()

    t_total = time.monotonic() - t0
    log.info(
        "Turn responded in %.1fs (brain=%s, stt->aihub_ms=%s, codex_ms=%s, actions_ms=%.1f, actions=%s)",
        t_total,
        used_brain,
        f"{stt_to_aihub_ms:.1f}" if stt_to_aihub_ms is not None else "n/a",
        f"{codex_ms_total:.1f}" if codex_ms_total is not None else "n/a",
        camera_actions_ms,
        executed_actions,
    )
    return {
        "ok": True,
        "assistant_text": assistant_text,
        "used_brain": used_brain,
        "actions": executed_actions,
        "egress": egress,
        "memory_items_used": len(context),
        "camera_speak": {"ok": True, "reason": "async"},
    }


class TaskStartRequest(BaseModel):
    conversation_id: str
    task_type: str
    task_goal: str
    athlete_name: str | None = None
    timestamp: str | None = None


@app.post("/v1/task/start", dependencies=[Depends(_require_auth)])
def task_start(req: TaskStartRequest) -> dict[str, Any]:
    athlete_name = _resolve_athlete_name(
        explicit_name=req.athlete_name,
        conversation_id=req.conversation_id,
    )
    if not athlete_name:
        return _identity_required_response("task_start")

    _pending_identity_clear()
    task_session_id = f"task-{uuid.uuid4().hex[:12]}"
    db.create_task_session(task_session_id, req.conversation_id, req.task_type, req.task_goal)
    workout = db.ensure_workout_session(
        task_session_id=task_session_id,
        conversation_id=req.conversation_id,
        athlete_name=athlete_name,
        task_type=req.task_type,
        task_goal=req.task_goal,
    )
    db.bind_identity_to_conversation(
        conversation_id=req.conversation_id,
        athlete_name=athlete_name,
        confidence=1.0,
        source="task_start",
    )
    db.bind_identity_to_task(
        task_session_id=task_session_id,
        athlete_name=athlete_name,
        confidence=1.0,
        source="task_start",
    )
    if _rep_counter is not None:
        _rep_counter.reset()
    _set_mode(
        current_mode="task_session_mode",
        task_session_mode=True,
        task_session_id=task_session_id,
        conversation_id=req.conversation_id,
    )
    db.log_route("R6", "audio", "task_start", "local", "none", "task_session_started")
    return {
        "ok": True,
        "task_session_id": task_session_id,
        "task_session_mode": True,
        "athlete_name": workout["athlete_name"],
    }


class TaskStopRequest(BaseModel):
    task_session_id: str
    reason: str = "voice_command"


@app.post("/v1/task/stop", dependencies=[Depends(_require_auth)])
def task_stop(req: TaskStopRequest) -> dict[str, Any]:
    updated = db.stop_task_session(req.task_session_id)
    if not updated:
        raise HTTPException(status_code=404, detail="task_session not found")
    db.stop_workout_session(req.task_session_id)
    _pending_identity_clear()
    mode = _parse_mode()
    next_mode = "conversation_mode" if mode["conversation_id"] else "idle"
    _set_mode(
        current_mode=next_mode,
        task_session_mode=False,
        task_session_id="",
    )
    if _rep_counter is not None:
        _rep_counter.reset()
    db.log_route("R7", "audio", "task_stop", "local", "none", "task_session_stopped")
    return {"ok": True, "task_session_mode": False}


class VisionEventRequest(BaseModel):
    task_session_id: str
    activity: str
    rep_count: int | None = None
    phase: str | None = None
    form_flags: list[str] = Field(default_factory=list)
    fatigue_score: float = 0.0
    confidence: float = 0.0
    athlete_name: str | None = None
    face_embedding: list[float] | None = None
    identity_min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    identity_quality: float | None = None
    identity_source: str = "vision"
    depth_score: float | None = None
    tempo_ms: float | None = None
    summary_sv: str = ""
    timestamp: str | None = None


@app.post("/v1/events/vision", dependencies=[Depends(_require_auth)])
def vision_event(req: VisionEventRequest) -> dict[str, Any]:
    mode = _parse_mode()
    if not mode["task_session_mode"]:
        raise HTTPException(
            status_code=409,
            detail="task_session_mode is off",
        )

    task = db.get_task_session(req.task_session_id)
    if not task:
        raise HTTPException(status_code=404, detail="task_session not found")
    conversation_id = str(task.get("conversation_id", "")).strip()

    # If an explicit name is provided with a face embedding, learn/update face memory.
    explicit_name = _clean_athlete_name(req.athlete_name)
    if explicit_name and req.face_embedding:
        try:
            db.remember_identity(
                athlete_name=explicit_name,
                embedding=req.face_embedding,
                source=req.identity_source or "vision",
                quality=req.identity_quality,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Resolve by face embedding before falling back to previous bindings.
    resolved_from_face = ""
    resolved_face_score: float | None = None
    face_unmatched = False
    if req.face_embedding:
        try:
            resolved = db.resolve_identity_by_embedding(
                embedding=req.face_embedding,
                min_score=(
                    req.identity_min_score
                    if req.identity_min_score is not None
                    else IDENTITY_RESOLVE_MIN_SCORE
                ),
            )
        except ValueError:
            resolved = {"matched": False}
        if bool(resolved.get("matched")):
            resolved_from_face = str(resolved.get("athlete_name", "")).strip()
            try:
                resolved_face_score = float(resolved.get("score", 0.0))
            except (TypeError, ValueError):
                resolved_face_score = None
        elif not explicit_name:
            face_unmatched = True

    athlete_name = _resolve_athlete_name(
        explicit_name=(explicit_name or resolved_from_face or None),
        conversation_id=conversation_id,
        task_session_id=req.task_session_id,
    )
    if not athlete_name:
        if face_unmatched:
            return {
                **_identity_required_response("vision_event"),
                "reason": "unknown_identity",
                "prompt_sv": "Jag känner inte igen personen. Säg: Det är <namn>.",
            }
        return _identity_required_response("vision_event")

    if face_unmatched and not explicit_name:
        # If this person already has known face embeddings, a mismatch likely means someone else
        # is now in view. Ask for explicit identity instead of silently overwriting.
        if db.get_embedding_count_for_athlete(athlete_name) > 0:
            return {
                **_identity_required_response("vision_event"),
                "reason": "unknown_identity",
                "prompt_sv": "Det verkar vara en annan person. Säg: Det är <namn>.",
            }

    if req.face_embedding and not resolved_from_face:
        # First named event with face data for this person: store embedding now.
        try:
            db.remember_identity(
                athlete_name=athlete_name,
                embedding=req.face_embedding,
                source=req.identity_source or "vision",
                quality=req.identity_quality,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    source_name = "vision_event_manual" if explicit_name else (
        "vision_event_face" if resolved_from_face else "vision_event"
    )
    db.bind_identity_to_task(
        task_session_id=req.task_session_id,
        athlete_name=athlete_name,
        confidence=resolved_face_score if resolved_face_score is not None else 1.0,
        source=source_name,
    )
    if conversation_id:
        db.bind_identity_to_conversation(
            conversation_id=conversation_id,
            athlete_name=athlete_name,
            confidence=resolved_face_score if resolved_face_score is not None else 1.0,
            source=source_name,
        )
    progress = db.track_vision_event(
        task_session_id=req.task_session_id,
        conversation_id=conversation_id,
        athlete_name=athlete_name,
        task_type=str(task.get("task_type", "fitness_coach")),
        task_goal=str(task.get("task_goal", "")),
        activity=req.activity,
        rep_count=req.rep_count,
        form_flags=req.form_flags,
        fatigue_score=req.fatigue_score,
        confidence=req.confidence,
        summary_sv=req.summary_sv,
        timestamp=req.timestamp,
        depth_score=req.depth_score,
        tempo_ms=req.tempo_ms,
    )

    tts_text = ""
    actions: list[str] = []
    if req.form_flags or req.fatigue_score >= 0.75:
        actions.append("tts_cue")
        tts_text = "Två reps kvar. Håll linjen och stabil bål."
    elif progress.get("personal_record_updated", False):
        actions.append("tts_pr")
        tts_text = (
            f"Nytt personligt rekord i {progress.get('exercise')}: "
            f"{progress.get('best_reps')} reps."
        )
    db.log_route("R8", "vision", req.activity, "local", "none", "vision_tick")
    return {
        "ok": True,
        "actions": actions,
        "tts_text": tts_text,
        "identity": {
            "athlete_name": athlete_name,
            "resolved_from_face": bool(resolved_from_face),
            "face_score": resolved_face_score,
        },
        "progress": progress,
    }


class IdentityRememberRequest(BaseModel):
    athlete_name: str
    conversation_id: str | None = None
    task_session_id: str | None = None
    embedding: list[float] | None = None
    source: str = "manual"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    quality: float | None = None


@app.post("/v1/identity/remember", dependencies=[Depends(_require_auth)])
def identity_remember(req: IdentityRememberRequest) -> dict[str, Any]:
    athlete_name = _clean_athlete_name(req.athlete_name)
    if not athlete_name:
        raise HTTPException(status_code=422, detail="athlete_name_required")

    try:
        identity = db.remember_identity(
            athlete_name=athlete_name,
            embedding=req.embedding,
            source=req.source,
            quality=req.quality,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    bindings: dict[str, Any] = {}
    if req.conversation_id:
        bindings["conversation"] = db.bind_identity_to_conversation(
            conversation_id=req.conversation_id,
            athlete_name=athlete_name,
            confidence=req.confidence,
            source=req.source,
        )
    if req.task_session_id:
        bindings["task"] = db.bind_identity_to_task(
            task_session_id=req.task_session_id,
            athlete_name=athlete_name,
            confidence=req.confidence,
            source=req.source,
        )
    return {
        "ok": True,
        "identity": identity,
        "bindings": bindings,
    }


class IdentityResolveRequest(BaseModel):
    embedding: list[float]
    conversation_id: str | None = None
    task_session_id: str | None = None
    source: str = "face"
    min_score: float = Field(default=IDENTITY_RESOLVE_MIN_SCORE, ge=0.0, le=1.0)


@app.post("/v1/identity/resolve", dependencies=[Depends(_require_auth)])
def identity_resolve(req: IdentityResolveRequest) -> dict[str, Any]:
    try:
        resolved = db.resolve_identity_by_embedding(
            embedding=req.embedding,
            min_score=req.min_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    bindings: dict[str, Any] = {}
    if resolved.get("matched"):
        athlete_name = str(resolved.get("athlete_name", "")).strip()
        if req.conversation_id:
            bindings["conversation"] = db.bind_identity_to_conversation(
                conversation_id=req.conversation_id,
                athlete_name=athlete_name,
                confidence=float(resolved.get("score", 0.0)),
                source=req.source,
            )
        if req.task_session_id:
            bindings["task"] = db.bind_identity_to_task(
                task_session_id=req.task_session_id,
                athlete_name=athlete_name,
                confidence=float(resolved.get("score", 0.0)),
                source=req.source,
            )
        return {
            "ok": True,
            "matched": True,
            "athlete_name": athlete_name,
            "score": resolved.get("score"),
            "min_score": resolved.get("min_score"),
            "candidates": resolved.get("candidates"),
            "bindings": bindings,
        }

    return {
        "ok": True,
        "matched": False,
        "reason": "unknown_identity",
        "prompt_sv": "Jag känner inte igen personen ännu. Säg: Det är <namn>.",
        "score": resolved.get("score"),
        "min_score": resolved.get("min_score"),
        "candidates": resolved.get("candidates"),
    }


@app.get("/v1/identity/context", dependencies=[Depends(_require_auth)])
def identity_context(
    conversation_id: str | None = Query(default=None),
    task_session_id: str | None = Query(default=None),
) -> dict[str, Any]:
    identity = None
    if task_session_id:
        identity = db.get_task_identity(task_session_id)
    if not identity and conversation_id:
        identity = db.get_conversation_identity(conversation_id)
    if not identity:
        return {"ok": True, "found": False}
    return {"ok": True, "found": True, "identity": identity}


class PolicyEvaluateRequest(BaseModel):
    source: str
    intent: str
    candidate_egress: str
    contains_camera_derived_text: bool = False


@app.post("/v1/policy/evaluate", dependencies=[Depends(_require_auth)])
def policy_evaluate(req: PolicyEvaluateRequest) -> dict[str, Any]:
    allow, egress, reason = evaluate_candidate_egress(
        intent=req.intent,
        candidate_egress=req.candidate_egress,
        contains_camera_derived_text=req.contains_camera_derived_text,
    )
    route_id = "R3" if req.intent == "morning_presence" else "R5"
    return {
        "allow": allow,
        "reason": reason,
        "egress": egress,
        "route_id": route_id,
    }


class SpeakerStateRequest(BaseModel):
    speaker_playing: bool
    duration_sec: float = 0.0


@app.post("/v1/speaker/state", dependencies=[Depends(_require_auth)])
def set_speaker_state(req: SpeakerStateRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    done_at = ""
    if req.speaker_playing and req.duration_sec > 0:
        done_at = (now + timedelta(seconds=req.duration_sec)).isoformat()
    _set_mode(
        **{},  # no mode fields changed
    )
    db.set_mode_state({
        "speaker_playing": db.bool_to_db(req.speaker_playing),
        "speaker_done_at": done_at,
    })
    return {
        "ok": True,
        "speaker_playing": req.speaker_playing,
        "speaker_done_at": done_at,
    }


@app.get("/v1/speaker/state", dependencies=[Depends(_require_auth)])
def get_speaker_state() -> dict[str, Any]:
    state = db.get_mode_state()
    playing = db.db_to_bool(state.get("speaker_playing"))
    done_at_raw = state.get("speaker_done_at", "")
    # Auto-expire: if done_at has passed, speaker is no longer playing.
    if playing and done_at_raw:
        done_at = _parse_iso(done_at_raw)
        if done_at and done_at <= datetime.now(timezone.utc):
            playing = False
            db.set_mode_state({
                "speaker_playing": db.bool_to_db(False),
                "speaker_done_at": "",
            })
    return {
        "ok": True,
        "speaker_playing": playing,
        "speaker_done_at": done_at_raw if playing else "",
    }


class SpeakerInterruptRequest(BaseModel):
    reason: str = "barge_in"


@app.post("/v1/speaker/interrupt", dependencies=[Depends(_require_auth)])
def interrupt_speaker(req: SpeakerInterruptRequest) -> dict[str, Any]:
    ok, reason = interrupt_camera_speaker(req.reason)
    # Always clear local speaker state so listener can continue immediately.
    db.set_mode_state({
        "speaker_playing": db.bool_to_db(False),
        "speaker_done_at": "",
    })
    return {
        "ok": ok,
        "reason": reason,
    }


class SpeakerAnnounceRequest(BaseModel):
    text: str
    source: str = "audio"
    event: str = "reply"


@app.post("/v1/speaker/announce", dependencies=[Depends(_require_auth)])
def speaker_announce(req: SpeakerAnnounceRequest) -> dict[str, Any]:
    ok, reason = speak_to_camera(req.text, req.source, event=req.event)
    return {
        "ok": ok,
        "reason": reason,
    }


@app.get("/v1/metrics/turns", dependencies=[Depends(_require_auth)])
def get_turn_metrics(
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    return {
        "ok": True,
        "items": db.list_turn_metrics(limit),
    }


@app.get("/v1/memory/context", dependencies=[Depends(_require_auth)])
def memory_context(
    conversation_id: str = Query(..., min_length=4),
    k: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    items = db.get_memory_context(conversation_id, k)
    return {"ok": True, "items": items}


@app.get("/v1/stats/progress", dependencies=[Depends(_require_auth)])
def stats_progress(
    athlete_name: str = Query(..., min_length=1),
    exercise: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    stats = db.get_progress_stats(
        athlete_name=athlete_name,
        exercise=exercise,
        limit=limit,
    )
    return {"ok": True, "stats": stats}
