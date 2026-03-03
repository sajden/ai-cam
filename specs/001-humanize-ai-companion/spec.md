# Feature Specification: Humanize AI Companion Personality

**Feature Branch**: `001-humanize-ai-companion`
**Created**: 2026-02-25
**Status**: Draft
**Input**: User description: "go through the repo try to understand how to make it better and more smooth, so its more of a AI friend less of a robot."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Natural, Varied Greetings (Priority: P1)

When the user triggers the wake word, the assistant responds with a greeting that feels natural and personal rather than always identical. The greeting varies based on time of day and how recently the last interaction occurred. After several days of use, the assistant no longer sounds like it is meeting the user for the first time every session.

**Why this priority**: The wake response is the first thing a user hears in every interaction. A static, identical greeting every time is the most immediately noticeable signal that this is software, not a companion. Fixing this has outsized impact on overall feel with minimal technical risk.

**Independent Test**: Can be fully tested by triggering the wake word 10 times across different times of day and verifying that the greeting varies meaningfully and is not word-for-word identical across consecutive triggers.

**Acceptance Scenarios**:

1. **Given** the user triggers the wake word in the morning for the first time that day, **When** the assistant responds, **Then** the greeting acknowledges the time of day and is not identical to the previous session's greeting.
2. **Given** the user already had a conversation within the last 10 minutes, **When** they trigger the wake word again, **Then** the assistant responds with a short continuity phrase (e.g., "Ja?" or "Vad mer?") rather than a full formal greeting.
3. **Given** the user just completed a workout session and triggers the wake word immediately after, **When** the assistant responds, **Then** the greeting may acknowledge the recent activity.

---

### User Story 2 - Warm, Varied Task Confirmations (Priority: P2)

When the user gives a command (move camera, play music, start workout), the assistant confirms the action with language that feels natural and varied rather than reciting the same fixed phrase every time. Over time, the user cannot predict word-for-word what the assistant will say before it says it.

**Why this priority**: Hardcoded confirmation strings make every interaction feel scripted. Varied confirmations create an impression of a present, responsive companion rather than a state machine.

**Independent Test**: Can be fully tested by issuing the same command (e.g., "titta vänster") five times and verifying that at least three distinct confirmation phrasings are used.

**Acceptance Scenarios**:

1. **Given** the user says "titta vänster" (camera pan left), **When** the assistant acknowledges, **Then** the confirmation is drawn from a pool of contextually appropriate phrases, not a single fixed string.
2. **Given** the user says "pausa musik" (pause music), **When** the assistant confirms, **Then** the response sounds conversational and varies between attempts.
3. **Given** the assistant fails to complete an action (e.g., camera timeout), **When** it reports the failure, **Then** the language is empathetic and human-sounding rather than a flat error statement.

---

### User Story 3 - Conversational Follow-Through (Priority: P2)

After completing a task, the assistant occasionally offers a brief natural follow-up rather than going silent immediately. After a workout session ends, it might say something encouraging. After starting a song, it might mention the artist. These follow-ups are brief, do not require a response, and feel like something a friend might say.

**Why this priority**: A purely reactive assistant that only speaks when spoken to feels like a tool. A companion occasionally shows initiative in low-stakes, contextually appropriate ways, deepening the sense of a two-way relationship.

**Independent Test**: Can be fully tested by completing a training session and verifying that the assistant offers a brief, contextually relevant closing remark at least 50% of the time without requiring any user prompt.

**Acceptance Scenarios**:

1. **Given** the user ends a workout session, **When** the assistant confirms the session ended, **Then** it optionally adds a brief friendly remark (e.g., "Bra jobbat!" or "Hoppas det kändes bra.").
2. **Given** the assistant successfully starts playing music the user requested, **When** confirming playback, **Then** it may briefly note the track or artist in a conversational way.
3. **Given** the assistant has been idle for more than 2 hours since the last interaction during a period the user is typically active, **When** it next speaks, **Then** it acknowledges the time gap naturally.

---

### User Story 4 - Richer Conversational Persona (Priority: P3)

The assistant's personality instructions are expanded so that it produces responses that are warmer, more curious, and more willing to engage in brief small talk — not just task execution. The assistant responds naturally to social questions and can ask a clarifying question rather than silently guessing.

**Why this priority**: Even with varied confirmations and greetings, the substance of conversational responses can still feel clinical. Enriching the persona unlocks better natural conversation without requiring new interaction paths — it is a better briefing for the underlying intelligence.

**Independent Test**: Can be fully tested by sending open-ended conversational inputs (e.g., "Vad tycker du om musik?", "Hur mår du?") and verifying the assistant engages naturally rather than deflecting or producing a task-oriented non-answer.

**Acceptance Scenarios**:

1. **Given** the user asks "Hur mår du?" (How are you?), **When** the assistant responds, **Then** it gives a brief, warm, natural-sounding response rather than a disclaimer about being an AI.
2. **Given** the user says something ambiguous (e.g., "Spela något bra"), **When** the assistant needs to interpret, **Then** it may acknowledge the ambiguity conversationally rather than silently picking one interpretation.
3. **Given** the user completes a task-related exchange, **When** the assistant has responded, **Then** it may briefly invite further conversation without demanding a response.

---

### Edge Cases

