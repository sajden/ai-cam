#!/usr/bin/env bash
set -euo pipefail

docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
  http://camera-voice-bridge:8091/v1/health
echo
