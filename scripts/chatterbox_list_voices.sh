#!/usr/bin/env bash
set -euo pipefail

# Lists available predefined voices from Chatterbox.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

json="$(docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS http://chatterbox-tts:8000/get_predefined_voices)"

python3 - <<'PY' "$json"
import json
import sys

items = json.loads(sys.argv[1])
for item in items:
    name = item.get("display_name", "")
    fn = item.get("filename", "")
    print(f"{name}\t{fn}")
PY
