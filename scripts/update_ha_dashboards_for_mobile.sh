#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-mobile}"
HOST_IP="${2:-192.168.50.215}"
HA_DIR="/home/sajden/github/ai-cam/data/homeassistant/.storage"

sudo python3 - "$MODE" "$HOST_IP" "$HA_DIR" <<'PY'
import json
import sys
from pathlib import Path

mode = sys.argv[1]
host_ip = sys.argv[2]
storage_dir = Path(sys.argv[3])

if mode == "revert":
    operatorhub_url = "http://localhost:5173/boards/daily"
    castboard_url = "http://localhost:8080/castboard"
    busschema_url = "http://localhost:8080/departures"
    busschema_title = "Buss"
else:
    operatorhub_url = f"http://{host_ip}:8080/operatorhub-app/boards/daily"
    castboard_url = f"http://{host_ip}:8080/castboard"
    busschema_url = f"http://{host_ip}:8080/departures"
    busschema_title = "Busschema"

files = {
    storage_dir / "lovelace_dashboards": ("dashboards", None),
    storage_dir / "lovelace.operatorhub": ("operatorhub", operatorhub_url),
    storage_dir / "lovelace.castboard": ("castboard", castboard_url),
    storage_dir / "lovelace.hemkontroll": ("busschema", busschema_url),
}

for path, spec in files.items():
    data = json.loads(path.read_text())
    kind, url = spec
    if kind == "dashboards":
        for item in data["data"]["items"]:
            if item.get("id") == "hemkontroll":
                item["title"] = busschema_title
    elif kind == "busschema":
        data["data"]["config"]["views"][0]["cards"][0]["url"] = url
    else:
        data["data"]["config"]["views"][0]["cards"][0]["url"] = url
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

if mode == "revert":
    print("Reverted Home Assistant dashboard URLs to localhost.")
else:
    print(f"Updated Home Assistant dashboards for mobile using host {host_ip}.")
PY

echo
echo "Next:"
echo "1. Restart Home Assistant"
echo "2. Reopen the HA app"
echo "3. Check Operator Hub, Castboard, and Busschema/Buss in the sidebar"
