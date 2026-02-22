#!/usr/bin/env bash
set -euo pipefail

# Quick test for camera voice bridge.
# Usage:
#   ./scripts/camera_speak_test.sh
#   ./scripts/camera_speak_test.sh "Hej Sebastian, test av kamerahögtalare."
#   ./scripts/camera_speak_test.sh "Hej Sebastian" "reolink_e1pro_main" "pcmu"

TEXT="${1:-Hej Sebastian, detta är ett test av kamerahögtalaren.}"
STREAM="${2:-}"
CODEC="${3:-}"
TOKEN="${CAMERA_VOICE_BRIDGE_TOKEN:-}"
if [[ -z "${TOKEN}" && -f ".env" ]]; then
  TOKEN="$(awk -F= '/^CAMERA_VOICE_BRIDGE_TOKEN=/{print $2; exit}' .env)"
fi
TEXT_ESCAPED="${TEXT//\"/\\\"}"
STREAM_ESCAPED="${STREAM//\"/\\\"}"
CODEC_ESCAPED="${CODEC//\"/\\\"}"

DATA="{\"text\":\"${TEXT_ESCAPED}\""
if [[ -n "${STREAM}" ]]; then
  DATA+=",\"stream\":\"${STREAM_ESCAPED}\""
fi
if [[ -n "${CODEC}" ]]; then
  DATA+=",\"codec\":\"${CODEC_ESCAPED}\""
fi
DATA+="}"

if [[ -n "${TOKEN}" ]]; then
  docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -X POST http://camera-voice-bridge:8091/v1/speak \
    -d "${DATA}"
else
  docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
    -H "Content-Type: application/json" \
    -X POST http://camera-voice-bridge:8091/v1/speak \
    -d "${DATA}"
fi

echo
echo "Requested camera speech."
