#!/usr/bin/env bash
set -euo pipefail

# Quick health probe for Chatterbox service from Docker network.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

docker compose --profile tts-chatterbox up -d chatterbox-tts

echo "1) Waiting for service (up to 180s)"
ok=0
for i in $(seq 1 90); do
  # Some Chatterbox builds do not expose /health; /docs is a stable 200 when server is ready.
  if docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
    http://chatterbox-tts:8000/docs >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "${ok}" -ne 1 ]]; then
  echo "Chatterbox did not become healthy in time. Recent logs:"
  docker compose --profile tts-chatterbox logs --tail 200 chatterbox-tts || true
  exit 1
fi

echo "health: ok"

echo "2) Short TTS request (bytes only)"

# Try OpenAI-compatible endpoint first, then fallback to native /tts.
if docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
  -H "Content-Type: application/json" \
  -X POST http://chatterbox-tts:8000/v1/audio/speech \
  -d '{"model":"chatterbox","input":"Hej Sebastian, Chatterbox är igång.","voice":"default","response_format":"wav"}' \
  | head -c 32 >/dev/null; then
  echo "ok (openai endpoint)"
  exit 0
fi

docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
  -H "Content-Type: application/json" \
  -X POST http://chatterbox-tts:8000/tts \
  -d '{"text":"Hej Sebastian, Chatterbox är igång.","output_format":"wav","voice_mode":"predefined","predefined_voice_id":"Alice.wav"}' \
  | head -c 32 >/dev/null
echo "ok (/tts endpoint)"
