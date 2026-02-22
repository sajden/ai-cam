#!/usr/bin/env bash
set -euo pipefail

# Start codex-gateway and run Codex device-auth login inside the container.
# Auth is persisted in ./data/codex-auth via the compose volume mount.

source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

cd "$(repo_root)"

docker_compose up -d codex-gateway
docker_compose exec codex-gateway codex login --device-auth

echo "Done: Codex login finished (or already active)."
