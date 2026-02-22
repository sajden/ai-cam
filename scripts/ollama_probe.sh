#!/usr/bin/env bash
set -euo pipefail

# Probe an Ollama server URL from inside the Docker network.
#
# Why: when you run Ollama on the Windows host (for GPU speed), Home Assistant (in Docker)
# must be able to reach it via host.docker.internal.
#
# Usage:
#   ./scripts/ollama_probe.sh
#   ./scripts/ollama_probe.sh http://host.docker.internal:11434
#
# Optional env:
#   OLLAMA_BASE_URL (default: http://host.docker.internal:11434)
#   OLLAMA_MODEL    (default: llama3.1:8b)

BASE_URL="${1:-${OLLAMA_BASE_URL:-http://host.docker.internal:11434}}"
MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
NET="ai-cam-net"

echo "Probing Ollama at: ${BASE_URL}"
echo "Model: ${MODEL}"
echo

echo "1) /api/tags (list models)"
docker run --rm --network "${NET}" curlimages/curl:8.6.0 -fsS \
  "${BASE_URL%/}/api/tags" | head -c 2000 || true
echo
echo

echo "2) /api/generate (short response test)"
docker run --rm --network "${NET}" curlimages/curl:8.6.0 -fsS \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${MODEL}\",\"prompt\":\"Svara kort pa svenska: Skriv siffran 7.\",\"stream\":false}" \
  "${BASE_URL%/}/api/generate" | head -c 2000 || true
echo
