from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DB_PATH = Path(os.getenv("AIHUB_DB_PATH", "/data/aihub.db"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mode_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                used_brain TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_sessions (
                task_session_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                task_goal TEXT NOT NULL,
                active INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS athletes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS person_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                athlete_id INTEGER NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(athlete_id) REFERENCES athletes(id)
            );

            CREATE TABLE IF NOT EXISTS face_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER NOT NULL,
                embedding_json TEXT NOT NULL,
                source TEXT NOT NULL,
                quality REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(person_id) REFERENCES person_profiles(id)
            );

            CREATE TABLE IF NOT EXISTS conversation_identity (
                conversation_id TEXT PRIMARY KEY,
                person_id INTEGER NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(person_id) REFERENCES person_profiles(id)
            );

            CREATE TABLE IF NOT EXISTS task_identity (
                task_session_id TEXT PRIMARY KEY,
                person_id INTEGER NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(person_id) REFERENCES person_profiles(id)
            );

            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_session_id TEXT NOT NULL UNIQUE,
                conversation_id TEXT NOT NULL,
                athlete_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                task_goal TEXT NOT NULL,
                active INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(athlete_id) REFERENCES athletes(id)
            );

            CREATE TABLE IF NOT EXISTS workout_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER NOT NULL,
                exercise TEXT NOT NULL,
                reps_total INTEGER NOT NULL,
                max_streak INTEGER NOT NULL,
                avg_form_score REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(workout_id, exercise),
                FOREIGN KEY(workout_id) REFERENCES workouts(id)
            );

            CREATE TABLE IF NOT EXISTS rep_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                set_id INTEGER NOT NULL,
                rep_index INTEGER NOT NULL,
                ts TEXT NOT NULL,
                depth_score REAL,
                tempo_ms REAL,
                form_score REAL,
                form_flags TEXT NOT NULL,
                fatigue_score REAL NOT NULL,
                confidence REAL NOT NULL,
                summary_sv TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(set_id, rep_index),
                FOREIGN KEY(set_id) REFERENCES workout_sets(id)
            );

            CREATE TABLE IF NOT EXISTS personal_records (
                athlete_id INTEGER NOT NULL,
                exercise TEXT NOT NULL,
                best_reps INTEGER NOT NULL,
                best_date TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (athlete_id, exercise),
                FOREIGN KEY(athlete_id) REFERENCES athletes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_workouts_athlete_started
                ON workouts(athlete_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_workout_sets_exercise
                ON workout_sets(exercise);
            CREATE INDEX IF NOT EXISTS idx_rep_events_set
                ON rep_events(set_id, rep_index DESC);
            CREATE INDEX IF NOT EXISTS idx_face_embeddings_person
                ON face_embeddings(person_id, id DESC);

            CREATE TABLE IF NOT EXISTS response_pool_usage (
                pool_name   TEXT NOT NULL,
                variant_key TEXT NOT NULL,
                used_at     TEXT NOT NULL,
                PRIMARY KEY (pool_name, variant_key)
            );

            CREATE TABLE IF NOT EXISTS person_presence (
                person_name  TEXT PRIMARY KEY,
                last_seen_at TEXT NOT NULL,
                arrived_at   TEXT,
                greeted_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS memory_facts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name    TEXT NOT NULL,
                fact_text      TEXT NOT NULL,
                category       TEXT NOT NULL DEFAULT 'general',
                source_conv_id TEXT,
                extracted_at   TEXT NOT NULL,
                follow_up_date TEXT,
                followed_up_at TEXT,
                active         INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_memory_facts_person
                ON memory_facts(person_name, active, extracted_at DESC);

            CREATE TABLE IF NOT EXISTS route_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id TEXT NOT NULL,
                source TEXT NOT NULL,
                intent TEXT NOT NULL,
                used_brain TEXT NOT NULL,
                egress TEXT NOT NULL,
                decision_reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS turn_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                source TEXT NOT NULL,
                user_text TEXT NOT NULL,
                used_brain TEXT NOT NULL,
                stt_to_aihub_ms REAL,
                codex_ms REAL,
                codex_search_used INTEGER,
                camera_actions_ms REAL,
                aihub_total_ms REAL NOT NULL,
                tts_request_ms REAL,
                tts_ok INTEGER,
                tts_reason TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
    _seed_defaults()


def _seed_defaults() -> None:
    defaults = {
        "current_mode": "idle",
        "privacy_mode": "false",
        "task_session_mode": "false",
        "conversation_id": "",
        "task_session_id": "",
        "conversation_expires_at": "",
        "speaker_playing": "false",
        "speaker_done_at": "",
    }
    with connect() as conn:
        for key, value in defaults.items():
            conn.execute(
                """
                INSERT INTO mode_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (key, value, now_iso()),
            )


def get_mode_state() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM mode_state").fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_mode_state(values: dict[str, str]) -> None:
    ts = now_iso()
    with connect() as conn:
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO mode_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, ts),
            )


def insert_turn(
    conversation_id: str,
    role: str,
    text: str,
    source: str,
    used_brain: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO conversation_turns (conversation_id, role, text, source, used_brain, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, text, source, used_brain, now_iso()),
        )


def get_memory_context(conversation_id: str, k: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT role, text, created_at
            FROM conversation_turns
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, k),
        ).fetchall()
    items = [
        {"timestamp": row["created_at"], "role": row["role"], "text": row["text"]}
        for row in rows
    ]
    items.reverse()
    return items


def get_latest_conversation_id(source: str | None = None) -> str:
    with connect() as conn:
        if source:
            row = conn.execute(
                """
                SELECT conversation_id
                FROM conversation_turns
                WHERE source = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (source,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT conversation_id
                FROM conversation_turns
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
    if not row:
        return ""
    return str(row["conversation_id"] or "").strip()


def _tokenize(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-zA-ZåäöÅÄÖ0-9]+", str(text).lower())
        if len(t) >= 2
    }


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def search_relevant_memory(
    query: str,
    k: int,
    current_conversation_id: str = "",
    lookback: int = 240,
) -> list[dict]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT conversation_id, role, text, created_at
            FROM conversation_turns
            ORDER BY id DESC
            LIMIT ?
            """,
            (lookback,),
        ).fetchall()

    now = datetime.now(timezone.utc)
    scored: list[tuple[float, dict]] = []
    for row in rows:
        text = str(row["text"])
        t_tokens = _tokenize(text)
        if not t_tokens:
            continue
        overlap = len(q_tokens & t_tokens)
        if overlap == 0:
            continue
        score = float(overlap)
        if row["conversation_id"] != current_conversation_id:
            score += 0.2
        if str(query).lower() in text.lower():
            score += 0.8

        age_min = max(0.0, (now - _parse_ts(row["created_at"])).total_seconds() / 60.0)
        recency = 1.0 / (1.0 + (age_min / 120.0))
        score += recency

        scored.append(
            (
                score,
                {
                    "timestamp": row["created_at"],
                    "role": row["role"],
                    "text": text,
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [item for _, item in scored[:k]]
    picked.sort(key=lambda x: x["timestamp"])
    return picked


def get_recent_turns(
    *,
    hours: int,
    limit: int,
    current_conversation_id: str = "",
) -> list[dict]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max(1, hours))
    fetch_n = max(limit * 20, 500)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT conversation_id, role, text, created_at
            FROM conversation_turns
            ORDER BY id DESC
            LIMIT ?
            """,
            (fetch_n,),
        ).fetchall()

    out: list[dict] = []
    for row in rows:
        ts = _parse_ts(str(row["created_at"]))
        if ts < cutoff:
            continue
        if current_conversation_id and str(row["conversation_id"]) == current_conversation_id:
            continue
        out.append(
            {
                "timestamp": row["created_at"],
                "role": row["role"],
                "text": row["text"],
            }
        )
        if len(out) >= limit:
            break
    out.reverse()
    return out


def create_task_session(
    task_session_id: str,
    conversation_id: str,
    task_type: str,
    task_goal: str,
) -> None:
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO task_sessions (task_session_id, conversation_id, task_type, task_goal, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (task_session_id, conversation_id, task_type, task_goal, ts, ts),
        )


def stop_task_session(task_session_id: str) -> bool:
    ts = now_iso()
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE task_sessions
            SET active = 0, updated_at = ?
            WHERE task_session_id = ?
            """,
            (ts, task_session_id),
        )
    return cur.rowcount > 0


def _normalize_athlete_name(name: str | None) -> str:
    cleaned = " ".join(str(name or "").strip().split())
    return cleaned


def _require_athlete_name(name: str | None) -> str:
    cleaned = _normalize_athlete_name(name)
    if not cleaned:
        raise ValueError("athlete_name_required")
    return cleaned


def _normalize_exercise(activity: str) -> str:
    raw = str(activity or "").strip().lower()
    if not raw:
        return "unknown"
    compact = re.sub(r"[^a-zA-ZåäöÅÄÖ0-9]+", "_", raw).strip("_")
    return compact or "unknown"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_float(value: float | int | None, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _parse_int(value: int | None, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _compute_form_score(*, form_flags: list[str], fatigue_score: float, confidence: float) -> float:
    # 1.0 is excellent form; penalties apply for fatigue and form flags.
    score = _clamp(confidence, 0.0, 1.0)
    score -= 0.10 * max(0, len(form_flags))
    score -= 0.25 * _clamp(fatigue_score, 0.0, 1.0)
    return round(_clamp(score, 0.0, 1.0), 4)


def _get_or_create_athlete_id(conn: sqlite3.Connection, name: str) -> int:
    athlete_name = _require_athlete_name(name)
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO athletes (name, created_at, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at
        """,
        (athlete_name, ts, ts),
    )
    row = conn.execute(
        "SELECT id FROM athletes WHERE name = ? LIMIT 1",
        (athlete_name,),
    ).fetchone()
    if not row:
        raise RuntimeError("athlete_upsert_failed")
    return int(row["id"])


def _upsert_person_profile(
    conn: sqlite3.Connection,
    *,
    athlete_id: int,
    display_name: str,
) -> int:
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO person_profiles (athlete_id, display_name, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(athlete_id) DO UPDATE SET
            display_name = excluded.display_name,
            updated_at = excluded.updated_at
        """,
        (athlete_id, display_name, ts, ts),
    )
    row = conn.execute(
        """
        SELECT id
        FROM person_profiles
        WHERE athlete_id = ?
        LIMIT 1
        """,
        (athlete_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("person_profile_upsert_failed")
    return int(row["id"])


def _normalize_embedding(values: list[float] | None) -> list[float]:
    if not values:
        return []
    out: list[float] = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        out.append(value)
        if len(out) >= 4096:
            break
    return out


def _cosine_similarity(a: list[float], b: list[float]) -> float | None:
    if not a or not b:
        return None
    if len(a) != len(b):
        return None
    n = len(a)
    if n <= 0:
        return None
    dot = 0.0
    a_sq = 0.0
    b_sq = 0.0
    for i in range(n):
        av = float(a[i])
        bv = float(b[i])
        dot += av * bv
        a_sq += av * av
        b_sq += bv * bv
    if a_sq <= 0.0 or b_sq <= 0.0:
        return None
    return dot / ((a_sq ** 0.5) * (b_sq ** 0.5))


def remember_identity(
    *,
    athlete_name: str,
    embedding: list[float] | None = None,
    source: str = "manual",
    quality: float | None = None,
) -> dict[str, Any]:
    display_name = _require_athlete_name(athlete_name)
    vector = _normalize_embedding(embedding)
    if vector and len(vector) < 32:
        raise ValueError("embedding_too_short")
    src = str(source or "manual").strip() or "manual"
    ts = now_iso()
    with connect() as conn:
        athlete_id = _get_or_create_athlete_id(conn, display_name)
        person_id = _upsert_person_profile(
            conn,
            athlete_id=athlete_id,
            display_name=display_name,
        )
        if vector:
            conn.execute(
                """
                INSERT INTO face_embeddings (person_id, embedding_json, source, quality, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    person_id,
                    json.dumps(vector, ensure_ascii=False, separators=(",", ":")),
                    src,
                    _parse_float(quality, 0.0) if quality is not None else None,
                    ts,
                ),
            )
    return {
        "athlete_name": display_name,
        "athlete_id": athlete_id,
        "person_id": person_id,
        "embedding_saved": bool(vector),
    }


def bind_identity_to_conversation(
    *,
    conversation_id: str,
    athlete_name: str,
    confidence: float = 1.0,
    source: str = "manual",
) -> dict[str, Any]:
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        raise ValueError("conversation_id_required")
    display_name = _require_athlete_name(athlete_name)
    src = str(source or "manual").strip() or "manual"
    score = _clamp(_parse_float(confidence, 1.0), 0.0, 1.0)
    ts = now_iso()
    with connect() as conn:
        athlete_id = _get_or_create_athlete_id(conn, display_name)
        person_id = _upsert_person_profile(
            conn,
            athlete_id=athlete_id,
            display_name=display_name,
        )
        conn.execute(
            """
            INSERT INTO conversation_identity (conversation_id, person_id, confidence, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                person_id = excluded.person_id,
                confidence = excluded.confidence,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (conv_id, person_id, score, src, ts),
        )
    return {
        "conversation_id": conv_id,
        "athlete_name": display_name,
        "person_id": person_id,
        "confidence": score,
        "source": src,
    }


def bind_identity_to_task(
    *,
    task_session_id: str,
    athlete_name: str,
    confidence: float = 1.0,
    source: str = "manual",
) -> dict[str, Any]:
    task_id = str(task_session_id or "").strip()
    if not task_id:
        raise ValueError("task_session_id_required")
    display_name = _require_athlete_name(athlete_name)
    src = str(source or "manual").strip() or "manual"
    score = _clamp(_parse_float(confidence, 1.0), 0.0, 1.0)
    ts = now_iso()
    with connect() as conn:
        athlete_id = _get_or_create_athlete_id(conn, display_name)
        person_id = _upsert_person_profile(
            conn,
            athlete_id=athlete_id,
            display_name=display_name,
        )
        conn.execute(
            """
            INSERT INTO task_identity (task_session_id, person_id, confidence, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(task_session_id) DO UPDATE SET
                person_id = excluded.person_id,
                confidence = excluded.confidence,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (task_id, person_id, score, src, ts),
        )
    return {
        "task_session_id": task_id,
        "athlete_name": display_name,
        "person_id": person_id,
        "confidence": score,
        "source": src,
    }


def get_conversation_identity(conversation_id: str) -> dict[str, Any] | None:
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                ci.conversation_id,
                ci.person_id,
                ci.confidence,
                ci.source,
                ci.updated_at,
                a.name AS athlete_name
            FROM conversation_identity ci
            JOIN person_profiles pp ON pp.id = ci.person_id
            JOIN athletes a ON a.id = pp.athlete_id
            WHERE ci.conversation_id = ?
            LIMIT 1
            """,
            (conv_id,),
        ).fetchone()
    return dict(row) if row else None


def get_task_identity(task_session_id: str) -> dict[str, Any] | None:
    task_id = str(task_session_id or "").strip()
    if not task_id:
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                ti.task_session_id,
                ti.person_id,
                ti.confidence,
                ti.source,
                ti.updated_at,
                a.name AS athlete_name
            FROM task_identity ti
            JOIN person_profiles pp ON pp.id = ti.person_id
            JOIN athletes a ON a.id = pp.athlete_id
            WHERE ti.task_session_id = ?
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def resolve_identity_by_embedding(
    *,
    embedding: list[float],
    min_score: float = 0.82,
) -> dict[str, Any]:
    vector = _normalize_embedding(embedding)
    if not vector or len(vector) < 32:
        raise ValueError("invalid_embedding")

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                fe.person_id,
                fe.embedding_json,
                a.name AS athlete_name
            FROM face_embeddings fe
            JOIN person_profiles pp ON pp.id = fe.person_id
            JOIN athletes a ON a.id = pp.athlete_id
            ORDER BY fe.id DESC
            LIMIT 1000
            """
        ).fetchall()

    if not rows:
        return {
            "matched": False,
            "athlete_name": "",
            "person_id": None,
            "score": 0.0,
            "min_score": round(_clamp(_parse_float(min_score, 0.82), 0.0, 1.0), 4),
            "candidates": 0,
        }

    best_by_person: dict[int, tuple[float, str]] = {}
    for row in rows:
        try:
            candidate_vec = _normalize_embedding(json.loads(str(row["embedding_json"])))
        except Exception:
            continue
        score = _cosine_similarity(vector, candidate_vec)
        if score is None:
            continue
        person_id = int(row["person_id"])
        athlete_name = str(row["athlete_name"] or "")
        current = best_by_person.get(person_id)
        if current is None or score > current[0]:
            best_by_person[person_id] = (score, athlete_name)

    threshold = _clamp(_parse_float(min_score, 0.82), 0.0, 1.0)
    if not best_by_person:
        return {
            "matched": False,
            "athlete_name": "",
            "person_id": None,
            "score": 0.0,
            "min_score": round(threshold, 4),
            "candidates": 0,
        }

    person_id, picked = max(best_by_person.items(), key=lambda x: x[1][0])
    score, athlete_name = picked
    matched = score >= threshold
    return {
        "matched": matched,
        "athlete_name": athlete_name if matched else "",
        "person_id": person_id if matched else None,
        "score": round(score, 4),
        "min_score": round(threshold, 4),
        "candidates": len(best_by_person),
    }


def get_embedding_count_for_athlete(athlete_name: str) -> int:
    display_name = _require_athlete_name(athlete_name)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(fe.id) AS n
            FROM athletes a
            JOIN person_profiles pp ON pp.athlete_id = a.id
            LEFT JOIN face_embeddings fe ON fe.person_id = pp.id
            WHERE a.name = ?
            """,
            (display_name,),
        ).fetchone()
    if not row:
        return 0
    return _parse_int(row["n"], 0)


def get_task_session(task_session_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT task_session_id, conversation_id, task_type, task_goal, active, created_at, updated_at
            FROM task_sessions
            WHERE task_session_id = ?
            LIMIT 1
            """,
            (task_session_id,),
        ).fetchone()
    return dict(row) if row else None


def ensure_workout_session(
    *,
    task_session_id: str,
    conversation_id: str,
    athlete_name: str,
    task_type: str,
    task_goal: str,
) -> dict[str, Any]:
    display_name = _require_athlete_name(athlete_name)
    ts = now_iso()
    with connect() as conn:
        athlete_id = _get_or_create_athlete_id(conn, display_name)
        row = conn.execute(
            """
            SELECT id
            FROM workouts
            WHERE task_session_id = ?
            LIMIT 1
            """,
            (task_session_id,),
        ).fetchone()
        if row:
            workout_id = int(row["id"])
            conn.execute(
                """
                UPDATE workouts
                SET conversation_id = ?,
                    athlete_id = ?,
                    task_type = ?,
                    task_goal = ?,
                    active = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (conversation_id, athlete_id, task_type, task_goal, ts, workout_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO workouts (
                    task_session_id, conversation_id, athlete_id, task_type, task_goal,
                    active, started_at, ended_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, NULL, ?, ?)
                """,
                (task_session_id, conversation_id, athlete_id, task_type, task_goal, ts, ts, ts),
            )
            workout_id = int(cur.lastrowid)
    return {
        "workout_id": workout_id,
        "athlete_id": athlete_id,
        "athlete_name": display_name,
    }


def stop_workout_session(task_session_id: str) -> bool:
    ts = now_iso()
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE workouts
            SET active = 0, ended_at = COALESCE(ended_at, ?), updated_at = ?
            WHERE task_session_id = ? AND active = 1
            """,
            (ts, ts, task_session_id),
        )
    return cur.rowcount > 0


def track_vision_event(
    *,
    task_session_id: str,
    conversation_id: str,
    athlete_name: str,
    task_type: str,
    task_goal: str,
    activity: str,
    rep_count: int | None,
    form_flags: list[str],
    fatigue_score: float,
    confidence: float,
    summary_sv: str,
    timestamp: str | None,
    depth_score: float | None = None,
    tempo_ms: float | None = None,
) -> dict[str, Any]:
    display_name = _require_athlete_name(athlete_name)
    ts = timestamp or now_iso()
    exercise = _normalize_exercise(activity)
    reps = max(0, _parse_int(rep_count, 0))
    fatigue = _clamp(_parse_float(fatigue_score, 0.0), 0.0, 1.0)
    conf = _clamp(_parse_float(confidence, 0.0), 0.0, 1.0)
    d_score = _parse_float(depth_score, 0.0) if depth_score is not None else None
    t_ms = _parse_float(tempo_ms, 0.0) if tempo_ms is not None else None
    flags = [str(x).strip() for x in form_flags if str(x).strip()]
    form_score = _compute_form_score(form_flags=flags, fatigue_score=fatigue, confidence=conf)

    with connect() as conn:
        athlete_id = _get_or_create_athlete_id(conn, display_name)

        workout_row = conn.execute(
            "SELECT id FROM workouts WHERE task_session_id = ? LIMIT 1",
            (task_session_id,),
        ).fetchone()
        if workout_row:
            workout_id = int(workout_row["id"])
            conn.execute(
                """
                UPDATE workouts
                SET conversation_id = ?,
                    athlete_id = ?,
                    task_type = ?,
                    task_goal = ?,
                    active = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (conversation_id, athlete_id, task_type, task_goal, now_iso(), workout_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO workouts (
                    task_session_id, conversation_id, athlete_id, task_type, task_goal,
                    active, started_at, ended_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, NULL, ?, ?)
                """,
                (task_session_id, conversation_id, athlete_id, task_type, task_goal, ts, now_iso(), now_iso()),
            )
            workout_id = int(cur.lastrowid)

        set_row = conn.execute(
            """
            SELECT id
            FROM workout_sets
            WHERE workout_id = ? AND exercise = ?
            LIMIT 1
            """,
            (workout_id, exercise),
        ).fetchone()
        if set_row:
            set_id = int(set_row["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO workout_sets (
                    workout_id, exercise, reps_total, max_streak, avg_form_score, created_at, updated_at
                )
                VALUES (?, ?, 0, 0, 0, ?, ?)
                """,
                (workout_id, exercise, now_iso(), now_iso()),
            )
            set_id = int(cur.lastrowid)

        rep_inserted = False
        if reps > 0:
            cur = conn.execute(
                """
                INSERT INTO rep_events (
                    set_id, rep_index, ts, depth_score, tempo_ms, form_score,
                    form_flags, fatigue_score, confidence, summary_sv, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(set_id, rep_index) DO UPDATE SET
                    ts = excluded.ts,
                    depth_score = excluded.depth_score,
                    tempo_ms = excluded.tempo_ms,
                    form_score = excluded.form_score,
                    form_flags = excluded.form_flags,
                    fatigue_score = excluded.fatigue_score,
                    confidence = excluded.confidence,
                    summary_sv = excluded.summary_sv
                """,
                (
                    set_id,
                    reps,
                    ts,
                    d_score,
                    t_ms,
                    form_score,
                    json.dumps(flags, ensure_ascii=False),
                    fatigue,
                    conf,
                    str(summary_sv or ""),
                    now_iso(),
                ),
            )
            rep_inserted = cur.rowcount > 0

            conn.execute(
                """
                UPDATE workout_sets
                SET reps_total = CASE WHEN ? > reps_total THEN ? ELSE reps_total END,
                    max_streak = CASE WHEN ? > max_streak THEN ? ELSE max_streak END,
                    updated_at = ?
                WHERE id = ?
                """,
                (reps, reps, reps, reps, now_iso(), set_id),
            )

        avg_row = conn.execute(
            "SELECT AVG(form_score) AS avg_form_score FROM rep_events WHERE set_id = ?",
            (set_id,),
        ).fetchone()
        avg_form_score = _parse_float(avg_row["avg_form_score"] if avg_row else 0.0, 0.0)
        conn.execute(
            "UPDATE workout_sets SET avg_form_score = ?, updated_at = ? WHERE id = ?",
            (round(avg_form_score, 4), now_iso(), set_id),
        )

        set_stats = conn.execute(
            """
            SELECT reps_total, max_streak, avg_form_score
            FROM workout_sets
            WHERE id = ?
            LIMIT 1
            """,
            (set_id,),
        ).fetchone()
        reps_total = _parse_int(set_stats["reps_total"] if set_stats else 0, 0)
        max_streak = _parse_int(set_stats["max_streak"] if set_stats else 0, 0)
        avg_form = _parse_float(set_stats["avg_form_score"] if set_stats else 0.0, 0.0)

        prev_pr_row = conn.execute(
            """
            SELECT best_reps
            FROM personal_records
            WHERE athlete_id = ? AND exercise = ?
            LIMIT 1
            """,
            (athlete_id, exercise),
        ).fetchone()
        prev_best = _parse_int(prev_pr_row["best_reps"] if prev_pr_row else 0, 0)

        if reps_total > 0:
            conn.execute(
                """
                INSERT INTO personal_records (athlete_id, exercise, best_reps, best_date, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(athlete_id, exercise) DO UPDATE SET
                    best_reps = CASE
                        WHEN excluded.best_reps > personal_records.best_reps THEN excluded.best_reps
                        ELSE personal_records.best_reps
                    END,
                    best_date = CASE
                        WHEN excluded.best_reps > personal_records.best_reps THEN excluded.best_date
                        ELSE personal_records.best_date
                    END,
                    updated_at = excluded.updated_at
                """,
                (athlete_id, exercise, reps_total, ts, now_iso()),
            )

        pr_row = conn.execute(
            """
            SELECT best_reps, best_date
            FROM personal_records
            WHERE athlete_id = ? AND exercise = ?
            LIMIT 1
            """,
            (athlete_id, exercise),
        ).fetchone()
        best_reps = _parse_int(pr_row["best_reps"] if pr_row else 0, 0)
        best_date = str(pr_row["best_date"] if pr_row else "")
        pr_updated = best_reps > prev_best

    return {
        "athlete_name": display_name,
        "exercise": exercise,
        "workout_id": workout_id,
        "set_id": set_id,
        "rep_inserted": rep_inserted,
        "reps_total": reps_total,
        "max_streak": max_streak,
        "avg_form_score": round(avg_form, 4),
        "best_reps": best_reps,
        "best_date": best_date,
        "personal_record_updated": pr_updated,
    }


def get_progress_stats(*, athlete_name: str, exercise: str, limit: int = 20) -> dict[str, Any]:
    athlete = _require_athlete_name(athlete_name)
    ex = _normalize_exercise(exercise)
    with connect() as conn:
        athlete_row = conn.execute(
            "SELECT id, name FROM athletes WHERE name = ? LIMIT 1",
            (athlete,),
        ).fetchone()
        if not athlete_row:
            return {
                "athlete_name": athlete,
                "exercise": ex,
                "best_reps": 0,
                "best_date": "",
                "latest_reps": 0,
                "trend_delta_reps": 0,
                "total_sessions": 0,
                "sessions": [],
            }
        athlete_id = int(athlete_row["id"])

        pr_row = conn.execute(
            """
            SELECT best_reps, best_date
            FROM personal_records
            WHERE athlete_id = ? AND exercise = ?
            LIMIT 1
            """,
            (athlete_id, ex),
        ).fetchone()

        rows = conn.execute(
            """
            SELECT
                w.id AS workout_id,
                w.task_session_id,
                w.started_at,
                w.ended_at,
                ws.reps_total,
                ws.max_streak,
                ws.avg_form_score
            FROM workouts w
            JOIN workout_sets ws ON ws.workout_id = w.id
            WHERE w.athlete_id = ? AND ws.exercise = ?
            ORDER BY w.started_at DESC
            LIMIT ?
            """,
            (athlete_id, ex, max(1, limit)),
        ).fetchall()

    sessions: list[dict[str, Any]] = []
    for row in rows:
        sessions.append(
            {
                "workout_id": int(row["workout_id"]),
                "task_session_id": str(row["task_session_id"]),
                "started_at": str(row["started_at"]),
                "ended_at": str(row["ended_at"] or ""),
                "reps_total": _parse_int(row["reps_total"], 0),
                "max_streak": _parse_int(row["max_streak"], 0),
                "avg_form_score": round(_parse_float(row["avg_form_score"], 0.0), 4),
            }
        )

    latest_reps = sessions[0]["reps_total"] if sessions else 0
    prev_reps = sessions[1]["reps_total"] if len(sessions) >= 2 else latest_reps
    trend_delta = int(latest_reps) - int(prev_reps)
    avg_reps = round(sum(int(s["reps_total"]) for s in sessions) / len(sessions), 2) if sessions else 0.0

    return {
        "athlete_name": athlete,
        "exercise": ex,
        "best_reps": _parse_int(pr_row["best_reps"] if pr_row else 0, 0),
        "best_date": str(pr_row["best_date"] if pr_row else ""),
        "latest_reps": int(latest_reps),
        "trend_delta_reps": trend_delta,
        "average_reps": avg_reps,
        "total_sessions": len(sessions),
        "sessions": sessions,
    }


def list_athlete_names(limit: int = 50) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM athletes
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, min(500, int(limit))),),
        ).fetchall()
    out: list[str] = []
    for row in rows:
        name = str(row["name"] or "").strip()
        if name:
            out.append(name)
    return out


