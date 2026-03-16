# Feature Specification: Desk Presence Tracking

**Feature Branch**: `004-presence-tracking`
**Created**: 2026-03-05
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Daily Away-Trip Summary (Priority: P1)

Jarvis automatically tracks each time the user leaves and returns to the desk area during the day. At the end of the day, or when asked, Jarvis can report how many times the user stepped away, for how long on average, and when the longest break was.

**Why this priority**: Core value — passive data collection with zero user effort. Delivers useful insight immediately on day one.

**Independent Test**: Step away from the desk a few times during the day, then ask Jarvis "hur många gånger har jag gått ifrån datorn idag?" and verify count and durations are correct.

**Acceptance Scenarios**:

1. **Given** the user is at their desk, **When** they leave and return, **Then** one away-trip is recorded with correct start time and duration.
2. **Given** multiple away-trips have occurred today, **When** the user asks Jarvis about their activity, **Then** Jarvis answers in Swedish with count, average duration, and longest break.
3. **Given** the user has been sitting for over 2 hours without a break, **When** they next speak to Jarvis, **Then** Jarvis mentions this naturally ("du har suttit i 2,5 timmar utan paus").

---

### User Story 2 — Spontaneous Awareness Comments (Priority: P2)

Jarvis weaves presence observations naturally into conversation without being asked — when the user returns from a long break, or after a long unbroken sitting session.

**Why this priority**: Makes Jarvis feel genuinely aware rather than just a query tool. High personality value at low implementation cost.

**Independent Test**: Sit for 3+ hours without leaving, then speak to Jarvis on any topic. Verify Jarvis mentions the long sitting session at least once.

**Acceptance Scenarios**:

1. **Given** the user returns from a break longer than 15 minutes, **When** they next speak to Jarvis, **Then** Jarvis may acknowledge the break ("välkommen tillbaka, lång paus?").
2. **Given** the user has not moved for over 2 hours, **When** they initiate any conversation, **Then** Jarvis notes this at most once per conversation session.
3. **Given** Jarvis has already commented on sitting, **When** the user talks again in the same hour, **Then** Jarvis does NOT repeat the same comment.

---

### User Story 3 — Weekly Patterns (Priority: P3)

Over multiple days, Jarvis builds a picture of the user's desk habits — typical break frequency, usual break times, most sedentary days.

**Why this priority**: Long-term value but requires data accumulation. Builds directly on P1.

**Independent Test**: After 5+ days of data, ask "hur ser mina vanor ut den här veckan?" and verify Jarvis describes meaningful patterns.

**Acceptance Scenarios**:

1. **Given** 5+ days of trip data, **When** asked about weekly patterns, **Then** Jarvis summarises at least: most active day, quietest day, typical break frequency.
2. **Given** today's behaviour differs significantly from the weekly average, **When** the user asks, **Then** Jarvis notes the difference ("du rör dig mer än vanligt idag").

---

### Edge Cases

- What if the person sensor triggers briefly (< 60 seconds) due to walking past or glitch? → Trip is discarded, not recorded.
- What if the user is away for hours (left home, sleeping)? → Trips over 4 hours are stored but excluded from desk-break statistics.
- What if the person sensor or HA is offline? → Tracking pauses silently; no errors in conversation.
- What if the user asks about presence data on their first day? → Jarvis responds: "jag har inte samlat tillräckligt med data ännu."

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST detect presence transitions using the existing Home Assistant Reolink person sensor — no new hardware or vision model required.
- **FR-002**: Each away-trip MUST be recorded locally with: date, start time, end time, duration, and time-of-day category (morning/afternoon/evening).
- **FR-003**: Trips shorter than 60 seconds MUST be discarded (sensor noise filter).
- **FR-004**: Trips longer than 4 hours MUST be stored but excluded from desk-break statistics.
- **FR-005**: A daily summary MUST be available to Jarvis as conversation context on every turn, including: trips today, average duration, longest break, longest unbroken sitting streak.
- **FR-006**: A weekly summary MUST be available to Jarvis as conversation context, including: per-day trip counts, most/least active days, typical break time windows.
- **FR-007**: Jarvis MUST be able to answer direct questions about today's and this week's presence data in Swedish.
- **FR-008**: Jarvis SHOULD proactively mention sitting streaks over 2 hours — at most once per conversation session.
- **FR-009**: All data MUST remain on-premises in the existing local database — nothing leaves the local network.
- **FR-010**: The feature MUST degrade gracefully if the HA sensor is unavailable — no crashes, no repeated error messages to the user.

### Key Entities

- **Away-trip**: A single absence event — when the user left, when they returned, duration, time-of-day category.
- **Daily summary**: Aggregated statistics for a calendar day — trip count, average duration, longest break, longest sitting streak.
- **Weekly pattern**: Aggregated view across 7 days — per-day summaries and deviation from average behaviour.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Away-trips are recorded with correct start/end times — manual spot-check across 10 known leave/return events shows ≥ 90% accuracy.
- **SC-002**: Jarvis answers "hur många gånger har jag gått ifrån datorn idag?" correctly within 2 seconds.
- **SC-003**: Jarvis spontaneously mentions a 2+ hour sitting streak during the next conversation after the threshold is crossed — verified in manual testing.
- **SC-004**: After 5 days of data, Jarvis produces at least 3 meaningful weekly pattern observations when asked.
- **SC-005**: Trips under 60 seconds do not appear in any summary — verified by triggering the sensor briefly.
- **SC-006**: No tracking errors appear in logs when HA sensor is intentionally taken offline for 10 minutes.

## Assumptions

- The camera's field of view covers the desk area well enough that "person visible = near desk" is a reasonable proxy. The feature does not distinguish "at desk" from "in the same room."
- One primary user. Multi-person disambiguation is out of scope.
- Sessions outside 06:00–23:00 local time are excluded from statistics.
- The HA integration method (polling vs event-driven webhook) is resolved during planning.
