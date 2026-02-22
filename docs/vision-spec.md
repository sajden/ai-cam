# Vision-spec (lokal videoanalys för reps/form)

Syfte: definiera hur video ska analyseras lokalt för triggers, rep-räkning och formfeedback.

## 1) Mål
- Reagera på kamerahändelser (hund/person/dans/morgon).
- Stödja uppdragssessioner (t.ex. armhävningar, stretch, squat-coachning).
- Ge kort, tydlig feedback i realtid.
- Aldrig skicka rå video/audio till moln.

## 2) Komponenter

### A) Frigate (eventnivå)
- Input: RTSP från Reolink.
- Output:
  - event (MQTT/webhook)
  - snapshots/klipp lokalt

Ansvar:
- billig, stabil 24/7-detektion
- trigga tyngre vision vid behov

### B) Vision Worker (ny lokal service)
- Input:
  - RTSP/go2rtc live eller snapshot-ström lokalt
  - styrsignal från `ai-hub` (start/stop uppdragssession)
- Output:
  - strukturerad text/data till `ai-hub` (JSON)

Ansvar:
- pose-estimering
- rep-räkning
- enkel form/fatigue-bedömning

### C) AI-hub (policy + orkestrering)
- Tar emot visionresultat.
- Avgör vilka svar/actions som ska ske (TTS, notis, logg, HA-action).
- Avgör om Codex behövs för textkunskap (aldrig rå media).

## 3) Modellstrategi

### 3.1 Eventdetektion (alltid på)
- Frigate (person/hund/motion)
- Låg kostnad, hög driftsäkerhet

### 3.2 Pose + reps (endast vid uppdrag/event)
- Lokal pose-modell i Vision Worker
- Kör med begränsad frame rate (ex. 5-10 FPS) för stabilitet/latens

### 3.3 Aktivitetsklassning (dans/stretch etc.)
- Enkel lokal klassning:
  - regelbaserat ovanpå pose/signaler
  - senare kan bytas till tränad klassmodell

## 4) Dataflöde

## 4.1 Eventflöde (hund/dans/morgon)
1. Frigate skapar event.
2. Event till `ai-hub`.
3. `ai-hub` kan begära kort analys från Vision Worker.
4. Vision Worker returnerar text/data (inte media).
5. `ai-hub` triggar HA-action (notis/TTS/Spotify).

## 4.2 Uppdragssession (reps/form)
1. Användare startar uppdrag via röst.
2. `ai-hub` sätter `task_session_mode=on`.
3. Vision Worker startar loop (ex. 5-10 FPS).
4. Vision Worker skickar:
   - `rep_count`
   - `phase` (up/down/hold)
   - `form_flags` (ex. "hips_sagging")
   - `fatigue_score` (0..1)
5. `ai-hub` ger kort TTS-cues:
   - "2 reps kvar"
   - "rakare rygg"
6. Stopp vid "avsluta uppdrag" eller timeout.

## 5) API-kontrakt (Vision Worker -> AI-hub)

Exempel payload:

```json
{
  "timestamp": "2026-02-11T13:30:00Z",
  "source": "vision_worker",
  "session_id": "task-abc-123",
  "mode": "task_session",
  "activity": "pushup",
  "rep_count": 12,
  "phase": "up",
  "form_flags": ["hips_sagging"],
  "fatigue_score": 0.78,
  "confidence": 0.86,
  "summary_sv": "12 reps klara. Formen tappar i höften."
}
```

Krav:
- endast text/metadata
- ingen bild/audio i payload

## 6) Formlogik (MVP)

### Armhävning (exempel)
- Landmärken: axel, armbåge, handled, höft, knä/fot.
- Rep:
  - nerfas när armbågsvinkel går under tröskel
  - uppfas när vinkel åter över tröskel
  - rep++ vid komplett cykel
- Formflaggor:
  - höft för låg/hög
  - ojämnt tempo
  - för kort range of motion

### Stretch/yoga (exempel)
- Ingen rep-räkning behövs alltid.
- Bedöm position mot målprofil (vinkelintervall + hålltid).
- Ge mjuka cues (inte spam):
  - "sänk axlarna"
  - "håll 10 sekunder"

## 7) Codex-roll (textkunskap, inte realtidsanalys)

Codex används endast när `ai-hub` behöver extern textkunskap, t.ex.:
- "hur utförs forward dog korrekt?"
- "vanliga fel i armhävningar"

Flöde:
1. `ai-hub` skickar textfråga.
2. Codex svarar med text.
3. `ai-hub` uppdaterar lokal "coaching-profil".
4. Vision Worker använder profilen lokalt.

Viktigt:
- Codex är inte i bildruta-för-bildruta-loopen.
- Rå media lämnar aldrig maskinen.

## 8) Prestandamål (MVP)
- End-to-end cue-latens: < 1.5 s i uppdragssession.
- Visionloop: 5-10 FPS räcker för rep/form i hemmascenario.
- CPU/GPU-budget: throttle vid hög belastning.

## 9) Failsafe
- Om visionfel:
  - fortsätt samtal utan vision
  - säg "jag tappade analysen, försök igen"
- Om Codex otillgänglig:
  - använd lokal fallback och säg att extern kunskap saknas just nu.

## 10) Acceptance
- AC-V1: Armhävningsreps räknas med stabilitet över minst 20 reps.
- AC-V2: Minst en relevant formflagga upptäcks i testscenario.
- AC-V3: Uppdragssession start/stop styr om visionloop körs.
- AC-V4: Ingen rå media går till Codex.
- AC-V5: Codex-kunskap kan förbättra textfeedback utan att påverka mediepolicy.

