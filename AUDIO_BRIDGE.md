# Audio Bridge — JBL Flip 6

## Bakgrund

Reolink E1 Pro:s RTSP backchannel (tvåvägsljud via kamerans inbyggda högtalare) är opålitlig — fungerar bara för ~1 ljudklipp per RTSP-session, sedan dör den. Testat med go2rtc persistent stream, backchannel reset, temp streams — inget löser grundproblemet i kamerans firmware.

**Lösning:** Extern Bluetooth-högtalare (JBL Flip 6) kopplad till Windows-datorn. En liten Python-tjänst på Windows tar emot WAV via HTTP och spelar upp det på Flip 6, utan att påverka vanligt Windows-ljud (Teams etc.).

## Arkitektur

```
[ai-hub /v1/speak] → [camera-voice-bridge (Docker)]
                              ↓
                     [Edge TTS → WAV + gain]
                              ↓
                     [POST WAV bytes → http://host.docker.internal:8092]
                              ↓
                     [audio_bridge.py (Windows)]
                              ↓
                     [ffmpeg konvertering → sounddevice → JBL Flip 6 (MME device 4)]
```

## Filer

| Fil | Plats | Beskrivning |
|-----|-------|-------------|
| `audio_bridge.py` | `C:\Github\tools\audio-bridge\` | Windows HTTP-tjänst, port 8092. Tar emot WAV, konverterar via ffmpeg (temp-filer), spelar på Flip 6 |
| `main.py` | `camera-voice-bridge/app/` | Docker-tjänst v0.3.0, port 8091. TTS via Edge TTS, gain, POSTar WAV till audio bridge |

## Status

### Klart
- [x] JBL Flip 6 parad med Windows via Bluetooth
- [x] `audio_bridge.py` fungerar — tar emot WAV via HTTP, spelar på Flip 6
- [x] ffmpeg-konvertering via temp-filer (Windows pipe:0 fungerade inte, "Invalid data found")
- [x] MME backend (device 4) fungerar stabilt (WASAPI device 21 gav PaErrorCode -9999)
- [x] Nåbar från WSL via `172.18.64.1:8092` (curl från WSL → audio bridge fungerar)
- [x] Manuellt test lyckades: WAV från Docker-container → curl (WSL) → audio bridge → Flip 6
- [x] `main.py` uppdaterad (v0.3.0) — go2rtc-logik borttagen, POSTar WAV till `CAMERA_VOICE_AUDIO_BRIDGE_URL`
- [x] Env-variabel: `CAMERA_VOICE_AUDIO_BRIDGE_URL` (default `http://host.docker.internal:8092`)
- [x] Docker → Windows nätverksproblem löst med `extra_hosts: host.docker.internal:host-gateway` i docker-compose
- [x] End-to-end test OK: ai-hub → speak → Edge TTS → audio bridge → Flip 6

### Nästa steg
- [ ] Autostart för `audio_bridge.py` på Windows (Task Scheduler eller startup-script)

## Kända begränsningar
- Kräver att Windows-datorn är igång och `audio_bridge.py` körs
- Flip 6 måste vara påslagen och parad via Bluetooth
- Device-index (4) kan ändras om nya ljudenheter läggs till/tas bort — kör `python -c "import sounddevice as sd; print(sd.query_devices())"` för att hitta rätt
- `audio_bridge.py` måste startas manuellt (inget autostart ännu)

## Säkerhet (endast AI-hub-flöde)

För att undvika att andra processer skickar ljud till högtalaren:

- Sätt samma token i `.env`:
  - `CAMERA_VOICE_AUDIO_BRIDGE_TOKEN=...`
  - `CAMERA_VOICE_BRIDGE_TOKEN=...`
  - `AIHUB_CAMERA_SPEAK_TOKEN=...`
- Starta Windows-tjänsten med:
  - `AUDIO_BRIDGE_TOKEN=...`
  - `AUDIO_BRIDGE_ALLOWED_CALLERS=camera-voice-bridge`

Exempel i PowerShell:

```powershell
$env:AUDIO_BRIDGE_TOKEN="din_hemliga_token"
$env:AUDIO_BRIDGE_ALLOWED_CALLERS="camera-voice-bridge"
python C:\Github\tools\audio-bridge\audio_bridge.py
```

Snabbstart via script (rekommenderat):

```bash
./scripts/start_audio_bridge_windows.sh
```

Det scriptet:
- läser `CAMERA_VOICE_AUDIO_BRIDGE_TOKEN` från projektets `.env`
- sätter `AUDIO_BRIDGE_TOKEN` och `AUDIO_BRIDGE_ALLOWED_CALLERS`
- startar `C:\Github\tools\audio-bridge\audio_bridge.py`

## Lösta problem (logg)

| Problem | Orsak | Lösning |
|---------|-------|---------|
| ffmpeg pipe "Invalid data found" | Windows hanterar binär pipe-data annorlunda | Temp-filer istället för pipe:0/pipe:1 |
| WASAPI PaErrorCode -9999 | WDM-KS driver-konflikt med WASAPI backend | Bytte till MME backend (device 4 istället för 21) |
| soundfile "Format not recognised" | Edge-tts WAV-format okänt för soundfile | ffmpeg-konvertering till 44100Hz stereo WAV |
| sounddevice "Invalid sample rate" | Flip 6 kräver 44100Hz, inte 24000Hz | ffmpeg resampling till 44100Hz |
| Docker container → Windows timeout | Docker bridge-nätverk routar inte till WSL2 gateway IP | `extra_hosts: host.docker.internal:host-gateway` i docker-compose |
