# Quickstart: Testing Humanize AI Companion Personality

**Branch**: `001-humanize-ai-companion` | **Date**: 2026-02-26

## Prerequisites

- Docker Desktop running with WSL2 backend
- `ai-hub` service built and running (`docker compose up -d --build ai-hub`)
- At least one registered identity in the system (existing setup)
- Camera speaker enabled (`AIHUB_CAMERA_SPEAK_ENABLED=1` in `.env`)

---

## Manual Acceptance Tests

### SC-001: Wake greeting variety (no phrase repeats more than twice in 10 triggers)

```bash
# Trigger the wake word 10 times in succession, note each response
# Simplest method: POST directly to the wake endpoint
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8080/v1/events/audio/wake \
    -H "Authorization: Bearer $AIHUB_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"conversation_id":"test-sc001","source":"audio"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('assistant_text',''))"
  sleep 2
done
```

**Pass**: No single phrase appears more than twice across the 10 responses.

---

### SC-002: Command confirmation variety (5 same commands → at least 3 distinct responses)

```bash
# Test Spotify pause confirmation
for i in $(seq 1 5); do
  curl -s -X POST http://localhost:8080/v1/events/audio/text \
    -H "Authorization: Bearer $AIHUB_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"conversation_id":"test-sc002","source":"audio","text":"pausa musik","allow_codex":false}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('assistant_text',''))"
  sleep 1
done
```

**Pass**: At least 3 distinct `assistant_text` values across the 5 calls.

---

### SC-003: Workout follow-up frequency (at least 3 in 10 sessions)

```bash
# Run 10 training sessions and count follow-up remarks heard via speaker
# Manually: start and stop workout 10 times, count times a follow-up remark is heard
# Programmatic check via logs:
docker compose logs ai-hub | grep "followup" | tail -20
```

**Pass**: Follow-up remark logged/spoken in at least 3 out of 10 sessions.

---

### SC-004: Social question handling (100% natural responses)

```bash
# Test social questions
for q in "hur mår du" "vad tycker du om musik" "är du glad idag"; do
  curl -s -X POST http://localhost:8080/v1/events/audio/text \
    -H "Authorization: Bearer $AIHUB_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"conversation_id\":\"test-sc004\",\"source\":\"audio\",\"text\":\"$q\",\"allow_codex\":true}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('assistant_text',''))"
done
```

**Pass**: Each response is a natural, warm Swedish reply — no "Som en AI kan jag inte..." or error output.

---

### FR-009: Minimal mode activation and persistence

```bash
# Activate minimal mode
curl -s -X POST http://localhost:8080/v1/events/audio/text \
  -H "Authorization: Bearer $AIHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test-fr009","source":"audio","text":"svara kortare","allow_codex":false}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('assistant_text',''))"

# Restart the ai-hub container to verify persistence
docker compose restart ai-hub

# Trigger wake word — should use short continuity phrases, no follow-ups
curl -s -X POST http://localhost:8080/v1/events/audio/wake \
  -H "Authorization: Bearer $AIHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test-fr009b","source":"audio"}'

# Deactivate minimal mode
curl -s -X POST http://localhost:8080/v1/events/audio/text \
  -H "Authorization: Bearer $AIHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test-fr009","source":"audio","text":"svara normalt","allow_codex":false}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('assistant_text',''))"
```

**Pass**: Confirmation "Okej, jag svarar kortare." on activation; preference survives restart; "Okej, jag svarar som vanligt igen." on deactivation.

---

### SC-005: Regression — existing functional behaviors unchanged

```bash
# Camera pan
curl -s -X POST http://localhost:8080/v1/events/audio/text \
  -H "Authorization: Bearer $AIHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test-sc005","source":"audio","text":"titta vänster","allow_codex":true}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('actions:', d.get('actions',[]))"

# Spotify search
curl -s -X POST http://localhost:8080/v1/events/audio/text \
  -H "Authorization: Bearer $AIHUB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test-sc005","source":"audio","text":"spela Bob Marley","allow_codex":true}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('actions:', d.get('actions',[]))"
```

**Pass**: Camera pan and Spotify actions still appear in `actions` array with zero regression.

---

## Inspecting the DB State

```bash
# Check response pool LRU state
docker compose exec ai-hub sqlite3 /data/aihub.db \
  "SELECT pool_name, variant_key, used_at FROM response_pool_usage ORDER BY pool_name, used_at DESC;"

# Check companion preferences
docker compose exec ai-hub sqlite3 /data/aihub.db \
  "SELECT key, value FROM mode_state WHERE key LIKE 'companion_pref_%';"
```

---

## New Environment Variables

These variables are optional (defaults work out of the box). Add to `.env` to override:

```bash
# Minimal mode verbal confirmations
AIHUB_MINIMAL_MODE_ON_ACK_TEXT=Okej, jag svarar kortare.
AIHUB_MINIMAL_MODE_OFF_ACK_TEXT=Okej, jag svarar som vanligt igen.

# Follow-up remark delay in seconds (default: 1.5)
AIHUB_FOLLOWUP_DELAY_SEC=1.5

# Follow-up remark probability 0.0–1.0 (default: 0.30 = 30%)
AIHUB_FOLLOWUP_PROBABILITY=0.30
```
