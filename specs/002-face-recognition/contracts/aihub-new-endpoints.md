# Contract: ai-hub New Endpoints

**Service**: `aihub` (existing, extended)
**Base URL**: `http://aihub:8080` (internal) / `http://127.0.0.1:8080` (host)

---

## POST /v1/events/person_arrived

Called by HA automation when Reolink person detection fires.

**Request**:
```json
{
  "event": "person_arrived",
  "camera_entity": "camera.reolink_e1pro",
  "snapshot_url": "http://homeassistant:8123/api/camera_proxy/camera.reolink_e1pro?token=<token>",
  "timestamp": "2026-03-03T14:22:01.123456+01:00"
}
```

**Flow** (internal):
1. Fetch snapshot JPEG from `snapshot_url`
2. POST to `face-recognition:8082/recognize`
3. Check `person_presence` for arrival vs. already-home
4. If new arrival + known person → speak greeting + PTZ nod + bind identity
5. If new arrival + unknown person + cooldown elapsed → speak "vem är du?"
6. If already home → update `last_seen_at`, update `active_person_name` silently

**Response 200**:
```json
{
  "ok": true,
  "identity": "Sebastian",
  "action": "arrival_greeting"
}
```

**Response 200 (already home)**:
```json
{
  "ok": true,
  "identity": "Sebastian",
  "action": "presence_updated"
}
```

---

## POST /v1/persons/{name}/enroll

Enroll or update face for a person. Called by voice enrollment handler in main.py or directly via API.

**Request**:
```
Content-Type: multipart/form-data
Field: image (JPEG bytes, optional — uses current camera frame if omitted)
```

**Response 200**:
```json
{
  "ok": true,
  "name": "Sebastian",
  "message": "Ok, jag kommer komma ihåg Sebastian!"
}
```

---

## GET /v1/persons

List all enrolled persons and their presence state.

**Response 200**:
```json
{
  "persons": [
    {
      "name": "Sebastian",
      "embedding_count": 3,
      "last_seen_at": "2026-03-03T14:22:01Z",
      "is_home": true
    }
  ]
}
```

---

## HA Automation Contract

HA calls ai-hub using `rest_command`. The HA `configuration.yaml` must define:

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

Automation trigger:
```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.reolink_e1pro_person
    to: "on"
```
