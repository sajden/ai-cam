# Feature Specification: AI Companion — Identity, Memory & Embodiment

**Feature Branch**: `002-face-recognition`
**Created**: 2026-03-03
**Status**: Draft

## Overview

An always-present AI companion that knows who is home, remembers what they tell it over time, and expresses itself physically through the camera's movements. The companion initiates conversations, follows up on past events, and feels genuinely personal — not a tool you query, but a presence that lives with you.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Välkommen hem (Priority: P1)

Sebastian kommer hem efter jobbet. Kameran detekterar en person, känner igen Sebastian, och hälsar: *"Välkommen hem Sebastian! Hur var din dag?"* Kameran vänder sig mot dörren och nickar. En konversation startar — Sebastian kan svara direkt. Om Sebastian redan var hemma och bara rörde sig förbi kameran händer ingenting.

**Why this priority**: Det är det mest konkreta och omedelbara värdet. Hemmet känns levande direkt.

**Independent Test**: Gå ut och kom hem igen efter 2+ timmar. Kameran ska hälsa med namn och starta ett samtal. Gå förbi kameran en timme senare — ingen ny hälsning.

**Acceptance Scenarios**:

1. **Given** Sebastian är enrollad och kommer hem (ej sedd på 2+ timmar), **When** kameran detekterar person och känner igen ansiktet, **Then** TTS-hälsning spelas upp med namn + kameran vänder sig mot personen inom 5 sekunder.
2. **Given** Sebastian var hemma sedan 30 minuter, **When** han går förbi kameran igen, **Then** ingen hälsning — kontext uppdateras tyst.
3. **Given** privacy mode är aktivt, **When** en person syns på kameran, **Then** ingenting händer.
4. **Given** en okänd person syns och det gått 24+ timmar sedan senaste okänd-person-händelse, **When** igenkänning misslyckas, **Then** kameran säger *"Hej, jag känner inte igen dig — vem är du?"*

---

### User Story 2 — Kameran har ett kroppsspråk (Priority: P2)

Sebastian frågar: *"Jarvis, är klockan 10?"* — AI:n svarar *"Nej, klockan är faktiskt 9"* och kameran skakar lätt på huvudet. När Sebastian tackar nickar kameran. När AI:n processar en fråga tittar kameran lite nedåt. Rörelserna är subtila och naturliga — inte robotlika ryckiga rörelser.

**Why this priority**: Kroppsspråket ger AI:n en fysisk personlighet. Det är det som skiljer detta från alla andra röstassistenter.

**Independent Test**: Ställ en ja/nej-fråga. Kameran ska röra sig i linje med svaret. Ställ en komplex fråga — kameran ska titta nedåt under processing.

**Acceptance Scenarios**:

1. **Given** AI:n svarar med "ja" eller bekräftelse, **When** TTS startar, **Then** kameran nickar (tilt upp-ner, 1-2 gånger).
2. **Given** AI:n svarar med "nej" eller korrigerar, **When** TTS startar, **Then** kameran skakar (pan vänster-höger, 1-2 gånger).
3. **Given** en förfrågan processas (STT → Codex), **When** systemet väntar på svar, **Then** kameran tittar lätt nedåt.
4. **Given** wake word detekteras, **When** mikrofonen aktiveras, **Then** kameran vänder sig mot personen.
5. **Given** konversation avslutas, **When** ingen aktivitet på 30 sekunder, **Then** kameran återgår till standardposition.

---

### User Story 3 — AI:n minns vad du berättar (Priority: P3)

Sebastian berättar under ett kvällssamtal att han sov dåligt och har ett viktigt möte på fredag. Nästa morgon när han kommer förbi kameran frågar AI:n: *"Sov du bättre ikväll? Och lycka till med mötet idag!"* Minnet är personligt och byggs upp över tid.

**Why this priority**: Utan minne är varje konversation isolerad. Minnet är det som skapar relationen.

**Independent Test**: Berätta något specifikt (t.ex. "jag är trött, tränade för hårt igår"). Nästa dag — bekräfta att AI:n refererar till det utan att bli påmind.

**Acceptance Scenarios**:

1. **Given** Sebastian nämner ett faktum om sig själv (humör, event, mående), **When** konversationen avslutas, **Then** faktumet är extraherat och sparat kopplat till Sebastian och tidpunkt.
2. **Given** ett sparat faktum är relevant (t.ex. möte på fredag → det är fredag), **When** Sebastian interagerar med AI:n, **Then** AI:n refererar naturligt till det utan att bli tillfrågad.
3. **Given** ett faktum är inaktuellt (t.ex. mötet har passerat), **When** faktumet tas upp igen, **Then** AI:n behandlar det som historik, inte aktuell händelse.
4. **Given** Sebastian korrigerar något AI:n minns fel, **When** korrektionen görs, **Then** minnet uppdateras.

---

