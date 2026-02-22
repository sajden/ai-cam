# Migration: Frigate → Reolink + Home Assistant

## Varför

Reolinks inbyggda AI + auto-tracking fungerar bättre än extern mjukvara:
- Smooth PTZ-tracking (hårdvarunivå, noll latens)
- Person/hund/katt-detektion direkt på kameran
- Fungerar inte samtidigt som Frigate (kameran klarar inte båda)
- Reolink har officiellt Platinum-partnerskap med HA sedan april 2025
- 100% lokalt, fungerar utan internet

## Ny arkitektur

```
Reolink E1 Pro (192.168.50.130)
├── Inbyggd AI: person/hund-detektion, auto-tracking
├── Inspelning: SD-kort (eller framtida NAS)
├── RTSP-ström: rtsp://admin:***@192.168.50.130:554/h264Preview_01_sub
└── HA-integration: PTZ, auto-tracking, AI-sensorer, guard return

Home Assistant (ai-cam-homeassistant)
├── Reolink-integration: kontroll, sensorer, automationer
├── Dashboard: live view, kamerakontroll
├── Automationer: "om person → slå på ljus", etc.
└── REST API: ai-hub styr via HA API

ai-hub (custom features)
├── RTSP direkt från kameran → OpenCV-frames
├── Rep-counter vid träning
├── Ollama vision queries ("vad ser du?", "hur är min form?")
├── Röststyrning (wake word → Codex → TTS → JBL Flip 6)
└── Styr kameran via HA REST API (PTZ, auto-tracking on/off)

camera-voice-bridge → audio-bridge (Windows) → JBL Flip 6
camera-listener → RTSP audio → wake word → STT → ai-hub
```

## Vad vi behåller

- [x] mosquitto (MQTT broker — HA kan använda för automationer)
- [x] ai-hub (röst, vision, rep-counter, Codex)
- [x] camera-voice-bridge + audio-bridge (TTS → JBL Flip 6)
- [x] camera-listener (wake word + STT)
- [x] codex-gateway (LLM-backend)
- [x] Home Assistant

## Vad vi tar bort

- [ ] Frigate (ersätts av kamerans egen AI + HA-integration)
- [ ] go2rtc (Frigate-komponent, behövs ej — ai-hub drar RTSP direkt)
- [ ] frigate_follower.py (Reolinks tracking är bättre)
- [ ] HOG-detektion i follow_tracker.py (kamerans AI tar över)

## Migrationssteg

### Fas 1: Reolink i Home Assistant
1. [x] Stoppa Frigate: `docker compose stop frigate`
2. [x] Lägg till Reolink-integrationen i HA (Settings → Integrations → Add → Reolink)
3. [x] Verifiera att HA ser: live view, PTZ-knappar, auto-tracking switch, AI-sensorer (person, hund)
4. [ ] Testa auto-tracking via HA: slå på switch → gå runt → verifiera smooth tracking

### Fas 2: ai-hub pratar med HA istället för Reolink direkt
5. [x] Skapa HA long-lived access token (Profile → Security → Create Token)
6. [x] ai-hub styr kameran direkt via Reolink HTTP API (fungerar nu utan Frigate)
   - Auto-tracking: `SetAiCfg` direkt till kameran (redan implementerat i reolink_client.py)
   - PTZ: direkt till kameran via HTTP API
   - HA-entiteter tillgängliga som backup/automationer:
     - `switch.living_room_automatisk_sparning` — auto-tracking on/off
     - `switch.living_room_aterga_till_skyddspunkt` — guard return
     - `button.living_room_ptz_vanster/hoger/uppat/nedat/stopp` — PTZ
     - `binary_sensor.living_room_person` — person-detektion
     - `binary_sensor.living_room_djur` — djur-detektion
     - `sensor.living_room_ptz_panoreringsposition` — PTZ position
     - `number.living_room_ai_person_kanslighet` — AI-känslighet
7. [x] Follow-intent använder Reolinks inbyggda auto-tracking (SetAiCfg)
8. [x] Follow-stop stänger av auto-tracking

### Fas 3: Uppdatera RTSP-källa
9. [x] Ändra ai-hub RTSP URL: peka direkt på kameran (sub-stream)
10. [x] Ändra camera-listener RTSP URL: peka direkt på kameran (main-stream)
11. [ ] Verifiera att rep-counter och vision queries fortfarande fungerar

### Fas 4: Rensa
12. [x] Ta bort frigate_follower.py
13. [ ] Förenkla follow_tracker.py (behåll bara som fallback, eller ta bort)
14. [x] Ta bort Frigate MQTT env-variabler från docker-compose.yml
15. [ ] Uppdatera docker-compose.yml: kommentera ut eller ta bort frigate-service
16. [ ] Frigör diskutrymme: `rm -rf data/frigate data/recordings data/clips data/models`

### Fas 5: Extra features (efter migration)
17. [ ] HA-automationer: person detekterad → slå på ljus, notis på telefon
18. [ ] Förbättra rep-counter med Ollama feedback
19. [ ] Dashboard i HA med kamerabild + AI-status
20. [ ] Blockera kameran från internet (router/brandvägg)

## Risker och fallback

| Risk | Mitigation |
|------|-----------|
| HA Reolink-integration saknar feature | Direkt HTTP API mot kameran som backup |
| RTSP direkt → kameran överbelastad | Samma sub-stream som Frigate använde |
| SD-kort-inspelning inte tillräcklig | Kan lägga till NAS/NFS-inspelning senare |
| Kameran tappar WiFi | Ethernet-adapter eller byt till PoE-modell |

## Verifiering efter migration

- [ ] "Hey Jarvis" → svar på JBL Flip 6 (röstloop fungerar)
- [ ] "Följ mig" → kameran följer smooth (Reolink auto-tracking via HA)
- [ ] "Sluta följa" → kameran stannar
- [ ] "Vad ser du?" → Ollama vision query fungerar
- [ ] Rep-counting vid träning fungerar
- [ ] HA dashboard visar live kamerabild
- [ ] Kameran blockerad från internet, allt fungerar ändå
