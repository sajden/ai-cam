# Audio Bridge Setup

Brygga mellan Docker/WSL och Windows-ljudkortet (JBL Flip 6).

## Arkitektur

```
camera-voice-bridge (Docker)
  → POST WAV till http://host.docker.internal:8092
    → audio_bridge.py (Windows, Python)
      → sounddevice → JBL Flip 6
```

## Filer

| Fil | Plats |
|-----|-------|
| Huvudskript | `C:\Github\tools\audio-bridge\audio_bridge.py` |
| Launcher (autogenererad) | `C:\Github\tools\audio-bridge\launch_audio_bridge.ps1` |
| Registreringsskript | `C:\Github\ai-cam\scripts\register_audio_bridge_task.ps1` |

## Krav

- Python (Windows) med `sounddevice`, `soundfile`, `numpy`
- ffmpeg i PATH
- JBL Flip 6 ihopkopplad via Bluetooth

## Hur det startar

Task Scheduler-task `ai-cam audio-bridge` kör `launch_audio_bridge.ps1` vid varje inloggning.

Launchern sätter env-vars och kör `audio_bridge.py`:
```powershell
$env:AUDIO_BRIDGE_TOKEN = "<token>"
$env:AUDIO_BRIDGE_ALLOWED_CALLERS = "camera-voice-bridge"
$env:AUDIO_BRIDGE_DEVICE_NAME = "JBL"
& "py" -3 "C:\Github\tools\audio-bridge\audio_bridge.py"
```

`audio_bridge.py` söker upp JBL-enheten vid namn (inte hårdkodat index) — fungerar även efter BT-reconnect.

Inbyggd keepalive spelar tyst ljud var 4:e minut så högtalaren inte sover.

## Verifiera att den körs

```powershell
curl http://localhost:8092/health -UseBasicParsing
# Förväntat: {"ok":true,"device_name":"Högtalare (JBL Flip 6)",...}

Get-Process python*
```

## Om något går fel

### Starta om manuellt
```powershell
Stop-ScheduledTask -TaskName 'ai-cam audio-bridge'
Start-ScheduledTask -TaskName 'ai-cam audio-bridge'
```

### Kör synkront för att se fel
```powershell
& "C:\Github\tools\audio-bridge\launch_audio_bridge.ps1"
```

### Registrera om från scratch (t.ex. efter token-byte)
```powershell
Unregister-ScheduledTask -TaskName 'ai-cam audio-bridge' -Confirm:$false
cd C:\Github\ai-cam\scripts
.\register_audio_bridge_task.ps1
```

Skriptet läser token automatiskt från WSL-repots `.env` och skriver ny launcher.

### JBL hittades inte
`audio_bridge.py` loggar alla tillgängliga output-enheter om `AUDIO_BRIDGE_DEVICE_NAME` inte matchar något. Ändra `AUDIO_BRIDGE_DEVICE_NAME` i launchern till ett delsträngsmatch mot enhetens namn.

### Task startar men ingen Python-process
Kör launchern direkt (se ovan) för att se felmeddelande. Vanliga orsaker:
- ffmpeg saknas i PATH
- Python-paket saknas (`pip install sounddevice soundfile numpy`)
- JBL inte ansluten vid start (bridgen startar ändå, hittar enheten när den ansluts)

## Tidslinje för automations-fix (HA)

Morgon-automationerna triggade inte sedan 6 mars pga `after: "06:00:00"` är strikt `>` i HA — misslyckas vid exakt 06:00:00.

Fixat via `docker exec ai-cam-homeassistant`:
- Lampa: `after: 06:00:00` → `after: 05:59:00`
- Spotify: `after: 05:55:00` → `after: 05:54:00`

Automations reloadades via HA API.