def log_route(
    route_id: str,
    source: str,
    intent: str,
    used_brain: str,
    egress: str,
    decision_reason: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO route_logs (route_id, source, intent, used_brain, egress, decision_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (route_id, source, intent, used_brain, egress, decision_reason, now_iso()),
        )


def insert_turn_metric(
    *,
    conversation_id: str,
    source: str,
    user_text: str,
    used_brain: str,
    stt_to_aihub_ms: float | None,
    codex_ms: float | None,
    codex_search_used: bool | None,
    camera_actions_ms: float | None,
    aihub_total_ms: float,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO turn_metrics (
                conversation_id, source, user_text, used_brain,
                stt_to_aihub_ms, codex_ms, codex_search_used,
                camera_actions_ms, aihub_total_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                source,
                user_text,
                used_brain,
                stt_to_aihub_ms,
                codex_ms,
                (1 if codex_search_used else 0) if codex_search_used is not None else None,
                camera_actions_ms,
                aihub_total_ms,
                now_iso(),
            ),
        )
        return int(cur.lastrowid)


def update_turn_metric_tts(
    metric_id: int,
    *,
    tts_request_ms: float,
    tts_ok: bool,
    tts_reason: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE turn_metrics
            SET tts_request_ms = ?, tts_ok = ?, tts_reason = ?
            WHERE id = ?
            """,
            (tts_request_ms, 1 if tts_ok else 0, tts_reason, metric_id),
        )


def list_turn_metrics(limit: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id, conversation_id, source, user_text, used_brain,
                stt_to_aihub_ms, codex_ms, codex_search_used,
                camera_actions_ms, aihub_total_ms,
                tts_request_ms, tts_ok, tts_reason, created_at
            FROM turn_metrics
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def bool_to_db(value: bool) -> str:
    return "true" if value else "false"


def db_to_bool(value: str | None) -> bool:
    return str(value).lower() == "true"


def dump_json(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Response pool LRU helpers (T002, T003)
# ---------------------------------------------------------------------------

def load_pool_usage() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT pool_name, variant_key, used_at FROM response_pool_usage ORDER BY used_at ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_pool_usage(pool_name: str, variant_key: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO response_pool_usage (pool_name, variant_key, used_at)
            VALUES (?, ?, ?)
            ON CONFLICT(pool_name, variant_key) DO UPDATE SET used_at=excluded.used_at
            """,
            (pool_name, variant_key, now_iso()),
        )


# ---------------------------------------------------------------------------
# Per-identity companion preference helpers (T004)
# ---------------------------------------------------------------------------

def get_companion_pref(person_id: int) -> str:
    key = f"companion_pref_{person_id}"
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM mode_state WHERE key = ? LIMIT 1",
            (key,),
        ).fetchone()
    if not row:
        return "full"
    return str(row["value"]).strip() or "full"


