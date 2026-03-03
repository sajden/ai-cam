# Research: Humanize AI Companion Personality

**Branch**: `001-humanize-ai-companion` | **Date**: 2026-02-26

## 1. LRU Variant Selection for Response Pools

**Decision**: In-memory `collections.OrderedDict` with write-through to a new `response_pool_usage` table in the existing `aihub.db` SQLite database.

**Rationale**:
- The existing `db.connect()` context manager and `DB_PATH` already own the SQLite file — adding one table costs zero new dependencies.
- The in-memory `OrderedDict` handles the hot path with no I/O; SQLite is touched only on write (one `INSERT OR REPLACE` per selection) and on startup (one `SELECT` to seed the LRU cache from persisted state).
- Container restarts reset pure in-memory state. The spec (SC-001) requires no phrase repeats more than twice in 10 consecutive triggers. Surviving restarts is required.
- All mutations are wrapped in a `threading.Lock` consistent with the existing concurrency model in `main.py`.

**New SQLite table**:
```sql
CREATE TABLE IF NOT EXISTS response_pool_usage (
    pool_name TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    used_at TEXT NOT NULL,
    PRIMARY KEY (pool_name, variant_key)
);
```

**Alternatives considered**:
- Pure in-memory dict only → loses LRU order on container restart, violates SC-001 post-deploy.
- SQLite-only → synchronous I/O in the wake-ack hot path adds unacceptable latency jitter.
- Redis → new service dependency, violates Constitution Principle V (Minimal External Surface).

---

## 2. Deferred/Cancellable TTS for Follow-Up Remarks

**Decision**: `threading.Timer` for the delay + `threading.Event` as a cancel flag, checked inside the delivery callback before `speak_to_camera` is called.

**Pattern**:
```python
_followup_cancel = threading.Event()
_followup_lock = threading.Lock()
_pending_followup_timer: threading.Timer | None = None

def schedule_followup(text: str, delay_sec: float = 1.5) -> None:
    global _pending_followup_timer
    with _followup_lock:
        if _pending_followup_timer is not None:
            _pending_followup_timer.cancel()
        _followup_cancel.clear()
        def _deliver() -> None:
            if _followup_cancel.is_set():
                return
            try:
                speak_to_camera(text, "audio", event="reply")
            except Exception as exc:
                log.error("Follow-up TTS failed: %s", exc)
        _pending_followup_timer = threading.Timer(delay_sec, _deliver)
        _pending_followup_timer.daemon = True
        _pending_followup_timer.start()

def cancel_followup() -> None:
    _followup_cancel.set()
    with _followup_lock:
        if _pending_followup_timer is not None:
            _pending_followup_timer.cancel()
```

`cancel_followup()` is called at the top of each new audio turn request handler.

**Rationale**:
- `threading.Timer` is a direct subclass of `threading.Thread` — zero new imports, fits the 14 existing `threading.Thread` TTS dispatch sites.
- `threading.Event` is the correct thread-safe boolean flag; O(1) set/check with no polling.
- `timer.cancel()` reliably prevents the callback if called before the delay elapses. The `is_set()` guard inside `_deliver` handles the race where the callback has already started when `cancel()` fires.

**Alternatives considered**:
- `asyncio.sleep` / `asyncio.Task.cancel()` → no persistent asyncio event loop in `aihub`; requires full architectural migration.
- `queue.Queue` with consumer thread → correct but adds a permanent background thread for a feature that fires a few times per hour.
- `time.sleep` in raw daemon thread → not cancellable without a shared flag (which is what `threading.Event` is).

---

## 3. Dynamic Context Injection into System Prompt

**Decision**: Static base prompt remains unchanged. A `_build_session_context_block()` function constructs a compact `[Session]` suffix at call time; the concatenated result is passed as `system_prompt` in the `ask_codex` payload.

**Pattern**:
```python
def _build_session_context_block(
    identity_name: str | None,
    time_of_day: str,
    recent_activity: str | None,
    companion_mode: bool,
) -> str:
    lines = []
    if identity_name:
        lines.append(f"Användaren heter {identity_name}.")
    if time_of_day:
        lines.append(f"Tid på dygnet: {time_of_day}.")
    if recent_activity:
        lines.append(f"Senaste aktivitet: {recent_activity[:120]}.")
    if not companion_mode:
        lines.append("Svarsstil: kortfattad och direkt.")
    return ("\n\n[Session]\n" + "\n".join(lines)) if lines else ""
```

**Token budget**: ~60–90 tokens added when fully populated (≤ 370 total). Well within model limits.

**Rationale**:
- `ask_codex` already accepts `system_prompt` as a payload field (line 130 of `codex_client.py`). This is a one-line change at each call site.
- The `[Session]` header gives the model a clear semantic boundary between static rules and transient facts.
- Gated fields (only appended when non-empty) prevent token bloat in anonymous or simple sessions.

**Alternatives considered**:
- Injecting context into first user message → visible in conversation history, confuses multi-turn sessions.
- Startup-time env var template substitution → bakes per-session values (name, time) as startup constants.
- Few-shot personality examples in the base prompt → 100–400 tokens per example, expensive and redundant with pre-authored pools.

---

## 4. Minimal Mode Detection (Verbal Mode Switch)

**Decision**: Two module-level compiled regex patterns + `_detect_minimal_mode_switch()` private function in `main.py`, evaluated as a pre-flight guard before `detect_camera_intent()` is reached (consistent with `_is_training_start_command` / `_is_training_stop_command` pattern).

