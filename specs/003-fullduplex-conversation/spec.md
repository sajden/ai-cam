# Feature Specification: Full-Duplex Natural Conversation

**Feature Branch**: `003-fullduplex-conversation`
**Created**: 2026-03-04
**Status**: Draft
**Input**: User description: "Full-duplex natural conversation — eliminate echo guard blocking so the user can speak immediately after (or during) Jarvis TTS playback without artificial delays."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Immediate Response After Jarvis Speaks (Priority: P1)

The user says "hey jarvis" and asks a question. Jarvis responds with a spoken answer. The user wants to reply immediately when Jarvis finishes — without waiting. Today there is an invisible 5-second window where the microphone is blocked after every Jarvis response, making the conversation feel like talking to an answering machine rather than a person.

**Why this priority**: This is the core problem. Every single conversation interaction is affected. Removing this friction makes the assistant feel fundamentally more natural.

**Independent Test**: Say "hey jarvis, vad heter du?" — wait for the answer — immediately say "berätta mer" — verify the follow-up is heard and answered without needing to wait or repeat the wake word.

**Acceptance Scenarios**:

1. **Given** Jarvis has just finished speaking, **When** the user speaks within 1 second, **Then** the system hears and responds to what was said
2. **Given** Jarvis is mid-sentence, **When** the user says the interrupt phrase, **Then** Jarvis stops and listens
3. **Given** a multi-turn conversation is in progress, **When** the user pauses to think for up to 2 minutes, **Then** the conversation window remains open without needing to say "hey jarvis" again

---

### User Story 2 - Conversation Stays Open Between Turns (Priority: P2)

After the first wake word, the user should be able to have a back-and-forth conversation without saying "hey jarvis" again for each turn. Today the conversation window closes after 30 seconds from the initial wake word — but Jarvis's own response takes 7–11 seconds, leaving little time for the user to actually reply.

**Why this priority**: Without this, even a 2-turn conversation requires saying the wake word twice. Makes the assistant feel like a search engine, not a companion.

**Independent Test**: After one "hey jarvis" trigger, have a 5-turn back-and-forth conversation without saying the wake word again — verify all turns are heard and answered.

**Acceptance Scenarios**:

1. **Given** a conversation is active, **When** the user takes up to 90 seconds to respond after Jarvis speaks, **Then** the system still hears the response without requiring a new wake word
2. **Given** 90+ seconds of silence after the last exchange, **When** the user speaks without saying "hey jarvis", **Then** the system does not respond (conversation correctly closed)

---

### User Story 3 - No False Echo Triggers (Priority: P3)

When the echo suppression is relaxed, the system must not accidentally transcribe Jarvis's own voice as a user command. If the speaker and microphone are in the same room, some echo will reach the microphone — the system must distinguish between Jarvis's voice and the user's voice.

**Why this priority**: Without this, removing the echo guard causes Jarvis to respond to himself, creating infinite loops. Quality gate for the other stories.

**Independent Test**: Let Jarvis speak a full sentence while standing silent — verify no follow-up conversation turn is triggered by the echo.

**Acceptance Scenarios**:

1. **Given** Jarvis is speaking, **When** no human speaks, **Then** no conversation turn is triggered from the echo
2. **Given** the user speaks at the same time as Jarvis, **When** the user says something clearly different from what Jarvis is saying, **Then** the user's words are heard and responded to

---

### Edge Cases

- What happens if Jarvis gives a very long response (30+ seconds) — does the conversation window stay open long enough for the user to reply after?
- How does the system handle the user speaking very quietly?
- What if there is loud background noise — does that trigger false response events?
- What if the speaker and microphone are in very close proximity — does the echo overwhelm the mic?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow the user to speak immediately (within 0.5 seconds) after Jarvis finishes a spoken response without any blocking period
- **FR-002**: The system MUST keep the conversation window open for at least 90 seconds after the last exchange, with the timer resetting after each turn
- **FR-003**: The system MUST NOT trigger a conversation turn from Jarvis's own voice echoing through the room when no human speaks
- **FR-004**: The system MUST allow the user to interrupt Jarvis mid-speech using the designated interrupt phrase
- **FR-005**: The system MUST remain continuously operational without manual restarts
- **FR-006**: The system MUST support Swedish-language speech in all scenarios
- **FR-007**: The conversation window timer MUST reset after each exchange (both user and Jarvis turns), not only from the initial wake word

### Key Entities

- **Echo suppression window**: The period during which the microphone is partially or fully blocked after Jarvis speaks — should be at most 0.5 seconds as a brief grace period
- **Conversation window**: The active listening period after a wake word — must be long enough for natural back-and-forth and reset on each turn

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The user can reply to Jarvis within 1 second of Jarvis finishing speaking and be heard correctly in 95% of attempts
- **SC-002**: A 5-turn back-and-forth conversation completes without the user saying "hey jarvis" more than once
- **SC-003**: Zero false conversation turns triggered by Jarvis's own voice in 10 consecutive tests
- **SC-004**: The conversation window stays open for at least 90 seconds of user inactivity after the last exchange
- **SC-005**: The interaction feels natural — the user does not need to time or pace their speech around system limitations

## Assumptions

- The Reolink camera microphone is the primary audio input source
- The JBL Flip 6 is the primary audio output (Bluetooth, Windows host)
- Physical distance between camera mic and JBL speaker provides some natural acoustic separation
- The solution must not require purchasing new hardware
- Swedish is the primary interaction language; wake words are "hey jarvis" / "hej jarvis"
- The solution must work within the existing Docker + Windows audio-bridge setup