def set_companion_pref(person_id: int, pref: str) -> None:
    key = f"companion_pref_{person_id}"
    set_mode_state({key: pref})


# ---------------------------------------------------------------------------
# Last interaction timestamp helper (T005)
# ---------------------------------------------------------------------------

def get_last_interaction_at(person_id: int | None) -> datetime | None:
    if person_id is None:
        with connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM conversation_turns ORDER BY id DESC LIMIT 1"
            ).fetchone()
    else:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT ct.created_at
                FROM conversation_turns ct
                JOIN conversation_identity ci ON ci.conversation_id = ct.conversation_id
                WHERE ci.person_id = ?
                ORDER BY ct.id DESC
                LIMIT 1
                """,
                (person_id,),
            ).fetchone()
    if not row:
        return None
    return _parse_ts(str(row["created_at"]))


# ---------------------------------------------------------------------------
# person_presence — arrival cooldown + presence tracking (T010)
# ---------------------------------------------------------------------------


def upsert_presence(person_name: str, last_seen_at: str | None = None) -> None:
    """Update last_seen_at for a person, creating the row if needed."""
    ts = last_seen_at or now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO person_presence (person_name, last_seen_at, arrived_at)
            VALUES (?, ?, ?)
            ON CONFLICT(person_name) DO UPDATE SET
                last_seen_at = excluded.last_seen_at
            """,
            (person_name, ts, ts),
        )


