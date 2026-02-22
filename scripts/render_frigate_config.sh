#!/usr/bin/env bash
set -euo pipefail

# Render a Frigate config file into ./data/config/frigate.yml.
#
# Why:
# - We want to keep camera credentials out of the git repo.
# - Frigate needs RTSP URLs in its config, and those include username/password.
#
# Input:
# - `.env` (CAMERA_HOST, CAMERA_USER, CAMERA_PASS, RTSP_* etc)
# - `frigate/config.template.yml` (committed template with placeholders)
#
# Output (gitignored):
# - `data/config/frigate.yml` (mounted read-only into the Frigate container)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/_lib.sh"

load_env

ROOT="$(repo_root)"
TEMPLATE="${ROOT}/frigate/config.template.yml"
OUT_DIR="${ROOT}/data/config"
OUT_FILE="${OUT_DIR}/frigate.yml"

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "Missing template: ${TEMPLATE}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

export ROOT
export TEMPLATE
export OUT_FILE

python3 - <<'PY'
import os
from pathlib import Path

template = Path(os.environ["TEMPLATE"])
out_file = Path(os.environ["OUT_FILE"])

text = template.read_text(encoding="utf-8")

def req_int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    return int(v)

def req_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "on"}

event_days = req_int("FRIGATE_EVENT_RETAIN_DAYS", 7)
snap_days = req_int("FRIGATE_SNAPSHOT_RETAIN_DAYS", 7)
snapshots_enabled = req_bool("FRIGATE_SNAPSHOTS_ENABLED", False)

detect_w = req_int("DETECT_WIDTH", 640)
detect_h = req_int("DETECT_HEIGHT", 360)
detect_fps = req_int("DETECT_FPS", 5)
live_include_sub = req_bool("FRIGATE_LIVE_INCLUDE_SUB", False)

cam_host = os.environ.get("CAMERA_HOST", "").strip()
cam_user = os.environ.get("CAMERA_USER", "").strip()
cam_pass = os.environ.get("CAMERA_PASS", "").strip()
rtsp_main = os.environ.get("RTSP_MAIN_PATH", "/h264Preview_01_main").strip()
rtsp_sub = os.environ.get("RTSP_SUB_PATH", "/h264Preview_01_sub").strip()
cam_name = os.environ.get("CAMERA_NAME", "reolink_e1pro").strip() or "reolink_e1pro"
record_audio_preset = os.environ.get("FRIGATE_RECORD_AUDIO_PRESET", "preset-record-generic-audio-aac").strip() or "preset-record-generic-audio-aac"

def yaml_escape(s: str) -> str:
    # Always quote to avoid surprises with ':' and special chars in passwords.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

if cam_host and cam_user and cam_pass:
    # If camera credentials exist, we inject the full RTSP URLs into the cameras block.
    main_url = f"rtsp://{cam_user}:{cam_pass}@{cam_host}:554{rtsp_main}"
    sub_url  = f"rtsp://{cam_user}:{cam_pass}@{cam_host}:554{rtsp_sub}"
    main_stream = f"{cam_name}_main"
    sub_stream = f"{cam_name}_sub"
    go2rtc_block = f"""go2rtc:
  streams:
    {main_stream}:
      - {yaml_escape(main_url)}
      - {yaml_escape(f"ffmpeg:{main_stream}#audio=opus")}
    {sub_stream}:
      - {yaml_escape(sub_url)}
      - {yaml_escape(f"ffmpeg:{sub_stream}#audio=opus")}
"""
    if live_include_sub:
        live_block = f"""    live:
      streams:
        Main: {yaml_escape(main_stream)}
        Sub: {yaml_escape(sub_stream)}
"""
    else:
        # Force Frigate live view to main stream for maximum remote quality/FPS.
        live_block = f"""    live:
      streams:
        Main: {yaml_escape(main_stream)}
"""

    cameras_block = f"""cameras:
  {cam_name}:
    ffmpeg:
      output_args:
        record: {yaml_escape(record_audio_preset)}
      inputs:
        - path: {yaml_escape(f"rtsp://127.0.0.1:8554/{main_stream}")}
          input_args: preset-rtsp-restream
          roles:
            - record
        - path: {yaml_escape(f"rtsp://127.0.0.1:8554/{sub_stream}")}
          input_args: preset-rtsp-restream
          roles:
            - detect
{live_block.rstrip()}
    detect:
      enabled: true
      width: {detect_w}
      height: {detect_h}
      fps: {detect_fps}
    motion:
      mask: []
    zones: {{}}
"""
else:
    # If the camera isn't configured yet, we keep an empty cameras object.
    # This lets Frigate boot and you can still use the UI + later add the camera.
    go2rtc_block = "go2rtc:\n  streams: {}\n"
    cameras_block = "cameras: {}\n"

repl = {
    "{{FRIGATE_EVENT_RETAIN_DAYS}}": str(event_days),
    "{{FRIGATE_SNAPSHOT_RETAIN_DAYS}}": str(snap_days),
    "{{FRIGATE_SNAPSHOTS_ENABLED}}": str(snapshots_enabled).lower(),
    "{{GO2RTC_BLOCK}}": go2rtc_block.rstrip() + "\n",
    "{{CAMERAS_BLOCK}}": cameras_block.rstrip() + "\n",
}

for k, v in repl.items():
    text = text.replace(k, v)

out_file.write_text(text, encoding="utf-8")

print(f"Wrote: {out_file}")
if cameras_block.strip() == "cameras: {}":
    print("Note: CAMERA_HOST/USER/PASS not set; wrote config with no cameras so Frigate can start.")
PY
