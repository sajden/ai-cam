# Väckfras och Startfras (hur det funkar hos oss)

Du vill ha:
- `Hej Codex` för att aktivera samtalsläge
- tydligt svar tillbaka, t.ex. `Hej! Hur kan jag hjälpa dig?`

Det är två olika nivåer:

## 1) Väckord på enhet (alltid lyssnande)

### openwakeword (standard sedan v2)

`camera-listener` använder nu **openwakeword** som dedikerad wakeword-detektor i idle-läge.
Detta ersätter den tidigare metoden (Whisper STT + textmatchning) och ger:

- **Massiv CPU-besparing:** Ingen VAD, ingen Whisper körs i idle. openwakeword är ~50MB vs ~75MB för Whisper tiny.
- **Alexa-liknande mönster:** Dedikerat wake word → ack → fråga.
- **Lägre latens:** openwakeword processar 80ms-chunks direkt utan att behöva vänta på hela talade segment.

#### Konfiguration

| Variabel | Default | Beskrivning |
|---|---|---|
| `CAMERA_LISTENER_WAKEWORD_ENGINE` | `openwakeword` | `openwakeword` eller `whisper` (fallback) |
| `CAMERA_LISTENER_OWW_MODEL` | `hey_jarvis` | Modellnamn (inbyggd i openwakeword) |
| `CAMERA_LISTENER_OWW_THRESHOLD` | `0.5` | Detektionströskel (0.0–1.0). Lägre = känsligare, högre = striktare. |

#### Hur det fungerar

1. I idle-läge matas rå PCM-audio direkt till openwakeword (inga VAD/STT-steg).
2. När openwakeword detekterar wake word → triggar wake via AIHub → öppnar konversationsfönster.
3. Under aktivt konversationsfönster körs full VAD → Whisper STT-pipeline som tidigare.
4. När konversationen timeout:ar (default 90s) → tillbaka till openwakeword idle.

#### Fallback till Whisper

Om openwakeword inte kan laddas (saknad dependency etc.) faller systemet automatiskt tillbaka till det gamla Whisper-baserade wake-detection-systemet. Du kan också tvinga det manuellt:

```bash
CAMERA_LISTENER_WAKEWORD_ENGINE=whisper
```

#### Troubleshooting

- **Ingen detektion:** Sänk `CAMERA_LISTENER_OWW_THRESHOLD` (t.ex. 0.3). Kontrollera att mikrofonen funkar med `scripts/test_wakeword.sh`.
- **Falska positiva:** Höj threshold (t.ex. 0.7).
- **"openwakeword requested but unavailable":** Kontrollera att `openwakeword` och `libgomp1` är installerade i Docker-imagen.
- **Custom wake word:** Byt `CAMERA_LISTENER_OWW_MODEL` till en annan inbyggd modell eller en .onnx-fil. Se [openwakeword docs](https://github.com/dscripka/openWakeWord).

### Äldre: Whisper-baserad wake detection

Det gamla systemet (fortfarande tillgängligt via `CAMERA_LISTENER_WAKEWORD_ENGINE=whisper`):
- Kör Whisper tiny/small STT kontinuerligt i idle
- Matchar transkriberad text mot `CAMERA_LISTENER_WAKE_PHRASES`
- Högre CPU-användning, men stödjer godtyckliga svenska fraser som "hej codex"

## 2) Väckfras i AIHub (textlogik)

I den här stacken ligger väckfraslogiken också i `ai-hub`:
- `AIHUB_WAKE_PHRASES=hej codex,hey codex`
- om texten bara är `hej codex` returnerar AIHub direkt:
  - `Hej! Hur kan jag hjälpa dig?`
- om texten är `hej codex ...fråga...` tas prefixet bort och frågan processas direkt

## Echo-skydd (speaker state)

När TTS spelas upp via kamerahögtalaren rapporterar `camera-voice-bridge` till ai-hub att högtalaren är aktiv. `camera-listener` frågar sedan ai-hub och skippar wake-detection/STT under uppspelning.

Flöde:
1. camera-voice-bridge → `POST /v1/speaker/state` (playing=true, duration_sec=X)
2. camera-listener → `GET /v1/speaker/state` (cachad 500ms)
3. Om speaker_playing=true → skippar openwakeword.feed() / STT
4. Auto-expiry baserat på duration → normal detektion återupptas

## Test

### Snabb loggfiltrering
```bash
./scripts/test_wakeword.sh
```
Streamer camera-listener-loggar filtrerat på wake/detect-events.

### Simulerad turn utan mikrofon
```bash
./scripts/test_voice_turn.sh "vad är klockan"
```
Skickar wake + turn till AIHub via curl.

## Kamera-mikrofon (nu)

Vi använder `camera-listener`-containern för always-on lokalt flöde:
- läser RTSP-ljud från `reolink_e1pro_main`
- kör openwakeword i idle (inget STT)
- vid wake: öppnar konversationsfönster, kör full Whisper STT
- skickar till AIHub vid väckfras + aktiv TTL-session
- sparar inte rå ljudström

## Framtida: Custom wake word

POC använder inbyggd `hey_jarvis`-modell. Custom "hej codex"-modell kan tränas senare med openwakeword:s träningsverktyg.
