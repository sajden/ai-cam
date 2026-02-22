#!/usr/bin/env bash
set -euo pipefail

# Installs a custom Home Assistant TTS provider that calls the local Chatterbox API.
# Target path:
#   ./data/homeassistant/custom_components/aihub_chatterbox

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${REPO_ROOT}/data/homeassistant/custom_components/aihub_chatterbox"

sudo install -d -m 0755 "${TARGET_DIR}"

cat <<'JSON' | sudo tee "${TARGET_DIR}/manifest.json" >/dev/null
{
  "domain": "aihub_chatterbox",
  "name": "AIHub Chatterbox TTS",
  "version": "0.1.0",
  "documentation": "https://github.com/sajden/ai-cam",
  "iot_class": "local_polling",
  "requirements": [],
  "codeowners": [
    "@sajden"
  ]
}
JSON

cat <<'PY' | sudo tee "${TARGET_DIR}/__init__.py" >/dev/null
"""AIHub Chatterbox TTS custom integration."""
PY

cat <<'PY' | sudo tee "${TARGET_DIR}/tts.py" >/dev/null
"""Home Assistant TTS provider for local Chatterbox API."""

from __future__ import annotations

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit

import voluptuous as vol

from homeassistant.components.tts import PLATFORM_SCHEMA, Provider
from homeassistant.const import CONF_NAME

_LOGGER = logging.getLogger(__name__)

CONF_URL = "url"
CONF_MODEL = "model"
CONF_VOICE = "voice"
CONF_RESPONSE_FORMAT = "response_format"
CONF_LANGUAGE = "language"
CONF_TIMEOUT = "timeout"

DEFAULT_NAME = "AIHub Chatterbox"
DEFAULT_URL = "http://chatterbox-tts:8000/tts"
DEFAULT_MODEL = "chatterbox"
DEFAULT_VOICE = ""
DEFAULT_RESPONSE_FORMAT = "wav"
DEFAULT_LANGUAGE = "sv"
DEFAULT_TIMEOUT = 120

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): vol.Coerce(str),
        vol.Optional(CONF_URL, default=DEFAULT_URL): vol.Coerce(str),
        vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): vol.Coerce(str),
        vol.Optional(CONF_VOICE, default=DEFAULT_VOICE): vol.Coerce(str),
        vol.Optional(CONF_RESPONSE_FORMAT, default=DEFAULT_RESPONSE_FORMAT): vol.In(
            ["wav", "opus", "mp3", "flac"]
        ),
        vol.Optional(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): vol.Coerce(str),
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.Coerce(int),
    }
)


def get_engine(hass, config, discovery_info=None):
    """Set up Chatterbox TTS provider."""
    return AIHubChatterboxProvider(config)


