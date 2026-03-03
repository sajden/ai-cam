# Quickstart: AI Companion — Identity, Memory & Embodiment

**Branch**: `002-face-recognition` | **Date**: 2026-03-03

---

## Prerequisites

- Docker Desktop with WSL2 backend
- NVIDIA GPU enabled in Docker Desktop (Settings > Resources > Enable GPU)
- NVIDIA Container Toolkit installed in WSL2
- Home Assistant running with Reolink integration configured
- Existing ai-cam stack running (ai-hub, mosquitto, go2rtc)

---

## Step 1: Configure environment

Add to `.env`:

```bash
# Face recognition service
FACE_RECOGNITION_API_KEY=change-me-strong-secret

# Thresholds and cooldowns
AIHUB_FACE_RECOGNITION_URL=http://face-recognition:8082
AIHUB_FACE_RECOGNITION_THRESHOLD=0.55
AIHUB_ARRIVAL_COOLDOWN_SEC=7200
AIHUB_UNKNOWN_PERSON_COOLDOWN_SEC=86400

# HA integration (for snapshot fetching)
AIHUB_HA_URL=http://homeassistant:8123
AIHUB_HA_TOKEN=<your-ha-long-lived-token>

# PTZ gestures
AIHUB_PTZ_GESTURES_ENABLED=1
AIHUB_PTZ_NOD_SPEED=10
AIHUB_PTZ_SHAKE_SPEED=10

# Proactive companion
AIHUB_MORNING_GREETING_TIME=07:00
AIHUB_PROACTIVE_ENABLED=1

# Memory extraction
AIHUB_MEMORY_EXTRACTION_ENABLED=1
```

---

## Step 2: Build and start face-recognition service

```bash
docker compose up -d --build face-recognition
```

Verify GPU is used:
```bash
docker compose logs face-recognition | grep -i "provider\|cuda\|gpu"
# Expected: "CUDA provider active: True"
```

---

## Step 3: Enroll yourself via API

```bash
curl -X POST http://localhost:8080/v1/persons/Sebastian/enroll \
  -F "image=@/path/to/photo.jpg"
# Response: {"ok": true, "name": "Sebastian", "message": "..."}
```

Or stand in front of the camera and say: **"Det här är Sebastian"**

---

## Step 4: Configure HA automation

In HA `configuration.yaml`:
```yaml
rest_command:
  notify_person_arrived:
    url: "http://aihub:8080/v1/events/person_arrived"
    method: POST
    content_type: "application/json"
    payload: >-
      {
        "event": "person_arrived",
        "camera_entity": "camera.reolink_e1pro",
        "snapshot_url": "http://homeassistant:8123/api/camera_proxy/camera.reolink_e1pro?token={{ state_attr('camera.reolink_e1pro', 'access_token') }}",
        "timestamp": "{{ now().isoformat() }}"
      }
```

Add automation in HA:
```yaml
alias: "AI companion: person arrived"
triggers:
  - trigger: state
    entity_id: binary_sensor.reolink_e1pro_person
    to: "on"
actions:
  - action: camera.snapshot
    target:
      entity_id: camera.reolink_e1pro
    data:
      filename: "/config/www/snapshots/arrival_{{ now().strftime('%Y%m%d_%H%M%S') }}.jpg"
  - action: camera.record
    target:
      entity_id: camera.reolink_e1pro
    data:
      filename: "/config/www/recordings/arrival_{{ now().strftime('%Y%m%d_%H%M%S') }}.mp4"
      duration: 20
      lookback: 5
  - action: rest_command.notify_person_arrived
mode: single
```

Restart HA to pick up `rest_command`.

---

## Step 5: Test arrival flow

1. Walk out of camera view for 2+ hours (or temporarily set `AIHUB_ARRIVAL_COOLDOWN_SEC=30` for testing)
2. Walk back into frame
3. Expected within 5 seconds: TTS greeting + camera nod

---

## Step 6: Frigate migration (optional, later phase)

When ready to remove Frigate:

```bash
# 1. Add go2rtc standalone service to docker-compose.yml
# 2. Update camera-listener RTSP URL:
#    CAMERA_LISTENER_RTSP_URL=rtsp://go2rtc:8554/reolink_e1pro_main
# 3. Update AIHUB_GO2RTC_BASE_URL=http://go2rtc:1984
# 4. Remove frigate service
docker compose up -d --build
docker compose stop frigate
docker compose rm frigate
```

---

## Troubleshooting

| Symptom | Check |
|---|---|
| "CPUExecutionProvider" in face-recognition logs | Run `pip list \| grep onnxruntime` — ensure only `onnxruntime-gpu` installed |
| Face recognition always returns unknown | Lower `AIHUB_FACE_RECOGNITION_THRESHOLD` to 0.45, enroll with 3+ photos |
| No greeting on arrival | Check HA automation fires: HA logs > binary_sensor state change. Check ai-hub logs for `/v1/events/person_arrived` |
| PTZ not moving | Check `AIHUB_PTZ_GESTURES_ENABLED=1` and Reolink creds in env |
| HA snapshot returns 401 | Regenerate HA long-lived token and update `AIHUB_HA_TOKEN` |
