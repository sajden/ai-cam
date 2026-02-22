#!/usr/bin/env bash
set -euo pipefail

# Render a Chatterbox-TTS-Server config into ./data/chatterbox/config.yaml.
# This script is idempotent and safe to re-run.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${ROOT_DIR}/data/chatterbox"
TARGET_FILE="${TARGET_DIR}/config.yaml"

mkdir -p \
  "${TARGET_DIR}" \
  "${TARGET_DIR}/reference_audio" \
  "${TARGET_DIR}/outputs" \
  "${TARGET_DIR}/logs" \
  "${TARGET_DIR}/hf-cache"

cat > "${TARGET_FILE}" <<'YAML'
api:
  host: "0.0.0.0"
  port: 8000
  cors:
    allow_origins: ["*"]
    allow_credentials: true
    allow_methods: ["*"]
    allow_headers: ["*"]

model:
  type: "chatterbox"
  # GPU strongly recommended for low latency.
  device: "cuda"
  torch_dtype: "float16"
  # Optional per-request defaults; keep conservative for stability.
  default_options:
    exaggeration: 0.5
    cfg_weight: 0.5
    temperature: 0.8
    language: "sv"

audio:
  output_format: "wav"
  sample_rate: 24000

logging:
  level: "INFO"
  format: "json"

output:
  save_generated_audio: false
  output_dir: "/app/outputs"
YAML

echo "Wrote: ${TARGET_FILE}"
