"""Keyword-based intent detection for camera PTZ, Spotify, and normal queries.

Vision queries ("vad ser du", "hur ser min dans ut", etc.) are intentionally
NOT handled here — they fall through to Codex, which emits [CAMERA_LOOK] and
gets a natural-language answer back.  This avoids a brittle keyword list and
lets the LLM understand subjective questions like "är jag snygg?".
"""

from __future__ import annotations

import re


def detect_camera_intent(text: str) -> str:
    """Return an intent string based on keyword matching in *text*.

    Returns one of:
        camera_follow_start
        camera_follow_stop
        camera_ptz_left / camera_ptz_right / camera_ptz_up / camera_ptz_down
        camera_zoom_in / camera_zoom_out
        camera_reset
        spotify_play / spotify_pause / spotify_next / spotify_prev / spotify_status / spotify_search
        none  (fall through to Codex — handles vision, general questions, etc.)
    """
    t = text.strip().lower()

    # --- Auto-tracking --------------------------------------------------
    if re.search(r"\b(följ mig|börja följ\w*|starta följ\w*|spåra mig)\b", t):
        return "camera_follow_start"
    if re.search(r"\b(sluta följ|stanna|avsluta följ|sluta spåra)\b", t):
        return "camera_follow_stop"

    # --- PTZ directional ------------------------------------------------
    if re.search(r"\b(titta|sväng|vrid|panorera)\b.*\b(vänster|åt vänster)\b", t):
        return "camera_ptz_left"
    if re.search(r"\b(titta|sväng|vrid|panorera)\b.*\b(höger|åt höger)\b", t):
        return "camera_ptz_right"
    if re.search(r"\b(titta|sväng|vrid)\b.*\bupp\b", t):
        return "camera_ptz_up"
    if re.search(r"\b(titta|sväng|vrid)\b.*\bner\b", t):
        return "camera_ptz_down"

    # --- Zoom -----------------------------------------------------------
    if re.search(r"\bzooma\s*in\b", t):
        return "camera_zoom_in"
    if re.search(r"\bzooma\s*(ut|tillbaka)\b", t):
        return "camera_zoom_out"

    # --- Reset / home position ------------------------------------------
    if re.search(r"\b(utgångsläge|hemläge|gå tillbaka|återställ kamera)\b", t):
        return "camera_reset"

    # --- Spotify / music ------------------------------------------------
    if re.search(r"\b(pausa|pausa musik(en)?|stoppa musik(en)?|stäng av musik(en)?|sluta spela)\b", t):
        return "spotify_pause"
    if re.search(
        r"\b(spela musik|sätt på musik|starta musik|spela lite musik|spela något musik"
        r"|spela en låt|sätt på en låt|starta en låt|spela lite|sätt igång musik"
        r"|sätt igång en låt|spela nåt|spela något)\b",
        t,
    ):
        return "spotify_play"

    # Track navigation
    if re.search(r"\b(nästa låt|hoppa över|nästa spår|nästa|skip)\b", t):
        return "spotify_next"
    if re.search(r"\b(föregående låt|bakåt|spela om igen|förra låten|föregående spår)\b", t):
        return "spotify_prev"

    # What's playing
    if re.search(r"\b(vad spelas|vad är det som spelas|vilken låt|vad lyssnar vi på|vad lyssnar jag på)\b", t):
        return "spotify_status"

    # Vision queries and music search fall through to Codex → tag handlers.
    return "none"
