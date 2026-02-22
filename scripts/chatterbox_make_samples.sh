#!/usr/bin/env bash
set -euo pipefail

# Generate WAV samples for predefined Chatterbox voices using Swedish text.
#
# Usage:
#   ./scripts/chatterbox_make_samples.sh
#   ./scripts/chatterbox_make_samples.sh "Hej, detta är ett test." 8
#   ./scripts/chatterbox_make_samples.sh "Hej, detta är ett test." 8 sv
#
# Args:
#   $1 text  (optional)
#   $2 limit (optional, 0 = all voices)
#   $3 language (optional, default: sv)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TEXT="${1:-Hej Sebastian. Detta är ett svenskt rösttest för ditt AI-hem. Hur låter min svenska?}"
LIMIT="${2:-0}"
LANGUAGE="${3:-sv}"
OUT_DIR="${ROOT_DIR}/data/chatterbox/samples"
mkdir -p "${OUT_DIR}"

voices_json="$(docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS http://chatterbox-tts:8000/get_predefined_voices)"

mapfile -t VOICES < <(python3 - <<'PY' "$voices_json" "$LIMIT"
import json
import sys

items = json.loads(sys.argv[1])
limit = int(sys.argv[2])

out = []
for item in items:
    fn = str(item.get("filename", "")).strip()
    if fn:
        out.append(fn)

if limit > 0:
    out = out[:limit]

for fn in out:
    print(fn)
PY
)

if [[ "${#VOICES[@]}" -eq 0 ]]; then
  echo "No voices found from /get_predefined_voices" >&2
  exit 1
fi

echo "Generating ${#VOICES[@]} samples in ${OUT_DIR}"
for voice in "${VOICES[@]}"; do
  payload="$(python3 - <<'PY' "$TEXT" "$voice" "$LANGUAGE"
import json
import sys

text = sys.argv[1]
voice = sys.argv[2]
language = sys.argv[3]
print(
    json.dumps(
        {
            "text": text,
            "output_format": "wav",
            "language": language,
            "voice_mode": "predefined",
            "predefined_voice_id": voice,
        },
        ensure_ascii=False,
    )
)
PY
)"

  out_file="${OUT_DIR}/${voice%.wav}_sv_test.wav"
  docker run --rm --network ai-cam-net curlimages/curl:8.6.0 -fsS \
    -H "Content-Type: application/json" \
    -X POST http://chatterbox-tts:8000/tts \
    -d "${payload}" > "${out_file}"
  echo "Wrote: ${out_file}"
done

echo
echo "Done. Lyssna på filerna i: ${OUT_DIR}"
echo "Tips: välj en röst och sätt i configuration.yaml:"
echo "  voice: predefined:<filename.wav>"
