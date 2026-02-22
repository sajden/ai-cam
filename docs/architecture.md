# Systemarkitektur (AI-cam)

Detta dokument beskriver hur hela systemet är tänkt att fungera, i vanlig svenska, och varför vi delar upp det i olika delar.

## Grundprinciper (dina krav)
- Inget "rått" ljud/video får lämna datorn.
- Kamera och analys är lokalt.
- Tvåvägsljud via Reolink är ett krav (ljud in från kamera + ljud ut till kamerahögtalare).
- Moln (t.ex. Codex) är valfritt och får bara få text, och bara när du uttryckligen ber om det (t.ex. "Hey Codex").
- Systemet ska vara aktivt 24/7, men "tyngre" analys ska bara starta vid event eller när du aktiverar en uppdragssession.

## Viktiga komponenter
- Kamera (Reolink): skickar RTSP video + audio in, samt ska användas för talkback audio out.
- Frigate: tar emot RTSP, gör detektion, spelar in event-klipp lokalt, exponerar snapshots/clips.
- Mosquitto (MQTT): lokal "event-buss" där Frigate kan publicera händelser och andra kan reagera.
- Home Assistant (HA): UI + automationer + Assist (röstpipeline och styrning av ditt smarta hem).
- STT (Whisper/Wyoming): audio -> text lokalt.
- Väckord (OpenWakeWord/Wyoming): lokal "hey ..." detektion (kräver en audio-källa 24/7).
- AI Orchestrator / "Brain" (framtida `ai-hub`): policy, minne (SQLite), routing mellan HA/vision/LLM.
- Vision/VLM (framtida): lokal bild/video-analys för t.ex. reps, pose, "vad händer".
- TTS (framtida, t.ex. Chatterbox): text -> tal med mer "mänsklig" röst.
- (Valfritt) Codex/moln-LLM: endast text, endast när du ber om det.

## Flöden (hög nivå)
### A) Passivt 24/7-läge
1. Frigate lyssnar på kameran (RTSP) och skapar events (person/hund/motion).
2. Event skickas på MQTT.
3. Ingen kontinuerlig uppdragsanalys kör om uppdragssession inte är på.

### B) Event-läge (t.ex. hund rör sig)
1. Frigate -> MQTT: "dog detected"
2. (Om policy tillåter) Brain hämtar snapshot/clip lokalt från Frigate.
3. Lokal vision kan analysera och skriva en kort text-sammanfattning.
4. HA kan skicka notis/automation och spara klipp lokalt.

### C) Samtalsläge (du pratar)
1. Idle: openwakeword lyssnar på rå PCM (ingen VAD/STT). Extremt lättviktigt.
2. Wake word detekterat → öppnar konversationsfönster (TTL ~90s).
3. Under konversation: Audio → VAD → Whisper STT → text.
4. Brain avgör:
   - smart-home intent → HA service calls
   - vanlig fråga → lokal LLM eller (om du säger "Hey Codex") till Codex (text-only)
5. Svar → TTS → kamerahögtalare. Speaker state rapporteras till ai-hub.
6. Under TTS-uppspelning: camera-listener pausar wake/STT (echo-skydd).
7. Konversation timeout → tillbaka till openwakeword idle.

### D) Uppdragssession (du aktiverar explicit)
1. Du säger t.ex. "Nu ska jag börja träna, räkna mina reps" eller "guida mig när jag lagar mat".
2. HA slår på `input_boolean.task_session_mode`.
3. Då får Brain starta en "session" och hämta relevanta snapshots lokalt för uppdraget.
4. Brain ger korta cues via TTS (och kan logga resultat i SQLite).

## Diagram (Mermaid)
Kopiera/visa i en Mermaid-kompatibel viewer (GitHub, vissa editors, etc).

```mermaid
flowchart TD
  CAM[Reolink E1 Pro<br/>RTSP Video+Audio In] -->|RTSP| FRIG[Frigate NVR<br/>Local ingest + events + clips]
  CAM -->|RTSP audio 24/7| AUD[camera-listener<br/>ffmpeg/rtsp->pcm]

  PHONE[Phone (Tailscale)] -->|VPN| HAUI[Home Assistant UI<br/>8123 (Tailscale-only)]
  PCUI[PC Browser UI<br/>127.0.0.1:8123] --> HAUI

  FRIG -->|Events| MQTT[MQTT (Mosquitto)<br/>Local event bus]
  FRIG -->|Clips/Snapshots| DATA[(./data/...<br/>clips/recordings/logs/models)]

  HA[Home Assistant Core<br/>Automations + Assist pipelines] --- HAUI
  MQTT --> HA
  FRIG -->|Integration (optional)| HA

  HA --> MODE[Helpers<br/>input_boolean.task_session_mode<br/>input_boolean.privacy_mode]
  MODE -->|gate| POLICY[Policy Router<br/>Local rules: what may run/leave box]

  AUD -->|idle: raw PCM| OWW[openwakeword<br/>Wake phrase: \"Hey Jarvis\"]
  OWW -->|wake detected| HUB[AI Orchestrator / \"Brain\"<br/>Intent + tools + routing]
  AUD -->|conversation active| STT[Whisper STT<br/>Audio -> Text]
  HAUI -. Push-to-talk mic .-> STT

  STT -->|user text| HUB
  HUB --> MEM[(SQLite Memory<br/>Conversations + facts)]
  MEM --> HUB

  HUB -->|Smart-home intent| HA
  HA -->|services/actions| DEV[Devices/Services<br/>lights, music, notifications]
  HA -->|notify| PHONE

  MQTT -->|event: person/dog/motion| HUB
  HUB -->|if POLICY allows (event or task_session_mode)| SNAP[Fetch snapshot/clip<br/>from Frigate local]
  SNAP --> VLM[Local Vision Model<br/>pose/rep count/activity]
  VLM -->|text summary| HUB

  HUB -->|ONLY if user says \"Hey Codex\"<br/>and POLICY allows| CODEX[(Codex / Cloud LLM)]
  CODEX -->|text response| HUB

  HUB -->|response text| TTS[Chatterbox TTS (local)<br/>Text -> Speech]
  TTS --> CVB[camera-voice-bridge<br/>go2rtc audio push]
  CVB --> CAMSPK[Camera Speaker<br/>Reolink talkback]
  CVB -->|speaker_playing| HUB
```

## Relaterade dokument
- `docs/coach-mode.md`
- `docs/wake-word.md`
- `docs/kravspec.md`
