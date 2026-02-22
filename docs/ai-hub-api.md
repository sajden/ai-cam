# AI-hub API-spec (MVP)

Syfte: definiera ett stabilt kontrakt mellan Home Assistant, Frigate, Vision Worker och AI-hub.

Bas-URL (internt Docker-nät):
- `http://aihub:8080`

Version:
- Alla endpoints under `/v1`

## 1) Principer
- AI-hub tar emot endast lokala events och text.
- Rå media (video/audio/snapshots) skickas inte genom API utanför lokalt nät.
- Codex-route är text-only och styrs av policy.

## 2) Auth (MVP)
- Internt nät + enkel bearer-token:
  - Header: `Authorization: Bearer <AIHUB_TOKEN>`
- Token sätts i `.env` och injiceras till relevanta services.

## 3) State-model
- `idle`
- `event_mode`
- `conversation_mode`
- `task_session_mode`
- `privacy_mode` (flagga som kan vara aktiv samtidigt)

## 4) Endpoints

## 4.1 Health
`GET /v1/health`

Response:
```json
{
  "ok": true,
  "service": "aihub",
  "version": "0.1.0"
}
```

## 4.2 Mode status
`GET /v1/mode`

Response:
```json
{
  "current_mode": "conversation_mode",
  "privacy_mode": false,
  "task_session_mode": true,
  "conversation_id": "conv-123",
  "task_session_id": "task-456"
}
```

## 4.3 Sätt mode/flaggor
`POST /v1/mode`

Request:
```json
{
  "set": {
    "privacy_mode": false,
    "task_session_mode": true
  },
  "reason": "voice_command_start_task"
}
```

Response:
```json
{
  "ok": true,
  "applied": {
    "privacy_mode": false,
    "task_session_mode": true
  }
}
```

## 4.4 Kamerahändelse (Frigate -> AI-hub)
`POST /v1/events/camera`

Request:
```json
{
  "event_id": "frigate-evt-001",
  "type": "dog_detected",
  "camera": "reolink_e1pro",
  "confidence": 0.87,
  "zone": "living_room",
  "timestamp": "2026-02-11T13:45:00Z",
  "refs": {
    "clip_path": "/media/frigate/clips/...",
    "snapshot_path": "/media/frigate/clips/..."
  }
}
```

Response:
```json
{
  "ok": true,
  "route_id": "R1",
  "actions": [
    "save_clip",
    "notify_phone"
  ],
  "egress": "none"
}
```

## 4.5 Wake-word trigger
`POST /v1/events/audio/wake`

Request:
```json
{
  "device": "reolink_mic",
  "wake_phrase": "hej siri",
  "timestamp": "2026-02-11T13:46:00Z"
}
```

Response:
```json
{
  "ok": true,
  "conversation_id": "conv-123",
  "mode": "conversation_mode",
  "ttl_seconds": 90
}
```

## 4.6 Konversationsturn (STT text -> AI-hub)
`POST /v1/conversation/turn`

Request:
```json
{
  "conversation_id": "conv-123",
  "source": "audio",
  "text": "Hej Siri, jag har stekt löken. Vad är nästa steg?",
  "allow_codex": true,
  "timestamp": "2026-02-11T13:46:10Z"
}
```

Response:
```json
{
  "ok": true,
  "assistant_text": "Bra! Nästa steg är att tillsätta köttfärsen och bryna den.",
  "used_brain": "codex",
  "actions": [],
  "egress": "text-only"
}
```

Kommentar:
- `allow_codex` styrs av route/policy (t.ex. "Hey Codex" eller `codex_first`).

## 4.7 Starta/stoppa uppdragssession
`POST /v1/task/start`

Request:
```json
{
  "conversation_id": "conv-123",
  "task_type": "fitness_coach",
  "task_goal": "Räkna armhävningar och säg till när form tappar",
  "timestamp": "2026-02-11T13:47:00Z"
}
```

Response:
```json
{
  "ok": true,
  "task_session_id": "task-456",
  "task_session_mode": true
}
```

`POST /v1/task/stop`

Request:
```json
{
  "task_session_id": "task-456",
  "reason": "voice_command"
}
```

Response:
```json
{
  "ok": true,
  "task_session_mode": false
}
```

## 4.8 Visionresultat (Vision Worker -> AI-hub)
`POST /v1/events/vision`

Request:
```json
{
  "task_session_id": "task-456",
  "activity": "pushup",
  "rep_count": 12,
  "phase": "up",
  "form_flags": ["hips_sagging"],
  "fatigue_score": 0.78,
  "confidence": 0.86,
  "summary_sv": "12 reps klara. Formen tappar i höften.",
  "timestamp": "2026-02-11T13:47:22Z"
}
```

Response:
```json
{
  "ok": true,
  "actions": [
    "tts_cue"
  ],
  "tts_text": "Två reps kvar. Håll höften rak."
}
```

## 4.9 Policybeslut (debug/insyn)
`POST /v1/policy/evaluate`

Request:
```json
{
  "source": "camera",
  "intent": "morning_presence",
  "candidate_egress": "text-only",
  "contains_camera_derived_text": true
}
```

Response:
```json
{
  "allow": false,
  "reason": "camera_text_blocked_by_policy",
  "egress": "none",
  "route_id": "R3"
}
```

## 4.10 Minne
`GET /v1/memory/context?conversation_id=conv-123&k=10`

Response:
```json
{
  "ok": true,
  "items": [
    {
      "timestamp": "2026-02-11T13:20:00Z",
      "role": "user",
      "text": "Jag vill laga köttfärssås"
    },
    {
      "timestamp": "2026-02-11T13:21:00Z",
      "role": "assistant",
      "text": "Börja med att hacka lök och vitlök."
    }
  ]
}
```

## 5) Felkoder
- `400`: ogiltig payload
- `401`: saknad/fel token
- `409`: konflikt i state (t.ex. start task när privacy_mode blockerar)
- `429`: rate-limit/cooldown
- `500`: internt fel

## 6) Koppling till routing-tabellen
- `route_id` i svar mappar till `docs/routing-table.md` (`R1..R10`).
- AI-hub måste logga:
  - `route_id`
  - valt brain (`local`/`codex`)
  - egress (`none`/`text-only`)
  - policyskäl vid blockering

