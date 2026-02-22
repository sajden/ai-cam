#!/usr/bin/env bash
set -euo pipefail

# Force a fresh Codex OAuth (device-auth) flow inside codex-gateway.
# Useful when quota/account changed or login state got stale.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cd "$(repo_root)"

docker_compose up -d codex-gateway

echo "Preparing fresh Codex auth state..."
docker_compose exec codex-gateway sh -lc '
  set -eu
  mkdir -p /root/.codex/backups
  ts="$(date +%Y%m%d-%H%M%S)"
  if [ -f /root/.codex/auth.json ]; then
    cp /root/.codex/auth.json "/root/.codex/backups/auth-${ts}.json"
    echo "Backed up old auth to /root/.codex/backups/auth-${ts}.json"
  fi
  rm -f /root/.codex/auth.json
  rm -rf /root/.codex/sessions/* /root/.codex/tmp/* || true
'

echo
echo "Starting new device-auth flow (follow URL + code)..."
docker_compose exec codex-gateway codex login --device-auth

echo
echo "Final login status:"
docker_compose exec codex-gateway codex login status

echo
echo "Gateway health:"
for _ in $(seq 1 20); do
  if docker run --rm --network "$(ai_network_name)" curlimages/curl:8.6.0 -fsS \
    http://codex-gateway:8090/v1/health; then
    echo
    exit 0
  fi
  sleep 1
done

echo "ERROR: codex-gateway health did not become ready in time." >&2
exit 1
