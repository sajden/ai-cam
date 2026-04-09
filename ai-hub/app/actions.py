from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from typing import Any


@dataclass
class HAConfig:
    base_url: str
    token: str
    notify_service: str
    spotify_entity_id: str
    dance_spotify_uri: str
    spotify_workout_uri: str
    spotify_arrival_uri: str


@dataclass
class CameraSpeakConfig:
    enabled: bool
    url: str
    token: str
    timeout_sec: int
    source_filter: str
    event_filter: set[str]
    stream: str


def load_ha_config() -> HAConfig:
    return HAConfig(
        base_url=os.getenv("AIHUB_HA_BASE_URL", "http://homeassistant:8123").rstrip("/"),
        token=os.getenv("AIHUB_HA_TOKEN", "").strip(),
        notify_service=os.getenv("AIHUB_HA_NOTIFY_SERVICE", "persistent_notification.create").strip(),
        spotify_entity_id=os.getenv("AIHUB_HA_SPOTIFY_ENTITY_ID", "").strip(),
        dance_spotify_uri=os.getenv("AIHUB_DANCE_SPOTIFY_URI", "").strip(),
        spotify_workout_uri=os.getenv("AIHUB_SPOTIFY_WORKOUT_URI", "").strip(),
        spotify_arrival_uri=os.getenv("AIHUB_SPOTIFY_ARRIVAL_URI", "").strip(),
    )


def load_camera_speak_config() -> CameraSpeakConfig:
    raw_events = os.getenv(
        "AIHUB_CAMERA_SPEAK_EVENTS",
        "reply,wake_ack,processing_ack",
    )
    event_filter = {x.strip().lower() for x in raw_events.split(",") if x.strip()}
    return CameraSpeakConfig(
        enabled=os.getenv("AIHUB_CAMERA_SPEAK_ENABLED", "0").strip() == "1",
        url=os.getenv("AIHUB_CAMERA_SPEAK_URL", "http://camera-voice-bridge:8091/v1/speak").strip(),
        token=os.getenv("AIHUB_CAMERA_SPEAK_TOKEN", "").strip(),
        timeout_sec=int(os.getenv("AIHUB_CAMERA_SPEAK_TIMEOUT_SEC", "20")),
        source_filter=os.getenv("AIHUB_CAMERA_SPEAK_SOURCE_FILTER", "audio").strip().lower(),
        event_filter=event_filter,
        stream=os.getenv("AIHUB_CAMERA_SPEAK_STREAM", "").strip(),
    )


CAMERA_SPEAK_MAX_CHARS = int(os.getenv("AIHUB_CAMERA_SPEAK_MAX_CHARS", "1100"))


def _parse_service(service: str) -> tuple[str, str]:
    if "." not in service:
        raise ValueError("service must be in domain.service format")
    domain, name = service.split(".", 1)
    if not domain or not name:
        raise ValueError("invalid service format")
    return domain, name


