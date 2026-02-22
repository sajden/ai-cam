# Routing-tabell (AI-hub)

Syfte: definiera exakt hur triggers routas, vilka villkor som gäller, och vad som får lämna maskinen.

## Policy-nyckel
- `Egress = none`: inget lämnar maskinen.
- `Egress = text-only`: endast text får lämna maskinen.
- `Raw media`: video, snapshots, ljud rådata. Detta är alltid blockerat utåt.

## Routing-profiler
- `local_first` (default): lokal LLM först, Codex vid explicit trigger.
- `codex_first` (valbar): Codex för de flesta textfrågor, men fortfarande text-only.
- Båda profilerna följer samma mediepolicy: rå video/audio lämnar aldrig maskinen.

## Routing

| ID | Trigger | Villkor | Lokal action | Codex tillåten | Egress | Timeout/Cooldown |
|---|---|---|---|---|---|---|
| R1 | `camera:dog_detected` | confidence >= tröskel, ej `privacy_mode` | Spara kort klipp, skicka HA-notis till telefon | Nej | none | cooldown 120s per zon |
| R2 | `camera:dance_detected` | confidence >= tröskel, ej `privacy_mode` | Starta Spotify-låt via HA | Nej | none | cooldown 90s |
| R3 | `camera:morning_presence` | tid inom morgonfönster, person hemma, ej `privacy_mode` | TTS-hälsning + öppna kort `conversation_mode`-fönster för följdfråga | Ja (för textfrågor) | text-only | max 1 gång per morgon, auto-lyssna 20-30s |
| R4 | `audio:wake_word` | wake phrase match | Öppna `conversation_mode` | Nej | none | session TTL 90s |
| R5 | `audio:conversation_turn` | inom aktiv konversationssession | STT -> intent -> svar -> TTS + minneshämtning | Ja (beroende på profil, alltid text-only) | text-only | förläng TTL vid varje ny user-turn |
| R6 | `audio:start_task_session` | intent = uppdrag start (ex. coachning/guidning) | Sätt `input_boolean.task_session_mode=on`, starta uppdragssession | Ja (för kunskapsstöd/instruktioner) | text-only | session timeout 10-20 min inaktivitet |
| R7 | `audio:end_task_session` | intent = uppdrag stopp | Sätt `input_boolean.task_session_mode=off`, stoppa kontinuerlig analys | Nej | none | omedelbar |
| R8 | `task_session:analysis_tick` | `task_session_mode=on` och ej `privacy_mode` | Hämta lokal snapshot, kör lokal vision, ge kort cue via TTS | Nej (default) | none | intervall t.ex. 1-2s / enligt last |
| R9 | `audio:hey_codex_query` | explicit fras "Hey Codex" + policy tillåter | Skicka textfråga till Codex, ta textsvar, TTS lokalt | Ja | text-only | 1 request åt gången per session |
| R10 | `camera:event_with_privacy_mode` | `privacy_mode=on` | Logga event minimalt, inga aktiva svar/utrop | Nej | none | n/a |

## Sessionregler

### Conversation session
- Start: wake word.
- Aktiv: varje ny användarfras förlänger sessionen.
- Slut: timeout eller explicit "avsluta samtal".
- Minne: tidigare konversationer hämtas lokalt från SQLite även i ny wake-word-session (långsiktigt minne).

### Task session
- Start: röstkommando under konversation, t.ex. "Starta uppdrag, coacha min squat".
- Är en del av samma `conversation_id`.
- Slut: "Avsluta uppdrag" eller timeout.
- Tillåter återkommande lokal kameraanalys under sessionen.

## Data som får lämna systemet

Tillåtet vid Codex-route:
- användarens textfråga
- frivilligt: lokal sammanfattningstext om policy tillåter

Obs:
- Även text kan vara känslig. Policy ska kunna blockera kamera-härledd text till Codex när du vill.

Aldrig tillåtet:
- RTSP-ström
- snapshots/klipp
- rå audio

## Acceptance (routing)
- AC-R1: Hundevent ger klipp + notis utan molntrafik.
- AC-R2: Dansevent startar rätt Spotify-låt.
- AC-R3: "Hey Siri" öppnar konversation som klarar följdfrågor.
- AC-R4: "Hey Codex" skickar endast text, aldrig media.
- AC-R5: Uppdragssession start/stop fungerar och styr analys-loop.
