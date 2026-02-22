#!/usr/bin/env bash
# Simulate a wake + conversation turn via AIHub API (no microphone needed).
# Usage: ./scripts/test_voice_turn.sh [text]
# Example: ./scripts/test_voice_turn.sh "vad är klockan"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"
load_env

AIHUB_BASE="${CAMERA_LISTENER_AIHUB_URL:-http://localhost:8080}"
TEXT="${1:-hej codex}"
AUTH_HEADER=""
if [[ -n "${AIHUB_TOKEN:-}" ]]; then
  AUTH_HEADER="Authorization: Bearer ${AIHUB_TOKEN}"
fi

echo "=== Step 1: Wake trigger ==="
WAKE_RESP=$(curl -s -X POST "${AIHUB_BASE}/v1/events/audio/wake" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER:+-H "$AUTH_HEADER"} \
  -d "{\"device\": \"test-script\", \"wake_phrase\": \"hej codex\"}")

echo "${WAKE_RESP}" | python3 -m json.tool 2>/dev/null || echo "${WAKE_RESP}"

CONV_ID=$(echo "${WAKE_RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('conversation_id',''))" 2>/dev/null || echo "")
if [[ -z "${CONV_ID}" ]]; then
  echo "ERROR: No conversation_id in wake response" >&2
  exit 1
fi

echo ""
echo "=== Step 2: Conversation turn (text='${TEXT}') ==="
TURN_RESP=$(curl -s -X POST "${AIHUB_BASE}/v1/conversation/turn" \
  -H "Content-Type: application/json" \
  ${AUTH_HEADER:+-H "$AUTH_HEADER"} \
  -d "{\"conversation_id\": \"${CONV_ID}\", \"source\": \"audio\", \"text\": \"${TEXT}\", \"allow_codex\": true}")

echo "${TURN_RESP}" | python3 -m json.tool 2>/dev/null || echo "${TURN_RESP}"

echo ""
echo "=== Step 3: Speaker state ==="
SPEAKER_RESP=$(curl -s "${AIHUB_BASE}/v1/speaker/state" \
  ${AUTH_HEADER:+-H "$AUTH_HEADER"})

echo "${SPEAKER_RESP}" | python3 -m json.tool 2>/dev/null || echo "${SPEAKER_RESP}"

echo ""
echo "Done. conversation_id=${CONV_ID}"