def _ha_call(cfg: HAConfig, service: str, payload: dict[str, Any]) -> tuple[bool, str]:
    if not cfg.token:
        return False, "missing_ha_token"
    try:
        domain, name = _parse_service(service)
    except ValueError as exc:
        return False, f"invalid_service:{exc}"

    url = f"{cfg.base_url}/api/services/{domain}/{name}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        method="POST",
        data=data,
        headers={
            "Authorization": f"Bearer {cfg.token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 300:
                return True, "ok"
            return False, f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:  # pragma: no cover
        return False, f"error:{type(exc).__name__}"


def execute_route_actions(route_id: str, context: dict[str, Any]) -> tuple[list[str], list[str]]:
    cfg = load_ha_config()
    executed: list[str] = []
    skipped: list[str] = []

    if route_id == "R1":
        msg = f"Hund upptäckt ({context.get('camera', 'okänd kamera')})."
        ok, reason = _ha_call(
            cfg,
            cfg.notify_service,
            {"title": "AI-cam", "message": msg},
        )
        (executed if ok else skipped).append(f"notify:{reason}")

    elif route_id == "R2":
        if not cfg.spotify_entity_id or not cfg.dance_spotify_uri:
            skipped.append("spotify:not_configured")
        else:
            ok, reason = play_spotify_uri(cfg, cfg.dance_spotify_uri)
            (executed if ok else skipped).append(f"spotify:{reason}")

    elif route_id == "R4a":
        if not cfg.spotify_entity_id or not cfg.spotify_arrival_uri:
            skipped.append("arrival_music:not_configured")
        else:
            ok, reason = play_spotify_uri(cfg, cfg.spotify_arrival_uri)
            (executed if ok else skipped).append(f"arrival_music:{reason}")

    elif route_id == "R4b":
        if not cfg.spotify_entity_id or not cfg.spotify_workout_uri:
            skipped.append("workout_music:not_configured")
        else:
            ok, reason = play_spotify_uri(cfg, cfg.spotify_workout_uri)
            (executed if ok else skipped).append(f"workout_music:{reason}")

    elif route_id == "R3":
        greeting_name = os.getenv("AIHUB_MORNING_GREETING_NAME", "").strip()
        greeting_msg = f"God morgon {greeting_name}." if greeting_name else "God morgon."
        ok, reason = _ha_call(
            cfg,
            cfg.notify_service,
            {"title": "God morgon", "message": greeting_msg},
        )
        (executed if ok else skipped).append(f"morning_greeting:{reason}")

    return executed, skipped


def get_ha_state(cfg: HAConfig, entity_id: str) -> tuple[str | None, str]:
    """Return (state_value, reason). state_value is None on error."""
    if not cfg.token:
        return None, "missing_ha_token"
    url = f"{cfg.base_url}/api/states/{entity_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {cfg.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("state"), "ok"
    except Exception as exc:
        return None, f"error:{type(exc).__name__}"


def get_ha_last_changed(cfg: HAConfig, entity_id: str) -> float | None:
    """Return seconds since last state change for entity_id, or None on error."""
    if not cfg.token:
        return None
    url = f"{cfg.base_url}/api/states/{entity_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {cfg.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            lc = data.get("last_changed")
            if not lc:
                return None
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(lc.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def control_air_purifier(cfg: HAConfig, command: str) -> tuple[bool, str]:
    """Control Philips air purifier fan. command: on|off|auto|sleep|turbo|speed_1|speed_2|speed_3"""
    entity = os.getenv("AIHUB_AIR_PURIFIER_ENTITY", "fan.sovrum")
    if command == "off":
        return _ha_call(cfg, "fan.turn_off", {"entity_id": entity})
    if command == "on":
        return _ha_call(cfg, "fan.turn_on", {"entity_id": entity})
    preset_map = {"auto": "auto", "sleep": "sleep", "turbo": "turbo",
                  "speed_1": "speed_1", "speed_2": "speed_2", "speed_3": "speed_3"}
    if command in preset_map:
        return _ha_call(cfg, "fan.set_preset_mode", {"entity_id": entity, "preset_mode": preset_map[command]})
    return False, f"unknown_command:{command}"


_TV_APP_IDS: dict[str, str] = {
    "youtube": "233637DE",
    "netflix": "CA5E8412",
    "hbo": "HBOMax",
    "hbomax": "HBOMax",
    "max": "HBOMax",
    "spotify": "CC32E753",
    "svtplay": "009B4F9A",
    "svt": "009B4F9A",
    "prime": "17608CFB",
    "primevideo": "17608CFB",
    "plex": "9AC194DC",
    "disney": "C3DE6BC2",
    "disneyplus": "C3DE6BC2",
}


def control_tv(cfg: HAConfig, command: str) -> tuple[bool, str]:
    """Control Chromecast via HA. command: play|pause|stop|mute|volume:up|volume:down|volume:N|app:NAME"""
    entity = os.getenv("AIHUB_TV_ENTITY", "").strip()
    if not entity:
        return False, "no_tv_entity_configured"
    if command == "pause":
        return _ha_call(cfg, "media_player.media_pause", {"entity_id": entity})
    if command == "play":
        return _ha_call(cfg, "media_player.media_play", {"entity_id": entity})
    if command in ("stop", "off"):
        return _ha_call(cfg, "media_player.turn_off", {"entity_id": entity})
    if command == "mute":
        return _ha_call(cfg, "media_player.volume_mute", {"entity_id": entity, "is_volume_muted": True})
    if command == "unmute":
        return _ha_call(cfg, "media_player.volume_mute", {"entity_id": entity, "is_volume_muted": False})
    if command.startswith("volume:"):
        vol_arg = command.split(":", 1)[1].strip()
        if vol_arg == "up":
            return _ha_call(cfg, "media_player.volume_up", {"entity_id": entity})
        if vol_arg == "down":
            return _ha_call(cfg, "media_player.volume_down", {"entity_id": entity})
        try:
            level = max(0, min(100, int(vol_arg)))
            return _ha_call(cfg, "media_player.volume_set", {"entity_id": entity, "volume_level": level / 100})
        except ValueError:
            return False, f"invalid_volume:{vol_arg}"
    if command.startswith("app:"):
        app_name = command.split(":", 1)[1].strip().lower()
        app_id = _TV_APP_IDS.get(app_name)
        if not app_id:
            return False, f"unknown_app:{app_name}"
        return _ha_call(
            cfg,
            "media_player.play_media",
            {
                "entity_id": entity,
                "media_content_type": "cast",
                "media_content_id": json.dumps({"app_id": app_id}),
            },
        )
    return False, f"unknown_tv_command:{command}"


def control_lights(cfg: HAConfig, command: str, **kwargs: Any) -> tuple[bool, str]:
    """Turn lights on/off via HA REST API. Entities read from AIHUB_LIGHT_ENTITIES."""
    raw = os.getenv("AIHUB_LIGHT_ENTITIES", "").strip()
    entities = [e.strip() for e in raw.split(",") if e.strip()]
    if not entities:
        return False, "no_entities_configured"
    if command == "off":
        return _ha_call(cfg, "light.turn_off", {"entity_id": entities})
    payload: dict[str, Any] = {"entity_id": entities}
    if "brightness_pct" in kwargs:
        payload["brightness_pct"] = int(kwargs["brightness_pct"])
    if "color_temp_kelvin" in kwargs:
        payload["color_temp_kelvin"] = int(kwargs["color_temp_kelvin"])
    if "rgb_color" in kwargs:
        payload["rgb_color"] = list(kwargs["rgb_color"])
    return _ha_call(cfg, "light.turn_on", payload)


def play_spotify(cfg: HAConfig) -> tuple[bool, str]:
    if not cfg.spotify_entity_id:
        return False, "not_configured"
    return _ha_call(cfg, "media_player.media_play", {"entity_id": cfg.spotify_entity_id})


def pause_spotify(cfg: HAConfig) -> tuple[bool, str]:
    if not cfg.spotify_entity_id:
        return False, "not_configured"
    return _ha_call(cfg, "media_player.media_pause", {"entity_id": cfg.spotify_entity_id})


def _get_spotify_state(cfg: HAConfig) -> dict:
    """Return HA state dict for the Spotify entity, or empty dict on error."""
    if not cfg.spotify_entity_id or not cfg.token:
        return {}
    url = f"{cfg.base_url}/api/states/{cfg.spotify_entity_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {cfg.token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def play_spotify_uri(cfg: HAConfig, uri: str) -> tuple[bool, str]:
    if not cfg.spotify_entity_id:
        return False, "not_configured"

    state_data = _get_spotify_state(cfg)
    state = state_data.get("state", "")
    attrs = state_data.get("attributes", {})
    current_source = attrs.get("source")
    sources = attrs.get("source_list", [])

    # If idle with no active source, select the first available source first
    if state in ("idle", "off", "unavailable", "") and not current_source and sources:
        _ha_call(
            cfg,
            "media_player.select_source",
            {"entity_id": cfg.spotify_entity_id, "source": sources[0]},
        )

    # If paused, stop first so play_media starts the new track immediately
    if state == "paused":
        _ha_call(cfg, "media_player.media_stop", {"entity_id": cfg.spotify_entity_id})

    return _ha_call(
        cfg,
        "media_player.play_media",
        {
            "entity_id": cfg.spotify_entity_id,
            "media_content_type": "music",
            "media_content_id": uri,
        },
    )


def next_track(cfg: HAConfig) -> tuple[bool, str]:
    if not cfg.spotify_entity_id:
        return False, "not_configured"
    return _ha_call(cfg, "media_player.media_next_track", {"entity_id": cfg.spotify_entity_id})


def prev_track(cfg: HAConfig) -> tuple[bool, str]:
    if not cfg.spotify_entity_id:
        return False, "not_configured"
    return _ha_call(cfg, "media_player.media_previous_track", {"entity_id": cfg.spotify_entity_id})


def get_current_track(cfg: HAConfig) -> str | None:
    """Return 'Track – Artist' for what's currently playing, or None."""
    if not cfg.spotify_entity_id or not cfg.token:
        return None
    url = f"{cfg.base_url}/api/states/{cfg.spotify_entity_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {cfg.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    state = data.get("state", "")
    if state in ("idle", "unavailable", "unknown", "off", ""):
        return None
    attrs = data.get("attributes", {})
    title = attrs.get("media_title", "")
    artist = attrs.get("media_artist", "")
    if title and artist:
        return f"{title} – {artist}"
    return title or None


def speak_to_camera(text: str, source: str, *, event: str = "reply") -> tuple[bool, str]:
    cfg = load_camera_speak_config()
    event_name = event.strip().lower() or "reply"
    if not cfg.enabled:
        return False, "disabled"
    if cfg.source_filter and cfg.source_filter != "any" and source.lower() != cfg.source_filter:
        return False, "source_filtered"
    if cfg.event_filter and event_name not in cfg.event_filter:
        return False, "event_filtered"
    if not text.strip():
        return False, "empty_text"
    safe_text = text.strip()
    if CAMERA_SPEAK_MAX_CHARS > 0 and len(safe_text) > CAMERA_SPEAK_MAX_CHARS:
        safe_text = safe_text[: CAMERA_SPEAK_MAX_CHARS - 1].rstrip() + "…"

    payload: dict[str, Any] = {"text": safe_text}
    if cfg.stream:
        payload["stream"] = cfg.stream
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"

    req = urllib.request.Request(cfg.url, method="POST", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_sec) as resp:
            if 200 <= resp.status < 300:
                return True, "ok"
            return False, f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        if detail:
            return False, f"http_{exc.code}:{detail[:220]}"
        return False, f"http_{exc.code}"
    except Exception as exc:  # pragma: no cover
        return False, f"error:{type(exc).__name__}"


def interrupt_camera_speaker(reason: str = "barge_in") -> tuple[bool, str]:
    cfg = load_camera_speak_config()
    if not cfg.enabled:
        return False, "disabled"
    if not cfg.url.strip():
        return False, "missing_url"

    parsed = urlsplit(cfg.url.strip())
    base_path = parsed.path.rstrip("/")
    if base_path.endswith("/speak"):
        interrupt_path = base_path[: -len("/speak")] + "/interrupt"
    else:
        head, _, _ = base_path.rpartition("/")
        interrupt_path = (head or base_path) + "/interrupt"
    interrupt_url = urlunsplit((parsed.scheme, parsed.netloc, interrupt_path, "", ""))

    payload = {"reason": reason.strip() or "barge_in"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"
    req = urllib.request.Request(interrupt_url, method="POST", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 300:
                return True, "ok"
            return False, f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:  # pragma: no cover
        return False, f"error:{type(exc).__name__}"
