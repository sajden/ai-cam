#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-data/aihub/aihub.db}"
LIMIT="${2:-20}"

if [[ ! -f "$DB_PATH" ]]; then
  echo "DB not found: $DB_PATH" >&2
  exit 1
fi

has_table="$(sqlite3 "$DB_PATH" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='turn_metrics' LIMIT 1;")"
if [[ "$has_table" != "1" ]]; then
  echo "Table turn_metrics does not exist yet."
  echo "Restart aihub first so db.init_db() creates it."
  exit 0
fi

sqlite3 -header -column "$DB_PATH" "
SELECT
  id,
  created_at,
  used_brain,
  ROUND(stt_to_aihub_ms, 1) AS stt_to_aihub_ms,
  ROUND(codex_ms, 1) AS codex_ms,
  codex_search_used,
  ROUND(camera_actions_ms, 1) AS camera_actions_ms,
  ROUND(aihub_total_ms, 1) AS aihub_total_ms,
  ROUND(tts_request_ms, 1) AS tts_request_ms,
  tts_ok,
  tts_reason,
  user_text
FROM turn_metrics
ORDER BY id DESC
LIMIT $LIMIT;
"
