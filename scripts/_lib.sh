#!/usr/bin/env bash
set -euo pipefail

# Shared helpers for scripts/:
# - Load `.env` consistently
# - Provide `docker_compose` wrapper (so scripts don't assume `docker-compose` v1)
# - Provide MQTT publish helper used for privacy/recording toggles

repo_root() {
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  echo "$d"
}

load_env() {
  local root env_file
  root="$(repo_root)"
  env_file="${root}/.env"
  if [[ ! -f "${env_file}" ]]; then
    echo "Missing .env at: ${env_file}" >&2
    echo "Create it from .env.example." >&2
    exit 1
  fi

  # Load .env as dotenv (not `source`), so values like
  # `A=b,c d` are handled correctly.
  while IFS= read -r line || [[ -n "${line}" ]]; do
    # Skip comments and empty lines.
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
    [[ "${line}" != *=* ]] && continue

    local key value
    key="${line%%=*}"
    value="${line#*=}"
    # Trim key whitespace.
    key="$(printf '%s' "${key}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    # Keep value raw (allow commas/spaces).
    export "${key}=${value}"
  done < "${env_file}"
}

require_vars() {
  # Fail fast if required vars are missing in .env.
  local missing=0
  for v in "$@"; do
    if [[ -z "${!v:-}" ]]; then
      echo "Missing required env var: ${v}" >&2
      missing=1
    fi
  done
  [[ "${missing}" -eq 0 ]] || exit 1
}

docker_compose() {
  # Prefer docker compose v2.
  if command -v docker >/dev/null 2>&1; then
    docker compose "$@"
  else
    echo "docker not found in PATH" >&2
    exit 1
  fi
}

ai_network_name() {
  # Matches docker-compose.yml networks.ai_net.name.
  # We keep it stable so helper containers can join the same network.
  echo "ai-cam-net"
}

mqtt_pub() {
  # Usage: mqtt_pub <topic> <payload>
  local topic="$1"
  local payload="$2"

  # We publish from a short-lived container so we don't need to install mosquitto tools in WSL.
  # 1) Try eclipse-mosquitto image if it has mosquitto_pub
  # 2) Fall back to a tiny mqtt client image otherwise

  # Try to use a mosquitto client that might exist in the mosquitto image.
  if docker image inspect eclipse-mosquitto:2 >/dev/null 2>&1; then
    if docker run --rm --network "$(ai_network_name)" eclipse-mosquitto:2 sh -lc "command -v mosquitto_pub >/dev/null 2>&1"; then
      docker run --rm --network "$(ai_network_name)" eclipse-mosquitto:2 \
        sh -lc "mosquitto_pub -h mosquitto -t '${topic}' -m '${payload}'"
      return
    fi
  fi

  # Fallback to a dedicated client image.
  docker run --rm --network "$(ai_network_name)" efrecon/mqtt-client \
    pub -h mosquitto -t "${topic}" -m "${payload}"
}
