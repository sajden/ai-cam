# Coach Mode (Voice-Activated Training Mode)

Goal: you say a phrase (after wake word / push-to-talk) like:
- "Nu ska jag börja träna. Räkna mina reps."

And the system switches into an "active" mode where *camera analysis is allowed* (locally),
and you get short coaching feedback (voice + notifications).

This doc focuses on the **MVP wiring** inside Home Assistant. Rep counting via vision is a later step.

## Key Idea: A Local Mode Switch

We represent "coach mode" as a Home Assistant helper:
- `input_boolean.coach_mode`

Everything that is privacy-sensitive (continuous camera snapshots, pose estimation, etc.) should only run when:
- `coach_mode = on`

## MVP Setup (No Custom Code)

### 1) Create Helpers (UI)
Home Assistant:
1. `Inställningar` -> `Enheter och tjänster` -> `Hjälpare`
2. Create:
   - Toggle helper:
     - Name: `Coachläge`
     - Entity: `input_boolean.coach_mode`

Optional helpers (nice-to-have later):
- `input_select.coach_workout` (e.g. squat/pushups)
- `counter.coach_reps` (rep counter)

### 2) Create Scripts (UI)
Create two scripts:

**Script: Start Coach Mode**
- Service: `input_boolean.turn_on`
  - Target: `input_boolean.coach_mode`
- Service: `persistent_notification.create`
  - Message: `Coachläge på`

**Script: Stop Coach Mode**
- Service: `input_boolean.turn_off`
  - Target: `input_boolean.coach_mode`
- Service: `persistent_notification.create`
  - Message: `Coachläge av`

### 3) Voice Activation (Assist)
In Assist (your Swedish assistant), you want the conversation agent to call the scripts.

You can say things like:
- "Starta coachläge"
- "Stäng av coachläge"
- "Nu ska jag börja träna"

Important: in the LLM agent settings, keep "Styr Home Assistant" enabled so it is allowed to call services.

## Next Step: Rep Counting / Fatigue Cues (Vision)

When you're ready, the pattern becomes:
- Frigate provides events and snapshots locally
- A local vision service (in `ai-hub/`) does pose estimation + rep counting
- It publishes:
  - `coach_reps` updates
  - `fatigue` warnings
  via MQTT or Home Assistant REST API
- Home Assistant automation decides what to say/play

The strict privacy policy stays:
- No video leaves the machine.
- Any cloud LLM/TTS gets only text, and only if you explicitly allow it for that request.

