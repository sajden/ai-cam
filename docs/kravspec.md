# Kravspec (AI-cam)

Datum: 2026-02-11

## Mål
Bygga en lokal AI-kompis för hemmet med Reolink-kamera, där video/audio stannar lokalt och systemet kan prata naturligt med användaren.

## Måste-krav
- Kamera: Reolink E1 Pro är installerad och används som primär källa för video + ljud in.
- Tvåvägsljud: systemet ska kunna ta in ljud från kameran och skicka tal tillbaka till kameran.
- Integritet:
  - rå video får aldrig skickas till moln
  - rå audio får aldrig skickas till moln
  - moln får endast text, och endast vid explicit trigger (t.ex. "Hey Codex")
- Aktivitetspolicy:
  - kontinuerlig tung analys får bara köras vid event eller explicit startkommando (uppdragssession)
- Nätverk:
  - inga publika portar
  - ingen port forwarding
  - mobil åtkomst endast via Tailscale
- Lagring:
  - all runtime-data under `./data/`
  - konversationsminne sparas lokalt i SQLite

## Bör-krav
- Lokal standardväg för AI-svar (moln endast som explicit läge).
- Eventnotiser vid hund/person-rörelse.
- Uppdragssession via röstkommando:
  - "Starta uppdrag"
  - "Avsluta uppdrag"
  - Exempeltyp: coachning vid träning

## Kan-krav
- Moln-LLM för bättre allmän frågesvarskvalitet när användaren säger "Hey Codex".
- Moln-TTS för bättre röstkvalitet (text-only), om användaren godkänner.

## Acceptanskriterier
- AC-1: Frigate visar live-feed och sparar eventklipp lokalt.
- AC-2: Hundrörelse triggar event och notis.
- AC-3: Systemet kan ta tal från kamerans ljudin och svara i kamerans högtalare.
- AC-4: "Hey Codex" routar endast text till moln, aldrig media.
- AC-5: När uppdragssession är av körs ingen kontinuerlig uppdragsanalys.
- AC-6: Konversationer sparas lokalt och kan återanvändas i senare svar.

## Öppna verifieringar (med ny kamera på plats)
- Verifiera RTSP video + audio in från Reolink i Frigate.
- Verifiera talkback/audio out till Reolink-högtalaren (ONVIF/Reolink-kanal).
- Verifiera end-to-end: användare pratar -> STT -> AI-svar -> TTS -> kamerahögtalare.
