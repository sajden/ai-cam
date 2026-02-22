#!/usr/bin/env bash
set -euo pipefail

# Start Windows audio_bridge.py with token/caller loaded from repo .env.
# Usage:
#   ./scripts/start_audio_bridge_windows.sh
#   ./scripts/start_audio_bridge_windows.sh "C:\\Github\\tools\\audio-bridge\\audio_bridge.py"

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

ROOT="$(repo_root)"
PS_SCRIPT="${ROOT}/scripts/start_audio_bridge.ps1"
ENV_FILE="${ROOT}/.env"
BRIDGE_SCRIPT_PATH="${1:-C:\\Github\\tools\\audio-bridge\\audio_bridge.py}"

if ! command -v powershell.exe >/dev/null 2>&1; then
  echo "powershell.exe not found (run from WSL with Windows interop enabled)." >&2
  exit 1
fi

if [[ ! -f "${PS_SCRIPT}" ]]; then
  echo "Missing PowerShell script: ${PS_SCRIPT}" >&2
  exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env: ${ENV_FILE}" >&2
  exit 1
fi

WIN_PS_SCRIPT="$(wslpath -w "${PS_SCRIPT}")"
WIN_ENV_FILE="$(wslpath -w "${ENV_FILE}")"

powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File "${WIN_PS_SCRIPT}" \
  -RepoEnvPath "${WIN_ENV_FILE}" \
  -BridgeScriptPath "${BRIDGE_SCRIPT_PATH}"
