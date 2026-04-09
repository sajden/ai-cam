"""ha_context.py — Fetches and formats Home Assistant state into a compact Swedish context block."""

import os
import time
import urllib.request
import urllib.error
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ha_context")

HA_URL = os.getenv("AIHUB_HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.getenv("AIHUB_HA_TOKEN", "").strip()
CACHE_TTL_SEC = int(os.getenv("AIHUB_HA_CONTEXT_CACHE_SEC", "30"))

_cache: dict = {"ts": 0.0, "block": ""}


def _fetch_states() -> list[dict]:
    req = urllib.request.Request(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _state(states: dict[str, dict], entity_id: str) -> dict | None:
    s = states.get(entity_id)
    if s and s["state"] not in ("unavailable", "unknown", "none"):
        return s
    return None


def _val(states: dict[str, dict], entity_id: str, default: str = "") -> str:
    s = _state(states, entity_id)
    return s["state"] if s else default


def _attr(states: dict[str, dict], entity_id: str, attr: str, default="") -> str:
    s = _state(states, entity_id)
    if s:
        return str(s.get("attributes", {}).get(attr, default))
    return default


def _format_light(name: str, state: str, brightness_pct: str) -> str:
    if state == "on":
        return f"{name} på {brightness_pct}%" if brightness_pct else f"{name} på"
    return f"{name} av"


def build_ha_context_block() -> str:
    """Return a compact Swedish [Hem] block with current HA state. Cached for CACHE_TTL_SEC."""
    global _cache
    now = time.monotonic()
    if now - _cache["ts"] < CACHE_TTL_SEC and _cache["block"]:
        return _cache["block"]

    if not HA_TOKEN:
        return ""

    try:
        raw = _fetch_states()
    except Exception as exc:
        logger.warning("ha_context: fetch failed: %s", exc)
        return _cache["block"]  # return stale on error

    states = {s["entity_id"]: s for s in raw}
    lines: list[str] = []

    # --- Väder & tid ---
    weather = _state(states, "weather.forecast_hem")
    sun = _state(states, "sun.sun")
    weather_parts = []
    if weather:
        cond_map = {
            "sunny": "soligt", "partlycloudy": "delvis molnigt", "cloudy": "molnigt",
            "rainy": "regn", "snowy": "snö", "fog": "dimma", "windy": "blåsigt",
            "lightning": "åska", "clear-night": "klar natt",
        }
        cond = cond_map.get(weather["state"], weather["state"])
        temp = weather.get("attributes", {}).get("temperature")
        if temp is not None:
            weather_parts.append(f"{cond}, {temp}°C ute")
        else:
            weather_parts.append(cond)
    if sun:
        weather_parts.append("sol uppe" if sun["state"] == "above_horizon" else "sol nere")
    if weather_parts:
        lines.append("Väder: " + ", ".join(weather_parts))

    # --- Temperatur & luftkvalitet (sovrum = luftrenaren) ---
    env_parts = []
    temp = _val(states, "sensor.sovrum_temperature")
    hum = _val(states, "sensor.sovrum_humidity")
    pm25 = _val(states, "sensor.sovrum_pm2_5")
    allergen = _val(states, "sensor.sovrum_indoor_allergen_index")
    if temp:
        env_parts.append(f"sovrum {temp}°C")
    if hum:
        env_parts.append(f"luftfukt {hum}%")
    if pm25:
        env_parts.append(f"PM2.5 {pm25} μg/m³")
    if allergen:
        env_parts.append(f"allergenindex {allergen}")
    if env_parts:
        lines.append("Inomhus: " + ", ".join(env_parts))

    # --- Luftrenare & luftfuktare ---
    devices = []
    fan = _state(states, "fan.sovrum")
    if fan:
        devices.append(f"luftrenare {'på' if fan['state'] == 'on' else 'av'}")
    hum_dev = _state(states, "humidifier.sovrum")
    if hum_dev:
        devices.append(f"luftfuktare {'på' if hum_dev['state'] == 'on' else 'av'}")
    if devices:
        lines.append("Enheter: " + ", ".join(devices))

    # --- Lampor ---
    lamp_map = {
        "light.krona1": "Krona 1",
        "light.krona2": "Krona 2",
        "light.krona3": "Krona 3",
    }
    on_lamps = []
    off_lamps = []
    for eid, name in lamp_map.items():
        s = _state(states, eid)
        if not s:
            continue
        if s["state"] == "on":
            bri = s.get("attributes", {}).get("brightness")
            pct = f" {round(bri / 255 * 100)}%" if bri else ""
            on_lamps.append(f"{name}{pct}")
        else:
            off_lamps.append(name)
    lamp_parts = []
    if on_lamps:
        lamp_parts.append("på: " + ", ".join(on_lamps))
    if off_lamps:
        lamp_parts.append("av: " + ", ".join(off_lamps))
    if lamp_parts:
        lines.append("Lampor: " + " | ".join(lamp_parts))

    # --- Media ---
    media_parts = []
    spotify = _state(states, "media_player.spotify_sajdenbiceps")
    if spotify:
        st = spotify["state"]
        attrs = spotify.get("attributes", {})
        if st == "playing":
            title = attrs.get("media_title", "")
            artist = attrs.get("media_artist", "")
            device = attrs.get("source", "")
            info = f"{artist} - {title}" if artist and title else title or artist
            media_parts.append(f"Spotify spelar: {info}" + (f" ({device})" if device else ""))
        else:
            media_parts.append(f"Spotify {st}")
    for eid in ["media_player.badrum"]:
        s = _state(states, eid)
        if s and s["state"] == "playing":
            name = s.get("attributes", {}).get("friendly_name", eid)
            title = s.get("attributes", {}).get("media_title", "")
            media_parts.append(f"{name}: {title}" if title else f"{name} spelar")
    if media_parts:
        lines.append("Media: " + " | ".join(media_parts))

    # --- Närvaro ---
    presence_parts = []
    seb = _state(states, "person.sebastian_castwall")
    if seb:
        presence_parts.append(f"Sebastian {'hemma' if seb['state'] == 'home' else 'borta'}")
    seb_batt = _val(states, "sensor.iphone_seb_battery_level")
    if seb_batt:
        presence_parts.append(f"iPhone {seb_batt}%")
    minna_batt = _val(states, "sensor.minna_samsung_battery_level")
    if minna_batt:
        minna_state = _val(states, "sensor.minna_samsung_battery_state")
        charge_icon = " ⚡" if minna_state == "charging" else ""
        presence_parts.append(f"Minna Samsung {minna_batt}%{charge_icon}")
    if presence_parts:
        lines.append("Närvaro: " + ", ".join(presence_parts))

    # --- Rörelsedetektion ---
    motion_parts = []
    if _val(states, "binary_sensor.living_room_person") == "on":
        motion_parts.append("person detekterad i vardagsrum")
    if _val(states, "binary_sensor.living_room_rorelse") == "on":
        motion_parts.append("rörelse i vardagsrum")
    if motion_parts:
        lines.append("Rörelse: " + ", ".join(motion_parts))

    # --- Inköpslista ---
    todo = _state(states, "todo.inkopslista")
    if todo and todo["state"] not in ("0", ""):
        lines.append(f"Inköpslista: {todo['state']} saker")

    block = ("\n\n[Hem]\n" + "\n".join(lines)) if lines else ""
    _cache = {"ts": now, "block": block}
    return block
