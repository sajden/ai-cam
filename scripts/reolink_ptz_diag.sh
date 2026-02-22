#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/_lib.sh"

load_env

direction="${1:-all}"
case "${direction}" in
  all|left|right|up|down|reset) ;;
  *)
    echo "Usage: $0 [all|left|right|up|down|reset]" >&2
    exit 1
    ;;
esac

if ! docker compose ps --services --status running | grep -qx "aihub"; then
  echo "Starting aihub container..."
  docker compose up -d aihub >/dev/null
fi

export PTZ_DIAG_DIRECTION="${direction}"

docker compose exec -T aihub python - <<'PY'
import json
import os
import time

from app.reolink_client import ReolinkClient, _is_success_response, load_reolink_config

direction = os.getenv("PTZ_DIAG_DIRECTION", "all").strip().lower()
cfg = load_reolink_config()
if not cfg.host:
    raise SystemExit("AIHUB_REOLINK_HOST saknas i .env")

ops = {
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
}
sequence = ["left", "right", "up", "down"] if direction == "all" else [direction]
speed = max(1, min(64, int(os.getenv("AIHUB_REOLINK_PTZ_SPEED", "20"))))
duration = max(0.08, float(os.getenv("AIHUB_REOLINK_PTZ_BURST_SEC", "0.55")))


def dump(label: str, resp) -> None:
    ok, reason = _is_success_response(resp)
    raw = json.dumps(resp, ensure_ascii=False)
    print(f"{label}: ok={ok} reason={reason or '-'} raw={raw}")


client = ReolinkClient(cfg)
try:
    print("Disabling camera auto-track before PTZ test...")
    dump("auto_track_off", client.set_auto_tracking(False))

    if sequence == ["reset"]:
        print("Running reset only...")
        dump("reset", client.ptz_preset(0))
        raise SystemExit(0)

    for key in sequence:
        op = ops[key]
        print(f"\nPTZ {key} (op={op}, speed={speed}, duration={duration}s)")
        dump("start", client.ptz_control(op, speed=speed))
        time.sleep(duration)
        dump("stop", client.ptz_stop())
finally:
    client.close()
PY
