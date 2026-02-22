#!/usr/bin/env bash
set -euo pipefail

# Show Codex login status and codex-gateway health.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cd "$(repo_root)"

docker_compose up -d codex-gateway >/dev/null
docker_compose exec codex-gateway codex login status

echo
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
