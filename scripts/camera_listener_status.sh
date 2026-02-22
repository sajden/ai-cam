#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATUS_FILE="${ROOT_DIR}/data/camera-listener/status.json"

docker compose ps camera-listener
echo

if [[ -f "${STATUS_FILE}" ]]; then
  echo "Status file: ${STATUS_FILE}"
  cat "${STATUS_FILE}"
else
  echo "No status file yet: ${STATUS_FILE}"
  echo "Tip: wait 10-20s after startup, then run again."
fi
echo
echo "Recent logs:"
docker compose logs --tail 50 camera-listener
