# Quickstart: Desk Presence Tracking

**Feature**: `004-presence-tracking`

## What Gets Built

A background thread in `ai-hub` polls the Reolink person sensor every 5s via HA REST API, records each away-trip to SQLite, and injects a daily/weekly summary into Jarvis's system prompt.

## Environment Variables to Add to `.env`

```env
# Desk presence tracking
AIHUB_PRESENCE_ENABLED=1
AIHUB_PRESENCE_ENTITY=binary_sensor.reolink_e1pro_person
AIHUB_PRESENCE_POLL_SEC=5
AIHUB_PRESENCE_MIN_TRIP_SEC=60
AIHUB_PRESENCE_MAX_TRIP_SEC=14400
AIHUB_PRESENCE_SITTING_ALERT_SEC=7200
```

## Deploy

```bash
docker compose up -d --build aihub
```

No other services need rebuilding.

## Verify It Works

1. Check logs: `docker compose logs aihub | grep presence`
   Should see: `Presence tracker started (entity=binary_sensor.reolink_e1pro_person, poll=5s)`

2. Walk away from the camera for 90+ seconds, return, then ask Jarvis:
   *"hur många gånger har jag gått ifrån datorn idag?"*
   Expected: Jarvis reports at least 1 trip with correct duration.

3. Check DB directly:
   ```bash
   docker exec ai-cam-aihub python3 -c "
   import sqlite3, json
   c = sqlite3.connect('/data/aihub.db')
   rows = c.execute('SELECT * FROM desk_trips ORDER BY id DESC LIMIT 5').fetchall()
   for r in rows: print(r)
   "
   ```

## Disable Without Rebuild

```env
AIHUB_PRESENCE_ENABLED=0
```
Then `docker compose up -d aihub` (no `--build` needed — env-only change).
