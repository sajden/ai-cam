#!/usr/bin/env bash
set -euo pipefail

# Pull an Ollama model into ./data/ollama (persistent).
#
# This script pulls into the *Docker* Ollama container (profile: docker-ollama).
# If you run Ollama on Windows instead (recommended for GPU), run `ollama pull ...` on Windows.
#
# Usage (Docker Ollama):
#   ./scripts/ollama_pull.sh llama3.1:8b

if [[ -z "${1:-}" ]]; then
  echo "Usage: ./scripts/ollama_pull.sh <model>"
  echo "Example: ./scripts/ollama_pull.sh llama3.1:8b"
  exit 1
fi

MODEL="$1"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose --profile docker-ollama up -d ollama
docker compose --profile docker-ollama exec -T ollama ollama pull "${MODEL}"
docker compose --profile docker-ollama exec -T ollama ollama list
