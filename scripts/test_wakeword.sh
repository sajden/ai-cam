#!/usr/bin/env bash
# Stream camera-listener logs filtered for wake/oww/detected events.
# Usage: ./scripts/test_wakeword.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "${SCRIPT_DIR}/_lib.sh"

echo "=== Streaming camera-listener wake word logs ==="
echo "Say your wake word ('hey jarvis' or configured phrase) near the camera mic."
echo "Press Ctrl+C to stop."
echo ""

docker_compose -f "$(repo_root)/docker-compose.yml" logs -f camera-listener 2>&1 \
  | grep --line-buffered -iE '(wake|oww|detect|openwakeword|wakeword|trigger)'