def set_greeted(person_name: str) -> None:
    """Record that this person was greeted just now (updates arrived_at too)."""
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO person_presence (person_name, last_seen_at, arrived_at, greeted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(person_name) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                arrived_at   = excluded.arrived_at,
                greeted_at   = excluded.greeted_at
            """,
            (person_name, ts, ts, ts),
        )


def get_presence(person_name: str) -> dict[str, Any]:
    """Return presence dict for a person or empty dict if unknown."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT person_name, last_seen_at, arrived_at, greeted_at
            FROM person_presence
            WHERE person_name = ?
            LIMIT 1
            """,
            (person_name,),
        ).fetchone()
    return dict(row) if row else {}


def is_new_arrival(person_name: str, cooldown_sec: int) -> bool:
    """Return True if the person has not been greeted within cooldown_sec seconds."""
    presence = get_presence(person_name)
    if not presence or not presence.get("greeted_at"):
        return True
    greeted_at = _parse_ts(str(presence["greeted_at"]))
    elapsed = (datetime.now(timezone.utc) - greeted_at).total_seconds()
    return elapsed >= cooldown_sec


# ---------------------------------------------------------------------------
# mode_state helpers: last_unknown_face_at (T011)
# ---------------------------------------------------------------------------


def get_last_unknown_face_at() -> datetime | None:
    """Return when an unknown face was last seen, or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM mode_state WHERE key = 'last_unknown_face_at' LIMIT 1"
        ).fetchone()
    if not row or not row["value"]:
        return None
    return _parse_ts(str(row["value"]))


