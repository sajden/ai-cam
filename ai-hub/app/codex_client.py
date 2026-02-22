from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


CODEX_URL = os.getenv("AIHUB_CODEX_URL", "http://codex-gateway:8090/v1/ask").strip()
CODEX_TOKEN = os.getenv("AIHUB_CODEX_TOKEN", "").strip()
CODEX_TIMEOUT_SEC = int(os.getenv("AIHUB_CODEX_TIMEOUT_SEC", "25"))
SEARCH_MODE = os.getenv("AIHUB_CODEX_SEARCH_MODE", "auto").strip().lower()
SEARCH_HINTS = [
    x.strip().lower()
    for x in os.getenv(
        "AIHUB_CODEX_SEARCH_HINTS",
        (
            "väder,vädret,temperatur,prognos,nyheter,aktie,börs,kurs,match,resultat,tabell,"
            "trafik,flyg,tåg,valuta,ränta,just nu,idag,senaste,nuvarande"
        ),
    ).split(",")
    if x.strip()
]
SEARCH_IGNORE_HINTS = [
    x.strip().lower()
    for x in os.getenv(
        "AIHUB_CODEX_SEARCH_IGNORE_HINTS",
        "recept,matlagning,mat,dikter,förklara,sammanfatta,översätt,kod",
    ).split(",")
    if x.strip()
]
SEARCH_HINT_PATTERNS = [
    x.strip()
    for x in os.getenv(
        "AIHUB_CODEX_SEARCH_HINT_PATTERNS",
        (
            r"\bväder(t|lek|prognos)?\b,"
            r"\btemperatur(en|er)?\b,"
            r"\b(regn|snö|vind|grader)\b,"
            r"\b(trafik|kö(er|erna)?|restid|ankomst|avgång|försening(ar)?)\b,"
            r"\b(buss|tåg|pendel|tunnelbana|flyg)\b,"
            r"\b(nästa|närmsta)\b,"
            r"\b(hur tar jag mig|ta mig till|åka till)\b,"
            r"\b(hur lång tid tar|gå från|gångavstånd|promenadavstånd|gångväg)\b"
        ),
    ).split(",")
    if x.strip()
]
_SEARCH_HINT_REGEX: list[re.Pattern[str]] = []
for _pat in SEARCH_HINT_PATTERNS:
    try:
        _SEARCH_HINT_REGEX.append(re.compile(_pat))
    except re.error:
        continue
SYSTEM_PROMPT = os.getenv(
    "AIHUB_CODEX_SYSTEM_PROMPT",
    (
        "Du är Codex, en svensk röstassistent kopplad till en övervakningskamera i hemmet.\n"
        "Svara naturligt på svenska i 2-4 meningar, om användaren inte ber om något annat.\n"
        "Låt tonen vara varm, tydlig och talspråklig.\n"
        "\n"
        "Du har dessa verktyg (inkludera taggen i ditt svar när du vill använda dem):\n"
        "  [CAMERA_LOOK] — se genom kameran. Du får en beskrivning tillbaka och kan svara på den.\n"
        "  [PTZ:left] [PTZ:right] [PTZ:up] [PTZ:down] — vrid kameran.\n"
        "  [ZOOM:in] [ZOOM:out] — zooma.\n"
        "  [FOLLOW:on] — starta automatisk personföljning.\n"
        "  [FOLLOW:off] — stoppa automatisk personföljning.\n"
        "  [CAMERA_RESET] — återställ kameran till utgångsläge.\n"
        "  [SPOTIFY_SEARCH:query] — sök och spela musik på Spotify. Ersätt 'query' med\n"
        "    artist, låttitel eller genre, t.ex. [SPOTIFY_SEARCH:Bob Marley] eller\n"
        "    [SPOTIFY_SEARCH:Lilla Ben Hov1] eller [SPOTIFY_SEARCH:reggae].\n"
        "\n"
        "Regler:\n"
        "- Använd [CAMERA_LOOK] när du behöver kameran för att svara — t.ex. när användaren frågar\n"
        "  vad du ser, hur de ser ut, vad de har på sig, hur deras dans/rörelse/träning ser ut,\n"
        "  om de är snygga, om de gör rätt, eller ber dig titta/kolla på dem. Vid tveksamhet: använd [CAMERA_LOOK].\n"
        "- Använd [SPOTIFY_SEARCH:query] när användaren vill spela musik, en låt, en artist eller genre.\n"
        "- Du kan kombinera verktyg, t.ex. [PTZ:left] [CAMERA_LOOK] för att vrida och titta.\n"
        "- Skriv alltid en kort textkommentar tillsammans med taggar, t.ex. 'Jag vrider vänster. [PTZ:left]'\n"
        "- Utan verktyg → svara direkt på frågan.\n"
    ),
)


def _needs_live_search(text: str) -> bool:
    if SEARCH_MODE == "always":
        return True
    if SEARCH_MODE == "never":
        return False

    lowered = text.lower()
    if any(hint in lowered for hint in SEARCH_IGNORE_HINTS):
        return False

    score = 0.0

    # Query classes that are usually time-sensitive.
    if any(hint in lowered for hint in SEARCH_HINTS):
        score += 1.0
    if any(rx.search(lowered) for rx in _SEARCH_HINT_REGEX):
        score += 1.0

    # Temporal markers often require fresh data.
    if re.search(r"\b(idag|imorgon|nu|just nu|senaste|aktuell|nuvarande|denna vecka)\b", lowered):
        score += 0.7

    # Calendar-like references imply freshness.
    if re.search(r"\b(20\d{2}|januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december)\b", lowered):
        score += 0.4

    return score >= 1.0


def should_send_processing_ack(text: str) -> bool:
    """Heuristic: speak a short 'thinking' acknowledgment before likely slower turns."""
    return _needs_live_search(text)


def ask_codex(
    text: str,
    conversation_id: str,
    memory: list[dict[str, Any]],
) -> tuple[bool, str, dict[str, Any]]:
    payload = {
        "text": text,
        "conversation_id": conversation_id,
        "memory": memory,
        "system_prompt": SYSTEM_PROMPT,
        "allow_search": _needs_live_search(text),
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if CODEX_TOKEN:
        headers["Authorization"] = f"Bearer {CODEX_TOKEN}"

    req = urllib.request.Request(
        CODEX_URL,
        method="POST",
        data=data,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=CODEX_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return False, "Tomt svar från Codex-gateway.", {}
            parsed = json.loads(body)
            text_out = str(parsed.get("text", "")).strip()
            if not text_out:
                return False, "Codex-gateway svarade utan text.", {}
            meta = {
                "elapsed_sec": float(parsed.get("elapsed_sec", 0.0) or 0.0),
                "search_used": bool(parsed.get("search_used", False)),
                "backend": str(parsed.get("backend", "")).strip(),
                "model": str(parsed.get("model", "")).strip(),
            }
            return True, text_out, meta
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        return False, f"Codex-fel HTTP {exc.code}: {detail or 'okänt fel'}", {}
    except Exception as exc:  # pragma: no cover
        return False, f"Codex-koppling misslyckades: {type(exc).__name__}", {}
