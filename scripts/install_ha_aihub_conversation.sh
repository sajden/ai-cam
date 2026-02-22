#!/usr/bin/env bash
set -euo pipefail

# Installs a custom Home Assistant conversation agent that forwards text turns to AIHub.
# Target path is inside the HA config mount:
#   ./data/homeassistant/custom_components/aihub_conversation

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${REPO_ROOT}/data/homeassistant/custom_components/aihub_conversation"

sudo install -d -m 0755 "${TARGET_DIR}"

cat <<'JSON' | sudo tee "${TARGET_DIR}/manifest.json" >/dev/null
{
  "domain": "aihub_conversation",
  "name": "AIHub Conversation",
  "version": "0.1.0",
  "config_flow": true,
  "iot_class": "local_push",
  "requirements": [],
  "codeowners": [
    "@sajden"
  ]
}
JSON

cat <<'PY' | sudo tee "${TARGET_DIR}/const.py" >/dev/null
"""Constants for AIHub conversation bridge."""

DOMAIN = "aihub_conversation"

CONF_BASE_URL = "base_url"
CONF_TOKEN = "token"
CONF_WAKE_PHRASE = "wake_phrase"
CONF_DEVICE = "device"

DEFAULT_NAME = "AIHub Conversation"
DEFAULT_BASE_URL = "http://aihub:8080"
DEFAULT_WAKE_PHRASE = "hej codex"
DEFAULT_DEVICE = "ha_assist"
REQUEST_TIMEOUT_SEC = 120
PY

cat <<'PY' | sudo tee "${TARGET_DIR}/__init__.py" >/dev/null
"""AIHub conversation integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = [Platform.CONVERSATION]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration from YAML (unused)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up integration from config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
PY

cat <<'PY' | sudo tee "${TARGET_DIR}/config_flow.py" >/dev/null
"""Config flow for AIHub conversation integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BASE_URL,
    CONF_DEVICE,
    CONF_TOKEN,
    CONF_WAKE_PHRASE,
    DEFAULT_BASE_URL,
    DEFAULT_DEVICE,
    DEFAULT_NAME,
    DEFAULT_WAKE_PHRASE,
    DOMAIN,
)


class AIHubConversationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AIHub Conversation."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            unique_id = user_input[CONF_BASE_URL].rstrip("/")
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Optional(CONF_TOKEN, default=""): str,
                vol.Optional(CONF_WAKE_PHRASE, default=DEFAULT_WAKE_PHRASE): str,
                vol.Optional(CONF_DEVICE, default=DEFAULT_DEVICE): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
PY

cat <<'PY' | sudo tee "${TARGET_DIR}/conversation.py" >/dev/null
"""Conversation platform that forwards turns to AIHub."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from aiohttp import ClientError

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import intent

from .const import (
    CONF_BASE_URL,
    CONF_DEVICE,
    CONF_TOKEN,
    CONF_WAKE_PHRASE,
    REQUEST_TIMEOUT_SEC,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AIHub conversation entity."""
    async_add_entities([AIHubConversationEntity(hass, entry)])


class AIHubConversationEntity(conversation.ConversationEntity):
    """Conversation agent proxying requests to AIHub."""

    _attr_supported_languages = ["sv", "en"]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._session = async_get_clientsession(hass)

        self._attr_name = entry.data.get(CONF_NAME, "AIHub Conversation")
        self._attr_unique_id = f"aihub_conversation_{entry.entry_id}"

        self._base_url = str(entry.data.get(CONF_BASE_URL, "http://aihub:8080")).rstrip("/")
        self._token = str(entry.data.get(CONF_TOKEN, "")).strip()
        self._wake_phrase = str(entry.data.get(CONF_WAKE_PHRASE, "hej codex")).strip() or "hej codex"
        self._device = str(entry.data.get(CONF_DEVICE, "ha_assist")).strip() or "ha_assist"

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages."""
        return self._attr_supported_languages

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        url = f"{self._base_url}{path}"
        async with asyncio.timeout(REQUEST_TIMEOUT_SEC):
            response = await self._session.post(url, json=payload, headers=headers)
            body = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"AIHub {path} failed ({response.status}): {body}")
            if not isinstance(body, dict):
                raise RuntimeError(f"AIHub {path} returned non-object JSON")
            return body

    async def _start_conversation(self) -> str:
        try:
            data = await self._post_json(
                "/v1/events/audio/wake",
                {
                    "device": self._device,
                    "wake_phrase": self._wake_phrase,
                },
            )
            conversation_id = str(data.get("conversation_id", "")).strip()
            if conversation_id:
                return conversation_id
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("AIHub wake call failed, fallback to local conversation id: %s", exc)
        return f"conv-ha-{uuid.uuid4().hex[:12]}"

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process text from Assist and return speech."""
        conversation_id = user_input.conversation_id or await self._start_conversation()

        assistant_text = ""
        try:
            data = await self._post_json(
                "/v1/conversation/turn",
                {
                    "conversation_id": conversation_id,
                    "source": "audio",
                    "text": user_input.text,
                    "allow_codex": True,
                },
            )
            assistant_text = str(data.get("assistant_text", "")).strip()
        except (TimeoutError, asyncio.TimeoutError, ClientError, RuntimeError) as exc:
            _LOGGER.warning("AIHub conversation turn failed: %s", exc)
            assistant_text = "AIHub svarar inte just nu. Försök igen om en stund."

        if not assistant_text:
            assistant_text = "Jag fick inget svar från AIHub."

        intent_response = intent.IntentResponse(language=user_input.language or "sv")
        intent_response.async_set_speech(assistant_text)
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=conversation_id,
        )
PY

cat <<'JSON' | sudo tee "${TARGET_DIR}/strings.json" >/dev/null
{
  "config": {
    "step": {
      "user": {
        "title": "AIHub Conversation",
        "description": "Koppla Home Assistant Assist till AIHub.",
        "data": {
          "name": "Namn",
          "base_url": "AIHub URL",
          "token": "AIHub Token (valfritt)",
          "wake_phrase": "Wake phrase",
          "device": "Device-id"
        }
      }
    }
  }
}
JSON

echo "Installed custom integration to: ${TARGET_DIR}"
echo "Next: restart Home Assistant and add integration 'AIHub Conversation' in UI."