def set_last_unknown_face_at(ts: str | None = None) -> None:
    """Record that an unknown face was just seen."""
    set_mode_state({"last_unknown_face_at": ts or now_iso()})


# ---------------------------------------------------------------------------
# memory_facts — conversation fact extraction + follow-up scheduling (T030)
# ---------------------------------------------------------------------------


def insert_fact(
    *,
    person_name: str,
    fact_text: str,
    category: str = "general",
    source_conv_id: str | None = None,
    follow_up_date: str | None = None,
) -> int:
    """Insert a memory fact. Returns the new row id."""
    ts = now_iso()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO memory_facts
                (person_name, fact_text, category, source_conv_id, extracted_at, follow_up_date, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (person_name, fact_text, category, source_conv_id, ts, follow_up_date),
        )
    return int(cur.lastrowid)


def get_facts_for_person(
    person_name: str,
    limit: int = 10,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """Return most recent facts for a person."""
    query = """
        SELECT id, person_name, fact_text, category, source_conv_id,
               extracted_at, follow_up_date, followed_up_at, active
        FROM memory_facts
        WHERE person_name = ?
    """
    params: list[Any] = [person_name]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY extracted_at DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def mark_followed_up(fact_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE memory_facts SET followed_up_at = ? WHERE id = ?",
            (now_iso(), fact_id),
        )


def deactivate_fact(fact_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE memory_facts SET active = 0 WHERE id = ?",
            (fact_id,),
        )