### User Story 4 — Proaktiv kompis (Priority: P4)

AI:n initierar konversation utan att Sebastian behöver säga wake word. På morgonen: *"God morgon Sebastian! Dagens ord är 'resilient' — det betyder motståndskraftig."* På kvällen: *"Hur gick det med mötet idag?"* Det känns som en kompis som tänker på en.

**Why this priority**: Proaktivitet är det som gör AI:n till en kompis snarare än ett verktyg. Utan det är det fortfarande bara en fancier Siri.

**Independent Test**: Konfigurera ett morgonhälsning-event. Bekräfta att AI:n initierar vid rätt tid utan att wake word sagts.

**Acceptance Scenarios**:

1. **Given** det är morgon och Sebastian identifierats som hemma, **When** konfigurerbar morgontid inträffar, **Then** AI:n initierar med hälsning + ett proaktivt element (ord, fråga, reflektion).
2. **Given** ett sparat faktum har ett tidsbundet uppföljningsdatum, **When** datumet inträffar och Sebastian är hemma, **Then** AI:n frågar om uppföljningen naturligt i konversationen.
3. **Given** AI:n initierar ett samtal, **When** Sebastian inte svarar inom 15 sekunder, **Then** AI:n avslutar tyst — ingen loop.
4. **Given** privacy mode är aktivt, **When** en proaktiv trigger inträffar, **Then** ingenting händer.

---

### User Story 5 — Enrollment: lär AI:n vem du är (Priority: P5)

Susanne (Sebastians mamma) hälsar på. Sebastian säger *"Det här är min mamma Susanne"* medan Susanne syns på kameran. AI:n svarar *"Hej Susanne, trevligt att träffas!"* och sparar hennes ansikte. Nästa gång Susanne besöker känner kameran igen henne.

**Why this priority**: Systemet kan inte ha värde utan att veta vem som är vem. Men grundenrollment av Sebastian kan göras via API, så detta blockerar inte P1-P4.

**Independent Test**: Enrolla en ny person via röstkommando. Låt personen lämna och komma tillbaka — bekräfta att de hälsas med rätt namn.

**Acceptance Scenarios**:

1. **Given** en person syns på kameran och kommandot *"Det här är [namn]"* sägs, **When** systemet processar kommandot, **Then** ansiktet sparas under det namnet och AI:n bekräftar på svenska.
2. **Given** initial enrollment av primäranvändare, **When** ett foto laddas upp via API, **Then** personen kan identifieras nästa gång de syns på kameran.
3. **Given** samma namn enrollas igen, **When** kommandot körs, **Then** befintlig data uppdateras, inte dupliceras.
4. **Given** inget ansikte syns tydligt vid enrollment, **When** kommandot körs, **Then** AI:n ber personen att komma in i bild.

---

### Edge Cases

- Två personer syns samtidigt: systemet identifierar det mest framträdande ansiktet (störst/mest centrerat), hälsar bara en åt gången.
- Reolink offline: röstinteraktion fortsätter, face recognition och kamerarörelser inaktiveras tyst.
- Okänd person inuti hemmet (ej vid dörren): samma flöde som okänd vid dörr, men ingen "välkommen hem"-fras.
- PTZ-rörelse misslyckas: TTS spelas upp som vanligt, ingen felmeddelande.
- Minnet är felaktigt: Sebastian kan korrigera verbalt, systemet uppdaterar.
- Kameran är i privacy mode: absolut noll face recognition, TTS, PTZ-rörelser eller proaktiva triggers.

## Requirements *(mandatory)*

### Functional Requirements

**Identity**
- **FR-001**: Systemet MÅSTE köra face recognition lokalt — ingen bild eller video lämnar hemmanätverket.
- **FR-002**: Face recognition MÅSTE triggas inom 5 sekunder efter att HA Reolink-integrationen detekterar en person.
- **FR-003**: Systemet MÅSTE använda ML-baserad face recognition kapabel att skilja på enrollade personer under normala inomhusljusförhållanden.
- **FR-004**: Systemet MÅSTE stödja enrollment via röstkommando (*"Det här är [namn]"*) och via API med foto.
- **FR-005**: Re-enrollment med samma namn MÅSTE uppdatera, inte duplicera, befintlig data.

**Arrival & Presence**
- **FR-006**: Systemet MÅSTE spåra per-person närvaro med en konfigurerbar cooldown (standard: 2 timmar) för att avgöra om en detekterad person "kommit hem" eller redan är hemma.
- **FR-007**: Vid ankomst MÅSTE systemet starta ett välkomstsamtal med personens namn.
- **FR-008**: Om person redan är hemma MÅSTE systemet uppdatera aktiv identitetskontext tyst utan hälsning.
- **FR-009**: Okänd person MÅSTE hanteras med en fråga (*"vem är du?"*) max en gång per 24-timmarsperiod.