class AIHubChatterboxProvider(Provider):
    """Provider class for Chatterbox API."""

    def __init__(self, config):
        self.name = config.get(CONF_NAME)
        self._url = config.get(CONF_URL)
        self._model = config.get(CONF_MODEL)
        self._voice = str(config.get(CONF_VOICE, "")).strip()
        self._response_format = config.get(CONF_RESPONSE_FORMAT)
        self._language = config.get(CONF_LANGUAGE)
        self._timeout = config.get(CONF_TIMEOUT)

    def _discover_predefined_voice_id(self) -> str | None:
        """Try to discover first available predefined voice id from Chatterbox."""
        try:
            parts = urlsplit(self._url)
            base_path = parts.path
            if base_path.endswith("/tts"):
                base_path = base_path[: -len("/tts")]
            discover_url = urlunsplit(
                (parts.scheme, parts.netloc, f"{base_path}/get_predefined_voices", "", "")
            )
            req = Request(discover_url, headers={"Accept": "application/json"}, method="GET")
            with urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Could not discover predefined voices: %s", exc)
            return None

        candidates: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    for key in ("id", "filename", "name", "value"):
                        val = item.get(key)
                        if isinstance(val, str) and val.strip():
                            candidates.append(val.strip())
                            break
        elif isinstance(data, dict):
            for key in ("voices", "items", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            candidates.append(item.strip())
                        elif isinstance(item, dict):
                            for k in ("id", "filename", "name", "value"):
                                val = item.get(k)
                                if isinstance(val, str) and val.strip():
                                    candidates.append(val.strip())
                                    break

        return candidates[0] if candidates else None

    def _clone_ref_path(self) -> str | None:
        """Parse voice config `clone:<file-or-path>` into absolute container path."""
        if not self._voice.startswith("clone:"):
            return None
        ref = self._voice.split(":", 1)[1].strip()
        if not ref:
            return None
        if not ref.startswith("/"):
            ref = f"/app/reference_audio/{ref}"
        return ref

    @property
    def default_language(self):
        """Return the default language."""
        return self._language

    @property
    def supported_languages(self):
        """Return list of supported languages."""
        return ["sv", "en"]

    @property
    def supported_options(self):
        """Return supported options."""
        return []

    def _native_payload_variants(self, message: str, language: str | None) -> list[dict]:
        """Build payload variants for /tts across server versions."""
        base = {
            "text": message,
            "output_format": self._response_format,
        }
        if language:
            base["language"] = language
        elif self._language:
            base["language"] = self._language

        clone_ref = self._clone_ref_path()
        if clone_ref:
            variants = []
            clone_filename = os.path.basename(clone_ref)
            # Different Chatterbox server builds may use different field names.
            for key in (
                "reference_audio_path",
                "reference_audio_file",
                "reference_audio",
                "reference_path",
                "speaker_wav",
                "audio_prompt_path",
            ):
                v = dict(base)
                v["voice_mode"] = "clone"
                v[key] = clone_ref
                variants.append(v)
            # Some builds require this exact key and expect only filename in reference_audio dir.
            v = dict(base)
            v["voice_mode"] = "clone"
            v["reference_audio_filename"] = clone_filename
            variants.insert(0, v)
            return variants

        if self._voice:
            if self._voice.startswith("predefined:"):
                v = dict(base)
                v["voice_mode"] = "predefined"
                v["predefined_voice_id"] = self._voice.split(":", 1)[1]
                return [v]
            v = dict(base)
            v["voice_mode"] = self._voice
            return [v]

        # If no voice set, try server default first.
        variants = [dict(base)]
        # Fallback for server builds that force predefined mode.
        discovered = self._discover_predefined_voice_id()
        if discovered:
            v = dict(base)
            v["voice_mode"] = "predefined"
            v["predefined_voice_id"] = discovered
            variants.append(v)
        return variants

    def _openai_payload(self, message: str, language: str | None) -> dict:
        payload = {
            "model": self._model,
            "input": message,
            "voice": self._voice,
            "response_format": self._response_format,
        }
        if language:
            payload["language"] = language
        elif self._language:
            payload["language"] = self._language
        return payload

    def _request_audio(self, payload: dict) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=self._timeout) as resp:
            return resp.read()

    def get_tts_audio(self, message, language, options=None):
        """Fetch TTS audio from local Chatterbox service."""
        payloads: list[dict]
        if self._url.rstrip("/").endswith("/tts"):
            payloads = self._native_payload_variants(message, language)
        else:
            payloads = [self._openai_payload(message, language)]

        last_http_error: tuple[int, str] | None = None
        for payload in payloads:
            try:
                audio = self._request_audio(payload)
                if not audio:
                    continue
                if self._response_format == "opus":
                    return "ogg", audio
                return self._response_format, audio
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                last_http_error = (exc.code, detail[:400])
                continue
            except URLError as exc:
                _LOGGER.error("Chatterbox connection error: %s", exc)
                return None, None
            except Exception as exc:  # pragma: no cover
                _LOGGER.error("Chatterbox TTS unexpected error: %s", type(exc).__name__)
                return None, None

        if last_http_error is not None:
            _LOGGER.error(
                "Chatterbox HTTP error %s after %s payload attempts: %s",
                last_http_error[0],
                len(payloads),
                last_http_error[1],
            )
        else:
            _LOGGER.error("Chatterbox returned empty audio payload")
        return None, None
PY

cat <<'JSON' | sudo tee "${TARGET_DIR}/strings.json" >/dev/null
{
  "title": "AIHub Chatterbox TTS"
}
JSON

echo "Installed custom TTS integration: ${TARGET_DIR}"
echo "Next: add platform 'aihub_chatterbox' under tts: in configuration.yaml and restart Home Assistant."
