# Trigger-spec (kamera + ljud)

Syfte: göra trigger-logiken entydig så systemet beter sig förutsägbart.

## 1) Triggerfamiljer

Systemet har exakt två ingångar:
- Kameratrigger: event från videoanalys.
- Ljudtrigger: wake word + tal.

Allt som händer i systemet måste komma från någon av dessa två.

## 2) Globala lägen (state)

- `idle`: systemet väntar.
- `event_mode`: körs när kamerahändelse triggat.
- `conversation_mode`: körs efter wake word/tal.
- `task_session_mode`: explicit uppdragssession med extra analys (coachning, guidning, etc).
- `privacy_mode`: blockerar vissa actions enligt policy.

Prioritet:
1. `privacy_mode` (högst)
2. `task_session_mode`
3. `conversation_mode`
4. `event_mode`
5. `idle`

## 3) Kameratrigger

Källa:
- Frigate event (MQTT/webhook), t.ex. `person`, `dog`, `motion`.

Regel:
- Event får trigga analys/action utan wake word.
- Event får aldrig skicka rå video/audio till moln.
- Event får bara ge lokala actions, eller text-only eskalering om policy uttryckligen tillåter.

Exempelregler:
- Hund går förbi:
  - spara kort klipp
  - skicka notis till telefon
- Jag dansar:
  - trigga lokal klassning "dans"
  - starta Spotify-låt via Home Assistant
- Morgonhälsning:
  - person upptäcks inom morgonfönster + hemma-läge
  - spela upp "God morgon Sebastian"

## 4) Ljudtrigger

Källa:
- Wake word ("Hej Siri" eller valt frasord) + efterföljande tal.

Regel:
- Wake word öppnar `conversation_mode`.
- `conversation_mode` har sessionstimer (ex. 90 s).
- Varje ny användarfras förlänger timern.
- Vid timeout: tillbaka till `idle`.
- Om användaren ber om ett aktivt uppdrag (t.ex. "coacha mig", "guida mig steg för steg"),
  skapas en `task_session_mode` kopplad till samma `conversation_id`.

Konsekvens:
- Du kan ha flerturnssamtal:
  - "Hej Siri, jag ska laga köttfärssås"
  - "Jag har stekt löken, vad är nästa steg?"

Systemet använder samma `conversation_id` under aktiv session.
`task_session_mode` är en under-sessionsnivå av konversationen, inte ett separat fristående triggerflöde.

## 5) Routing-regler (AI)

Varje trigger blir ett standardiserat uppdrag till AI-hub:
- `source`: `camera` eller `audio`
- `intent`: t.ex. `notify_dog`, `task_start`, `recipe_help`
- `confidence`
- `context_refs`: lokala referenser (snapshot-id, clip-path, conversation-id)

Routern väljer:
- Home Assistant action (lampor, Spotify, notis)
- Lokal LLM
- Codex/moln-LLM (endast vid explicit trigger, text-only)

## 6) "Hey Codex" policy

`Hey Codex` betyder:
- denna fråga får gå till moln-LLM
- payload är text, aldrig rå media

Default utan "Hey Codex":
- lokal väg först

Valbar profil:
- `codex_first`: Codex används för de flesta textfrågor, men fortfarande text-only och aldrig rå media.

## 7) Anti-spam och säkerhet

- Cooldown per eventtyp (ex. hund-notis max 1 gång/2 min).
- Dubblettskydd för samma händelse.
- Minsta confidence innan action.
- Quiet hours för TTS-utrop (notis kan fortfarande skickas).

## 8) Acceptance för triggers

- AC-T1: Hundevent triggar klipp + notis.
- AC-T2: Dansevent triggar Spotify-action.
- AC-T3: Morgonevent triggar hälsning.
- AC-T4: Wake word öppnar samtal, följdfråga fungerar inom sessionstimer.
- AC-T4b: Aktivt uppdrag (task session) kan startas inuti en pågående konversation.
- AC-T4c: Ny wake-word-session kan hämta relevant historik från lokalt minne.
- AC-T5: "Hey Codex" skickar endast text till molnväg.
- AC-T6: Utan trigger sker ingen tung analys.