**Embodiment**
- **FR-010**: Kameran MÅSTE nicka (tilt) vid jakande svar och skaka (pan) vid nekande svar, synkroniserat med TTS.
- **FR-011**: Kameran MÅSTE vända sig mot en identifierad person vid wake word.
- **FR-012**: Kameran MÅSTE inta en "tänkande" position (lätt nedåt) under Codex-processing.
- **FR-013**: Kameran MÅSTE återgå till standardposition efter avslutad konversation.

**Memory**
- **FR-014**: Systemet MÅSTE extrahera och spara minnesfakta från konversationer (namn, events, humör, planer) kopplade till identifierad person och tidpunkt.
- **FR-015**: Relevanta minnen MÅSTE injiceras i systemkontexten vid varje konversationstur.
- **FR-016**: Systemet MÅSTE kunna flagga minnen med uppföljningsdatum för proaktiv återkoppling.

**Proactivity**
- **FR-017**: Systemet MÅSTE kunna initiera konversation utan wake word vid konfigurerbara triggers (tid på dagen, identifierad ankomst, uppföljningsdatum).
- **FR-018**: Proaktiva initiativ MÅSTE avbrytas tyst om ingen svarar inom 15 sekunder.
- **FR-019**: Proaktiva initiativ MÅSTE inkludera minst ett av: uppföljning på minne, ord på dagen, reflektion, eller personlig fråga.

**Infrastructure**
- **FR-020**: Frigate MÅSTE kunna avvecklas — all detektion sköts av HA Reolink-integration.
- **FR-021**: Videoinspelning MÅSTE ske lokalt via HA + go2rtc från main-streamen (max kvalitet).
- **FR-022**: Systemet MÅSTE vara inaktivt i alla dimensioner när privacy mode är aktivt.

### Key Entities

- **Person Profile**: Enrollad person med namn, relationsroll (valfri, t.ex. "mamma"), ansiktsdata, aktivitetspreferenser, och senast-sedd-tidpunkt.
- **Memory Fact**: Ett extraherat faktum från en konversation. Har koppling till person, tidpunkt, kategori (event/humör/plan/preferens), och valfritt uppföljningsdatum.
- **Presence State**: Per-person spårning av om personen är hemma, när de senast sågs, och om cooldown för hälsning är aktiv.
- **PTZ Gesture**: En namngiven kamerarörelse (nod, skaka, vänd, tänk, standard) med konfigurerbara vinklar och hastigheter.
- **Proactive Trigger**: En schemalagd eller event-baserad trigger som initierar ett samtal utan wake word.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Känd person hälsas med namn inom 5 sekunder efter ankomst i minst 80% av försök under normalt inomhusljus.
- **SC-002**: Noll felidentifieringar mellan enrollade personer i back-to-back-tester under standardförhållanden.
- **SC-003**: Enrollment av ny person via röstkommando tar under 60 sekunder från kommando till första lyckade igenkänning.
- **SC-004**: Kamerarörelser är synkroniserade med TTS-svar i 100% av ja/nej-svar.
- **SC-005**: AI:n refererar till minst ett sparat minnesfaktum utan att bli påmind inom 24 timmar efter att faktumet sparades, vid nästa relevanta interaktion.
- **SC-006**: Proaktiva initiativ triggas vid konfigurerad tid i 100% av fall när personen är hemma och privacy mode är inaktivt.
- **SC-007**: Noll face recognition-händelser, TTS, eller PTZ-rörelser när privacy mode är aktivt.
- **SC-008**: Videoinspelning sparas lokalt med full main-stream-kvalitet utan Frigate.

## Assumptions

- Reolink E1 Pro används som primär kamera — PTZ (pan/tilt) är tillgängligt.
- RTX 4070 med CUDA används för lokal ML face recognition — ingen cloud-bearbetning av video eller bilder.
- Ljud når användaren via Bluetooth-högtalare kopplad till Windows-värd via audio bridge.
- HA Reolink-integrationen kan leverera person-detektions-events med tillräcklig tillförlitlighet för ankomstflödet.
- Codex (OpenAI) används för konversation — enbart text skickas, ingen video eller bild.
- Minnen extraheras av Codex/LLM från konversationstext — ingen separat NLP-pipeline behövs.
- En enrollad person åt gången är aktiv kontext (multi-person-konversation är out of scope).
- Proaktiva initiativ kräver att personen är hemma (identifierad inom cooldown-fönstret).

## Out of Scope

- Multi-person simultana konversationer.
- Igenkänning på fler än en kamera.
- Emotion- eller åldersdetektering.
- Röstidentifiering (identitet via röst, ej ansikte).
- Liveness detection (spoofing-skydd).
- Mobilapp eller webb-UI för minneshantering.
- Integration med externa kalenders eller tjänster (Google Calendar etc.).
- Flerspråkigt stöd — svenska är enda språket.