- What happens when the pool of varied responses is exhausted (all variants recently used)? Responses should cycle without obvious repetition, prioritizing least-recently-used variants.
- How does the system handle multilingual input (mixing Swedish and English)? Respond in Swedish by default; match the user's language if they switch entirely.
- What if the user explicitly prefers the old, direct style? Saying "svara kort" activates minimal/direct mode permanently for that identity (no follow-ups, shortest confirmation variants). Saying "svara normalt" reverts to companion mode. The assistant MUST confirm the mode change verbally on both activation and deactivation.
- What happens if the assistant's follow-up remark conflicts with a new user command? The follow-up is delivered as a separate TTS utterance after a ~1–2 second pause; if the user speaks during that pause window, the follow-up is suppressed and the new input takes priority.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The wake acknowledgement MUST draw from a pool of at least 5 contextually varied phrases, differentiated by time of day, recency of prior interaction, and the recognized identity of the current user. Each registered identity maintains its own interaction history for personalization purposes.
- **FR-002**: When the user triggers the wake word within 10 minutes of a previous interaction, the assistant MUST respond with a short continuity phrase rather than a full formal greeting.
- **FR-003**: Each hardcoded task-confirmation string MUST be replaced with a pool of at least 3 contextually appropriate variant phrases.
- **FR-004**: Failure and error responses MUST use empathetic, human-sounding language rather than neutral status messages.
- **FR-005**: The assistant MUST offer a brief, contextually relevant follow-up remark after completing a workout session at least 30% of the time. The remark MUST be delivered as a separate TTS utterance approximately 1–2 seconds after the task confirmation ends. If the user speaks during that pause window, the follow-up MUST be suppressed and the user's new input MUST take priority.
- **FR-006**: The system persona instructions for the conversational path MUST be expanded to include explicit guidance on warmth, curiosity, willingness to engage in brief small talk, and handling of ambiguous input conversationally.
- **FR-007**: The assistant MUST respond naturally to direct social questions (e.g., "hur mår du?") rather than deflecting with a disclaimer about being software.
- **FR-008**: All personality changes MUST preserve existing functional behavior — camera control, Spotify, training, and vision queries must continue to work identically with zero regression.
- **FR-009**: Users MUST be able to activate minimal/direct response mode verbally (e.g., "svara kort"), which suppresses follow-ups and uses the shortest confirmation variants. This preference MUST persist permanently across sessions for that identity until the user explicitly disables it (e.g., "svara normalt").

### Key Entities

- **Response Pool**: A named collection of phrase variants for a given interaction type (wake greeting, task confirmation, error message, follow-up remark), with metadata indicating contextual eligibility (time of day, recency of last interaction, preceding action type).
- **Interaction Context**: A transient record of the current session — what actions were taken, how long the session has lasted, what the last interaction type was, and which registered identity is active — used to select contextually appropriate responses.
- **Persona Profile**: The set of personality instructions used for conversational responses, defining tone, warmth level, willingness to engage socially, and approach to ambiguity.
- **Preference State**: A persistent per-identity flag (companion mode or minimal/direct mode) that survives across sessions. Activated verbally ("svara kort") and reverted verbally ("svara normalt"). Each registered identity has an independent, durable preference with no automatic expiry.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a test of 10 consecutive wake triggers, no single greeting phrase repeats more than twice.
- **SC-002**: The same verbal command issued 5 times produces at least 3 distinct confirmation phrasings.
- **SC-003**: After a workout session ends, a contextually relevant follow-up remark is produced in at least 3 out of 10 sessions.
- **SC-004**: Open-ended social questions receive a natural, contextually appropriate response 100% of the time with no deflection or error output.
- **SC-005**: All existing functional task behaviors (camera control, Spotify, training, vision) succeed at the same rate before and after personality changes are applied — zero regression.
- **SC-006**: After one week of daily use, the primary user rates the assistant's companion quality at ≥4 out of 5 on a structured self-rating (1 = completely robotic, 5 = feels like a real companion).

## Assumptions

- The primary language of the assistant is Swedish (sv-SE) and all response pools will be authored in Swedish.
- "Less robotic" means: more linguistic variety, more contextual awareness, and warmer tone — not persistent emotional modeling, long-term memory, or simulated feelings beyond brief, friendly acknowledgements.
- Scope covers voice interaction responses only (wake, confirmation, error, follow-up, persona) — not workout display overlays, camera stream UI, or Home Assistant dashboard elements.
- Varied response pools are pre-authored by the developer; the system selects from them at runtime based on available context signals.
- Each registered identity maintains its own interaction history. Personalized greetings, follow-ups, and minimal/direct mode preference are per-identity, not shared across the household.
- The conversational persona expansion is backward-compatible and does not alter existing camera, Spotify, or training tool-tag behavior.

## Dependencies

- Wake-word detection, STT, TTS, and routing pipelines remain unchanged.
- Response pool selection requires access to the current time of day and the timestamp of the most recent prior interaction.
- Persona profile changes apply when the conversational routing path is active.
- Follow-up remark delivery requires the ability to schedule a deferred TTS utterance with a cancellation signal (triggered when user speech is detected during the pause window).

## Clarifications

### Session 2026-02-26

- Q: When should follow-up remarks be delivered relative to task completion? → A: After a pause — separate TTS utterance ~1–2 seconds after confirmation TTS ends, suppressed if user speaks first.
- Q: Should response personalization (greetings, follow-ups, minimal mode preference) be per registered identity or shared across the household? → A: Per recognized identity — each registered person has their own interaction history and preferences.
- Q: How long should minimal/direct mode persist once activated? → A: Permanently across sessions until the user explicitly disables it (e.g., "svara normalt").
- Q: How should SC-006 ("feels like a companion") be measured objectively? → A: Structured self-rating — primary user rates companion quality ≥4/5 after one week of daily use.
