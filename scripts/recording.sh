#!/usr/bin/env bash
set -euo pipefail

# Toggle only recordings (leave detection on) using Frigate MQTT control topics.
#
# Requirements:
# - mosquitto + frigate running
# - CAMERA_NAME set in `.env` (defaults to reolink_e1pro)

if [[ -z "${1:-}" ]]; then
  echo "Usage: ./scripts/recording.sh <on|off>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_lib.sh"

load_env

CAMERA="${CAMERA_NAME:-reolink_e1pro}"
MODE="$1"

case "${MODE}" in
  on)
    mqtt_pub "frigate/${CAMERA}/recordings/set" "ON"
    echo "Recordings enabled for camera: ${CAMERA}"
    ;;
  off)
    mqtt_pub "frigate/${CAMERA}/recordings/set" "OFF"
    echo "Recordings disabled for camera: ${CAMERA}"
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    exit 1
    ;;
esac