**Patterns**:
```python
_MINIMAL_MODE_ON = re.compile(
    r"\b(svara|prata|var)\b.{0,20}\b(kort(are)?|enkelt|koncist|direkt|kortfattat)\b",
    re.IGNORECASE,
)
_MINIMAL_MODE_OFF = re.compile(
    r"\b(svara|prata|var)\b.{0,20}\b(normalt?|som vanligt|utf(ö|o)rligt)\b",
    re.IGNORECASE,
)
```

**Confirmation strings** (env-var-backed per Constitution Principle III):
- `AIHUB_MINIMAL_MODE_ON_ACK_TEXT` → default: `"Okej, jag svarar kortare."`
- `AIHUB_MINIMAL_MODE_OFF_ACK_TEXT` → default: `"Okej, jag svarar som vanligt igen."`

**`intent_detector.py` is not modified** — its contract (camera PTZ + Spotify + vision) remains clean.

**Rationale**:
- Two-signal pattern (verb of speech + adverb of brevity) eliminates false positives for incidental use of "kort" or "normalt" in unrelated sentences.
- Pre-flight placement ensures mode switches always intercept before Codex routing — consistent with training start/stop pattern.
- Per-identity persistence lives in `main.py` because identity context is already resolved there.

**Alternatives considered**:
- Adding intents to `intent_detector.py` → blurs its clean boundary; state-write would infect a pure detection module.
- LLM classification via Ollama → adds 1–2s latency to what should be instant meta-commands.

---

## 5. Swedish Response Phrase Pools (sv-SE, Sofie Neural)

All phrases authored for Microsoft Sofie Neural TTS. Key prosody notes: short clause boundaries read better; exclamation marks produce natural rising intonation for greetings; avoid UPPERCASE mid-sentence (over-stressed by Sofie).

### Wake Acknowledgement Pool

**Morning (06:00–11:00)**:
- `"God morgon! Vad kan jag hjälpa dig med?"`
- `"Morgon! Vad gäller det?"`
- `"Hej hej, god morgon. Vad behöver du?"`

**Afternoon (11:00–18:00)**:
- `"Hej! Vad kan jag göra för dig?"`
- `"Här är jag. Vad är det?"`
- `"Ja, hej! Vad önskar du?"`

**Evening (18:00–22:00)**:
- `"God kväll! Vad kan jag hjälpa till med?"`
- `"Hej igen. Vad gäller det?"`
- `"Här är jag. Vad behöver du?"`

**Short continuity (last interaction < 10 min)**:
- `"Ja?"` / `"Vad mer?"` / `"Ja, vad är det?"` / `"Mm, vad gäller det?"` / `"Hör på."`

**With known identity** (name substitution):
- `"Hej {name}! Vad kan jag hjälpa dig med?"`
- `"Ja, {name}?"`
- `"Här är jag, {name}. Vad gäller det?"`

### Task Confirmation Pools

**Spotify play**: `"Kör igång musiken."` / `"Sätter på musik nu."` / `"Startar musiken."`

**Spotify pause**: `"Pausar musiken."` / `"Okej, tyst nu."` / `"Stannar musiken."`

**Spotify next**: `"Nästa låt."` / `"Hoppar vidare."` / `"Byter låt."`

**Spotify prev**: `"Går tillbaka."` / `"Spelar om igen."` / `"Föregående låt."`

**Camera follow start**: `"Håller koll på dig."` / `"Följer med dig nu."` / `"Okej, jag ser dig."`

**Camera follow stop**: `"Slutar följa."` / `"Stannar kameran."` / `"Okej, stannar här."`

**Training start (with name)**: `"Kör på, {name}! Jag räknar."` / `"Okej {name}, jag håller koll. Kör!"` / `"Startar. Visa vad du går för, {name}!"`

**Training stop**: `"Bra jobbat! Sparar passet."` / `"Klart! Bra kämpat."` / `"Avrundar nu. Bra gjort."`

### Follow-Up Remarks After Workout
- `"Hoppas det kändes bra."` / `"Starkt jobbat."` / `"Imponerande. Bra gjort."` / `"Kom ihåg att dricka vatten."` / `"Det där var riktigt fint."` / `"Du är bra på det här."`

### Empathetic Error Phrases
- `"Oj, något gick snett. Förlåt."` / `"Hmm, det funkade inte den här gången."` / `"Det gick inte som planerat, förlåt."`

### Processing Acknowledgement Pool
- `"Ja självklart, ett ögonblick."` / `"Låt mig kolla det."` / `"En sekund, jag letar upp det."` / `"Vänta lite, jag kollar."` / `"Okej, jag tar reda på det."`

---

## 6. Expanded System Prompt (Persona Profile)

The existing base prompt is extended with warmth and social engagement guidance. The new section is appended after the existing tool rules:

```
Personlighet:
- Du är varm, nyfiken och engagerad — inte bara ett verktyg.
- Om någon frågar hur du mår eller vad du tycker, svara kort och naturligt utan att avfärda frågan.
- Du kan ställa en följdfråga om användaren verkar vilja prata mer.
- Om en begäran är oklar, fråga snabbt vad de menar snarare än att gissa tyst.
- Undvik fraser som "Som en AI kan jag inte..." — du kan alltid svara något naturligt.
```
