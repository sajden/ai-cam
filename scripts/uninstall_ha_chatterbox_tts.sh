#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${REPO_ROOT}/data/homeassistant/custom_components/aihub_chatterbox"

if [[ -d "${TARGET_DIR}" ]]; then
  sudo rm -rf "${TARGET_DIR}"
  echo "Removed: ${TARGET_DIR}"
else
  echo "Not installed: ${TARGET_DIR}"
fi

