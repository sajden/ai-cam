# Research: Full-Duplex Natural Conversation

**Feature**: `003-fullduplex-conversation`
**Phase**: 0 – Outline & Research
**Date**: 2026-03-04

---

## Finding 1: Echo Guard Bug — Root Cause Confirmed

### Decision
Fix the echo guard by replacing the fixed `ASSISTANT_ECHO_GUARD_SEC` timer with a dynamic calculation based on `speaker_done_at` from the existing `GET /v1/speaker/state` endpoint, plus a short grace period (~0.3 s).

### Rationale
The current bug is a timing mismatch between when the guard is set and when audio actually plays:

| Timeline | Event |
|----------|-------|
| T1 (0 s) | camera-listener receives assistant_text from aihub HTTP response |
| T1 | `assistant_guard_until = now + 5.0` is set (lines 935 and 969 in camera-listener/app/main.py) |
| T2 (~0.3 s) | aihub dispatches TTS request to camera-voice-bridge |
| T3 (~1-3 s) | edge-tts renders audio |
| T4 (~2-5 s) | audio-bridge begins playback on JBL Flip 6 |
| T9 (T4 + duration) | playback ends; `speaker_done_at` written in aihub DB |

The guard expires at T1+5 s. If TTS is short, T9 < T1+5 s — guard fires mid-playback and blocks the user for dead silence. If TTS is long, T9 > T1+5 s — user can speak immediately after playback but hears their own words transcribed with no response because the guard already expired and the text similarity filter kicks in instead.

The `speaker_done_at` ISO timestamp is already computed by camera-voice-bridge (line 276) and stored in aihub. `GET /v1/speaker/state` already returns it (lines 3619–3622 of ai-hub/app/main.py). camera-listener's `AIHubClient.speaker_playing()` (line 652) calls this endpoint but only reads the `speaker_playing` bool, discarding `speaker_done_at`.

### Fix
1. Extend `AIHubClient` to also extract and cache `speaker_done_at` from each `/v1/speaker/state` response.
2. At lines 935 and 969, replace `now_ts + ASSISTANT_ECHO_GUARD_SEC` with `speaker_done_at_unix + ECHO_GRACE_SEC` (default: 0.3 s), with fallback to `now_ts + ASSISTANT_ECHO_GUARD_SEC` if `speaker_done_at` is unknown.
3. Remove the duplicate `CAMERA_LISTENER_ASSISTANT_ECHO_GUARD_SEC` definition in `.env` (line 87 sets 1.5 s, line 95 sets 5 s; the last value wins — this is a latent bug).

### Alternatives Considered
- **Leave guard as-is, reduce to 1 s**: Reduces blocking window but guard still expires at wrong time relative to playback. Rejected.
- **Poll speaker_playing in a background thread**: Extra complexity, still has a race window. Rejected.
- **Text similarity filter only (no time guard)**: SequenceMatcher ratio ≥ 0.84 catches exact echoes but misses partial or paraphrased echoes. Insufficient alone. Rejected as sole mechanism.

---

## Finding 2: Conversation TTL — Already Correct

### Decision
No change required to conversation TTL reset logic. Increase `CAMERA_LISTENER_CONVERSATION_TTL_SEC` from 30 to 120 seconds.

### Rationale
Research confirmed that `state.active_until` is correctly reset to `now_ts + CONVERSATION_TTL_SEC` on every successful turn (line 964 of camera-listener/app/main.py). The problem was only the TTL value: 30 s minus ~11 s for Jarvis's response = ~8 s left for the user to reply. 90 s (spec FR-002) requires setting `CONVERSATION_TTL_SEC=120` (120 s gives a comfortable buffer even for long Jarvis responses).

Additionally, `AIHUB_CONVERSATION_TTL_SEC=300` (currently set) correctly governs the server-side window and is already sufficient.

### Alternatives Considered
- Increase to 300 s: Excessively long; mic stays open when user walks away. 120 s is conservative enough.

---

## Finding 3: AEC Library Options

### Decision
**Phase 1 (this feature)**: Do not add AEC library. The `speaker_done_at` fix eliminates the structural need for hardware AEC in most scenarios. The physical separation between the Reolink camera mic and the JBL Flip 6 provides natural acoustic separation.

**Phase 2 (future)**: If echo self-triggering is observed after Phase 1, add `webrtc-audio-processing` as the preferred AEC solution.

### Rationale
| Option | Viability | Notes |
|--------|-----------|-------|
| `webrtc-audio-processing-python` | **Viable** | Pre-built wheels, ~13 ms latency, can use TTS WAV as reference signal |
| `speexdsp-python` | Viable | Lightweight, needs `libspeexdsp-dev` in Dockerfile, less accurate |
| `pyaudiowpatch` WASAPI loopback | **Not viable** | JBL Flip 6: `max_input_channels=0`, no loopback support over Bluetooth |
| Hardware AEC (new USB mic+speaker) | Not viable | Spec prohibits new hardware purchases |

The text similarity filter (`SequenceMatcher ≥ 0.84`) already provides a secondary echo rejection layer. Combined with `speaker_done_at`-based guard timing, false triggers should be rare.

### Alternatives Considered
- Add AEC in this feature: Adds significant complexity (reference signal synchronisation across Bluetooth + RTSP delays of 100–400 ms). Risk outweighs benefit at this stage. Deferred.

---

## Finding 4: Barge-In During Playback (FR-004)

### Decision
Re-use the existing barge-in mechanism (`CAMERA_LISTENER_BARGE_IN_ENABLED=1`). The barge-in path at `camera-listener` already calls `POST /v1/speaker/interrupt` which clears `speaker_done_at` in aihub. No new code required for interrupt support.

### Rationale
The spec requires that the user can interrupt mid-speech using the interrupt phrase. This is already implemented via `CAMERA_LISTENER_BARGE_IN_INTERRUPT_SPEAKER=1` and `CAMERA_LISTENER_INTERRUPT_PHRASES`. Confirming it works end-to-end is a test task, not an implementation task.

---

## Summary of Changes Required

| Component | File | Change |
|-----------|------|--------|
| camera-listener | `app/main.py` | `AIHubClient.speaker_playing()` → also cache `speaker_done_at` as Unix timestamp |
| camera-listener | `app/main.py` | Lines 935, 969: replace `now_ts + ASSISTANT_ECHO_GUARD_SEC` with `_guard_until_from_speaker_done()` helper |
| camera-listener | `app/main.py` | Add `_guard_until_from_speaker_done(now_ts)` function |
| `.env` | `.env` | Remove duplicate `CAMERA_LISTENER_ASSISTANT_ECHO_GUARD_SEC` (line 87); keep line 95 at 5 s as fallback |
| `.env` | `.env` | `CAMERA_LISTENER_CONVERSATION_TTL_SEC` → 120 |
| `.env.example` | `.env.example` | Document new `CAMERA_LISTENER_ECHO_GRACE_SEC` var (default: 0.3) |
| `aihub` | none | No changes — `speaker_done_at` already in `/v1/speaker/state` response |
