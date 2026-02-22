#!/usr/bin/env bash
set -euo pipefail

# Record a short RTSP clip directly using ffmpeg inside the Frigate container.
#
# Why inside Frigate?
# - Frigate image already includes ffmpeg and has the media volume mounted.
# - Output ends up under ./data/clips/ so it's persistent and easy to find.
#
# Usage:
# - ./scripts/record_30s.sh
# - ./scripts/record_30s.sh "rtsp://user:pass@ip:554/..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_lib.sh"

load_env
require_vars CAMERA_HOST CAMERA_USER CAMERA_PASS RTSP_MAIN_PATH

RTSP_URL="${1:-rtsp://${CAMERA_USER}:${CAMERA_PASS}@${CAMERA_HOST}:554${RTSP_MAIN_PATH}}"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="/media/frigate/clips/manual/clip_${TS}.mp4"

echo "Recording 30s from: ${RTSP_URL}"

# Frigate images can ship ffmpeg outside PATH (for example under /usr/lib/ffmpeg/<ver>/bin/ffmpeg).
FFMPEG_BIN="$(
  docker_compose exec -T frigate sh -lc '
    for p in \
      ffmpeg \
      /usr/lib/ffmpeg/7.0/bin/ffmpeg \
      /usr/lib/ffmpeg/6.0/bin/ffmpeg \
      /usr/lib/ffmpeg/5.0/bin/ffmpeg \
      /usr/bin/ffmpeg
    do
      if [ "$p" = "ffmpeg" ]; then
        command -v ffmpeg >/dev/null 2>&1 && { echo ffmpeg; exit 0; }
      elif [ -x "$p" ]; then
        echo "$p"
        exit 0
      fi
    done
    exit 1
  ' 2>/dev/null || true
)"

if [[ -z "${FFMPEG_BIN}" ]]; then
  echo "Could not find ffmpeg inside the frigate container." >&2
  echo "Run: docker compose exec frigate sh -lc 'ls -l /usr/lib/ffmpeg /usr/bin 2>/dev/null'" >&2
  exit 1
fi

docker_compose exec -T frigate sh -lc \
  "mkdir -p /media/frigate/clips/manual && \
   '${FFMPEG_BIN}' -hide_banner -loglevel error -rtsp_transport tcp -i '${RTSP_URL}' -t 30 -c copy '${OUT}'"

echo "Saved: ./data/clips/manual/clip_${TS}.mp4"
