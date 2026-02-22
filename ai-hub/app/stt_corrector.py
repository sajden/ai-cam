"""LLM-based STT text correction and hallucination filtering.

Uses a fast local model (Ollama) to:
1. Fix common STT transcription errors ("titta höga" → "titta höger")
2. Filter hallucinations ("tack så mycket" repeated → IGNORE)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("AIHUB_OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
CORRECTOR_MODEL = os.getenv("AIHUB_OLLAMA_CORRECTOR_MODEL", "llama3.1:8b")
CORRECTOR_TIMEOUT_SEC = int(os.getenv("AIHUB_OLLAMA_CORRECTOR_TIMEOUT_SEC", "5"))

_SYSTEM_PROMPT = """\
Du är en STT-korrigerare för ett svenskt röststyrningssystem.

UPPGIFT: Rätta uppenbara talfel i transkriberad text. Svara BARA med den korrigerade texten.

REGLER:
- Rätta hörfel: "titta höga" → "titta höger", "förl i mig" → "följ mig", "öl och mig" → "följ mig"
- Behåll meningens syfte och längd — lägg inte till ord
- Om texten är en hallucination (meningslös, repetitiv, inte riktad till en assistent, eller typiska undertexter som "tack så mycket", "textning", "välkomna"), svara med exakt: IGNORE
- Om texten redan är korrekt, returnera den oförändrad
- Svara ALDRIG med förklaringar, bara den korrigerade texten eller IGNORE"""


def correct_stt_text(text: str) -> str | None:
    """Return corrected text, or None if the text should be ignored.

    Uses a fast local LLM to fix STT errors and filter hallucinations.
    Falls back to returning the original text if the LLM is unavailable.
    """
    payload = {
        "model": CORRECTOR_MODEL,
        "system": _SYSTEM_PROMPT,
        "prompt": text,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 60,
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
        with urllib.request.urlopen(req, timeout=CORRECTOR_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read())
            result = str(body.get("response", "")).strip()
            if not result:
                log.warning("STT corrector returned empty response for: %r", text)
                return text
            if result.upper() == "IGNORE":
                log.info("STT corrector filtered hallucination: %r", text)
                return None
            if result != text:
                log.info("STT corrector: %r -> %r", text, result)
            return result
    except Exception as exc:
        log.warning("STT corrector unavailable (%s), using original text", type(exc).__name__)
        return text
