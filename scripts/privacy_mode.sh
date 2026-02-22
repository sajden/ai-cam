#!/usr/bin/env bash
set -euo pipefail

# Privacy mode toggle for a single camera using Frigate's MQTT control topics.
#
# What it does:
# - enable  => turns OFF detection + recordings for the camera (privacy ON)
# - disable => turns ON  detection + recordings for the camera (privacy OFF)
#
# Requirements:
# - mosquitto + frigate running
# - CAMERA_NAME set in `.env` (defaults to reolink_e1pro)

if [[ -z "${1:-}" ]]; then
  echo "Usage: ./scripts/privacy_mode.sh <enable|disable>"
  echo "  enable  = privacy ON  (disable detect + recordings)"
  echo "  disable = privacy OFF (enable detect + recordings)"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_lib.sh"

load_env

CAMERA="${CAMERA_NAME:-reolink_e1pro}"
MODE="$1"

case "${MODE}" in
  enable)
    mqtt_pub "frigate/${CAMERA}/detect/set" "OFF"
    mqtt_pub "frigate/${CAMERA}/recordings/set" "OFF"
    echo "Privacy enabled for camera: ${CAMERA}"
    ;;
  disable)
    mqtt_pub "frigate/${CAMERA}/detect/set" "ON"
    mqtt_pub "frigate/${CAMERA}/recordings/set" "ON"
    echo "Privacy disabled for camera: ${CAMERA}"
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    exit 1
    ;;
esac
