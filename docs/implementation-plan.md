# Implementationsplan (nästa steg)

Den här planen utgår från din målbild:
- Lokalt först
- Ingen rå video/audio ut
- "Hey Codex" = explicit text-eskalering
- Uppdragssession aktiveras med fras

## Fas 1: Stabil bas (nu)
1. Behåll nuvarande stack: Frigate, Mosquitto, Home Assistant, Whisper, wake word.
2. Fortsätt med lokal LLM för standardläge.
3. Sätt tydlig policy:
   - Standard: allt lokalt.
   - Cloud: endast text och endast vid explicit trigger ("Hey Codex").

Klart när:
- Du kan prata med assistenten stabilt.
- Event från Frigate syns i HA.
- Ingen kamera-analys körs utan event/uppdragssession.

## Fas 2: Uppdragssession (kontrollerad aktivering)
1. Skapa helper i HA:
   - `input_boolean.task_session_mode`
2. Skapa röstkommandon/scripts:
   - "Starta uppdrag"
   - "Avsluta uppdrag"
3. Koppla så att vision-analys bara får köras när:
   - `task_session_mode = on` eller
   - ett Frigate-event triggat den.

Klart när:
- Frasen aktiverar uppdragssession.
- Uppdragssession ändrar faktiskt systemets beteende.

## Fas 3: AI-hub (hjärna + minne)
1. Skapa `ai-hub` service:
   - API för text in/text ut
   - Policy-router
   - Minne i SQLite (`./data/aihub`)
2. Spara konversationer:
   - tidsstämpel
   - intent
   - svar
   - session-id (t.ex. task-session)
3. Verktygsrouting:
   - HA-actions lokalt
   - Frigate snapshots lokalt
   - Codex endast via explicit trigger

Klart när:
- Samma fråga kan använda minne från tidigare samtal.
- "Hey Codex" går annan väg än lokal standard.

## Fas 4: Vision för reps och fatigue
1. Lägg till lokal visionmodul i `ai-hub`:
   - rep count
   - enkel form/fatigue-signal
2. Kör den endast under uppdragssession.
3. Skicka korta cues till TTS:
   - "2 reps kvar"
   - "rakare rygg"

Klart när:
- Du får rep-räkning i realtid under uppdragssession.

## Fas 5: Röstkvalitet
1. Välj slutlig TTS (lokal eller cloud text-only).
2. Om cloud-TTS används:
   - blockera kamera-relaterad text till cloud som default
   - kräv explicit godkännande för undantag

Klart när:
- Rösten är acceptabel för daglig användning.

## Beslut vi behöver låsa tidigt
1. Primär TTS-väg:
   - lokal först, cloud fallback
   - eller cloud först
2. "Hey Codex" policy:
   - får den se bara användarens fråga?
   - eller även lokalt minnessammanhang?
3. Kamera-audio:
   - 24/7 RTSP-audio in direkt från kameran
   - eller separat mic tills vidare
