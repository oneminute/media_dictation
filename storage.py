from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 6
DEFAULT_LEARNER_NAME = "Default"


def database_path() -> Path:
    raw = os.getenv("MEDIA_DICTATION_DB", "data/media_dictation.db").strip()
    path = Path(raw or "data/media_dictation.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(database_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS learners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS media_sources (
                id TEXT PRIMARY KEY,
                learner_id INTEGER,
                original_name TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(learner_id)
                    REFERENCES learners(id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS practice_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                language TEXT,
                is_generated INTEGER NOT NULL DEFAULT 0,
                total_items INTEGER NOT NULL DEFAULT 0,
                last_sentence_index INTEGER NOT NULL DEFAULT 0,
                completed_sentences INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_video
                ON practice_sessions(video_id);

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sentence_index INTEGER NOT NULL,
                sentence_text TEXT NOT NULL,
                answer_before TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                wrong_word TEXT,
                correct_word TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id)
                    REFERENCES practice_sessions(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_attempts_session_sentence
                ON attempts(session_id, sentence_index);

            CREATE INDEX IF NOT EXISTS idx_attempts_correct_word
                ON attempts(correct_word);

            CREATE TABLE IF NOT EXISTS practice_items (
                session_id INTEGER NOT NULL,
                sentence_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                duration REAL NOT NULL,
                PRIMARY KEY(session_id, sentence_index),
                FOREIGN KEY(session_id)
                    REFERENCES practice_sessions(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS practice_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                sentence_index INTEGER,
                event_type TEXT NOT NULL,
                value_ms INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id)
                    REFERENCES practice_sessions(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_practice_events_session
                ON practice_events(session_id, sentence_index);

            CREATE INDEX IF NOT EXISTS idx_practice_events_created
                ON practice_events(created_at);

            CREATE TABLE IF NOT EXISTS sentence_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learner_id INTEGER NOT NULL,
                original_session_id INTEGER NOT NULL,
                sentence_index INTEGER NOT NULL,
                sentence_text TEXT NOT NULL,
                answer_before TEXT NOT NULL DEFAULT '',
                is_correct INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(learner_id)
                    REFERENCES learners(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(original_session_id)
                    REFERENCES practice_sessions(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sentence_reviews_learner
                ON sentence_reviews(learner_id, created_at);

            CREATE TABLE IF NOT EXISTS translations (
                source_text TEXT PRIMARY KEY,
                translation TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS translation_cache_v2 (
                source_text TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                translation TEXT NOT NULL,
                service_tier TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(source_text, provider, model, prompt_version)
            );

            CREATE TABLE IF NOT EXISTS word_translations (
                normalized_word TEXT NOT NULL,
                context_sentence TEXT NOT NULL,
                display_word TEXT NOT NULL,
                translation TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (normalized_word, context_sentence)
            );

            CREATE TABLE IF NOT EXISTS word_translation_cache_v2 (
                normalized_word TEXT NOT NULL,
                context_sentence TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                display_word TEXT NOT NULL,
                translation TEXT NOT NULL,
                service_tier TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (
                    normalized_word,
                    context_sentence,
                    provider,
                    model,
                    prompt_version
                )
            );

            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_word TEXT NOT NULL UNIQUE,
                display_word TEXT NOT NULL,
                translation TEXT NOT NULL,
                context_sentence TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source_url TEXT,
                added_count INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS vocabulary_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learner_id INTEGER NOT NULL,
                normalized_word TEXT NOT NULL,
                display_word TEXT NOT NULL,
                meaning TEXT NOT NULL,
                review_stage INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                due_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(learner_id, normalized_word, meaning),
                FOREIGN KEY(learner_id)
                    REFERENCES learners(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_vocab_due
                ON vocabulary_entries(learner_id, due_at);

            CREATE TABLE IF NOT EXISTS vocabulary_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                context_sentence TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source_url TEXT,
                session_id INTEGER,
                sentence_index INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entry_id, context_sentence, video_id),
                FOREIGN KEY(entry_id)
                    REFERENCES vocabulary_entries(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(session_id)
                    REFERENCES practice_sessions(id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_vocabulary_updated
                ON vocabulary(updated_at DESC);
            """
        )

        default_row = conn.execute(
            "SELECT id FROM learners WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if default_row is None:
            existing = conn.execute(
                "SELECT id FROM learners WHERE name = ?",
                (DEFAULT_LEARNER_NAME,),
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    "INSERT INTO learners (name, is_default) VALUES (?, 1)",
                    (DEFAULT_LEARNER_NAME,),
                )
                default_id = int(cursor.lastrowid)
            else:
                default_id = int(existing["id"])
                conn.execute(
                    "UPDATE learners SET is_default = 1 WHERE id = ?",
                    (default_id,),
                )
        else:
            default_id = int(default_row["id"])

        _add_column_if_missing(conn, "practice_sessions", "learner_id", "INTEGER")
        _add_column_if_missing(conn, "practice_sessions", "video_title", "TEXT")
        _add_column_if_missing(conn, "practice_sessions", "segmentation_version", "TEXT")
        _add_column_if_missing(
            conn,
            "practice_sessions",
            "source_type",
            "TEXT NOT NULL DEFAULT 'youtube'",
        )
        _add_column_if_missing(conn, "practice_sessions", "media_id", "TEXT")

        conn.execute(
            """
            UPDATE practice_sessions
            SET source_type = 'youtube'
            WHERE source_type IS NULL OR source_type = ''
            """
        )

        conn.execute(
            "UPDATE practice_sessions SET learner_id = ? WHERE learner_id IS NULL",
            (default_id,),
        )

        # One-time best-effort migration of the old flat vocabulary table into
        # the learner-aware, multi-meaning structure.
        legacy_vocab = conn.execute(
            """
            SELECT
                normalized_word,
                display_word,
                translation,
                context_sentence,
                video_id,
                source_url,
                added_at,
                updated_at
            FROM vocabulary
            """
        ).fetchall()

        for row in legacy_vocab:
            conn.execute(
                """
                INSERT INTO vocabulary_entries (
                    learner_id,
                    normalized_word,
                    display_word,
                    meaning,
                    due_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(learner_id, normalized_word, meaning) DO NOTHING
                """,
                (
                    default_id,
                    row["normalized_word"],
                    row["display_word"],
                    row["translation"],
                    row["added_at"],
                    row["updated_at"],
                ),
            )
            entry = conn.execute(
                """
                SELECT id
                FROM vocabulary_entries
                WHERE learner_id = ?
                  AND normalized_word = ?
                  AND meaning = ?
                """,
                (
                    default_id,
                    row["normalized_word"],
                    row["translation"],
                ),
            ).fetchone()
            if entry is not None and row["context_sentence"]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO vocabulary_occurrences (
                        entry_id,
                        context_sentence,
                        video_id,
                        source_url
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        int(entry["id"]),
                        row["context_sentence"],
                        row["video_id"],
                        row["source_url"],
                    ),
                )

        for version in range(1, SCHEMA_VERSION + 1):
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (version,),
            )


def get_schema_version() -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
    return int(row["version"] or 0)


def get_default_learner_id() -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM learners WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO learners(name, is_default) VALUES (?, 1)",
                (DEFAULT_LEARNER_NAME,),
            )
            return int(cursor.lastrowid)
        return int(row["id"])


def list_learners() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, is_default, created_at, updated_at
            FROM learners
            ORDER BY is_default DESC, id
            """
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def create_learner(name: str) -> dict[str, Any]:
    cleaned = " ".join(str(name or "").strip().split())
    if not cleaned:
        raise ValueError("Learner name is required.")
    if len(cleaned) > 80:
        raise ValueError("Learner name is too long.")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO learners(name)
            VALUES (?)
            ON CONFLICT(name) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """,
            (cleaned,),
        )
        row = conn.execute(
            """
            SELECT id, name, is_default, created_at, updated_at
            FROM learners
            WHERE name = ?
            """,
            (cleaned,),
        ).fetchone()

    return {
        "id": int(row["id"]),
        "name": row["name"],
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _coerce_learner_id(learner_id: int | None) -> int:
    if learner_id is None:
        return get_default_learner_id()
    try:
        value = int(learner_id)
    except (TypeError, ValueError):
        return get_default_learner_id()

    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM learners WHERE id = ?",
            (value,),
        ).fetchone()
    return value if exists is not None else get_default_learner_id()


def save_media_source(
    *,
    media_id: str,
    original_name: str,
    stored_filename: str,
    mime_type: str,
    size_bytes: int,
    title: str,
    learner_id: int | None = None,
) -> dict[str, Any]:
    learner_id = _coerce_learner_id(learner_id)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO media_sources (
                id,
                learner_id,
                original_name,
                stored_filename,
                mime_type,
                size_bytes,
                title
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                learner_id,
                original_name,
                stored_filename,
                mime_type or "",
                max(0, int(size_bytes or 0)),
                title or "",
            ),
        )
    return get_media_source(media_id) or {}


def get_media_source(media_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                learner_id,
                original_name,
                stored_filename,
                mime_type,
                size_bytes,
                title,
                created_at
            FROM media_sources
            WHERE id = ?
            """,
            (str(media_id),),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "learner_id": (
            int(row["learner_id"])
            if row["learner_id"] is not None
            else None
        ),
        "original_name": row["original_name"],
        "stored_filename": row["stored_filename"],
        "mime_type": row["mime_type"],
        "size_bytes": int(row["size_bytes"] or 0),
        "title": row["title"],
        "created_at": row["created_at"],
    }


def create_session(
    *,
    video_id: str,
    source_url: str,
    language: str,
    is_generated: bool,
    total_items: int,
    learner_id: int | None = None,
    video_title: str = "",
    items: Iterable[dict[str, Any]] | None = None,
    segmentation_version: str = "v2",
    source_type: str = "youtube",
    media_id: str | None = None,
) -> int:
    learner_id = _coerce_learner_id(learner_id)
    item_list = list(items or [])
    effective_total = len(item_list) if item_list else max(0, int(total_items))

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO practice_sessions (
                video_id,
                source_url,
                language,
                is_generated,
                total_items,
                learner_id,
                video_title,
                segmentation_version,
                source_type,
                media_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                source_url,
                language,
                1 if is_generated else 0,
                effective_total,
                learner_id,
                video_title,
                segmentation_version,
                source_type or "youtube",
                media_id,
            ),
        )
        session_id = int(cursor.lastrowid)

        for index, item in enumerate(item_list):
            start = float(item.get("start", 0) or 0)
            end = float(item.get("end", start + 0.25) or (start + 0.25))
            duration = float(
                item.get("duration", max(0.25, end - start))
                or max(0.25, end - start)
            )
            conn.execute(
                """
                INSERT INTO practice_items (
                    session_id,
                    sentence_index,
                    text,
                    start,
                    end,
                    duration
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    index,
                    str(item.get("text", "")),
                    start,
                    end,
                    duration,
                ),
            )

    return session_id


def record_attempt(
    *,
    session_id: int,
    sentence_index: int,
    sentence_text: str,
    answer_before: str,
    event_type: str,
    wrong_word: str | None = None,
    correct_word: str | None = None,
) -> None:
    allowed = {"replace", "missing", "extra", "correct"}
    if event_type not in allowed:
        raise ValueError(f"Unsupported event_type: {event_type}")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO attempts (
                session_id,
                sentence_index,
                sentence_text,
                answer_before,
                event_type,
                wrong_word,
                correct_word
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(session_id),
                max(0, int(sentence_index)),
                sentence_text,
                answer_before,
                event_type,
                wrong_word,
                correct_word,
            ),
        )

        if event_type == "correct":
            conn.execute(
                """
                UPDATE practice_sessions
                SET
                    last_sentence_index = ?,
                    completed_sentences = (
                        SELECT COUNT(DISTINCT sentence_index)
                        FROM attempts
                        WHERE session_id = ?
                          AND event_type = 'correct'
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    max(0, int(sentence_index)),
                    int(session_id),
                    int(session_id),
                ),
            )
        else:
            conn.execute(
                """
                UPDATE practice_sessions
                SET last_sentence_index = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (max(0, int(sentence_index)), int(session_id)),
            )


def record_practice_event(
    *,
    session_id: int,
    sentence_index: int | None,
    event_type: str,
    value_ms: int = 0,
    detail: str = "",
) -> None:
    allowed = {
        "play",
        "reveal",
        "translation",
        "word_lookup",
        "next",
        "prev",
        "time_spent",
        "session_open",
    }
    if event_type not in allowed:
        raise ValueError(f"Unsupported practice event: {event_type}")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO practice_events (
                session_id,
                sentence_index,
                event_type,
                value_ms,
                detail
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(session_id),
                None if sentence_index is None else max(0, int(sentence_index)),
                event_type,
                max(0, int(value_ms or 0)),
                str(detail or "")[:500],
            ),
        )
        conn.execute(
            """
            UPDATE practice_sessions
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (int(session_id),),
        )


def _practice_items_for_session(
    conn: sqlite3.Connection,
    session_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sentence_index, text, start, end, duration
        FROM practice_items
        WHERE session_id = ?
        ORDER BY sentence_index
        """,
        (int(session_id),),
    ).fetchall()
    return [
        {
            "sentence_index": int(row["sentence_index"]),
            "text": row["text"],
            "start": float(row["start"]),
            "end": float(row["end"]),
            "duration": float(row["duration"]),
        }
        for row in rows
    ]


def get_session_detail(session_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT ps.*, l.name AS learner_name
            FROM practice_sessions ps
            LEFT JOIN learners l ON l.id = ps.learner_id
            WHERE ps.id = ?
            """,
            (int(session_id),),
        ).fetchone()
        if row is None:
            return None

        completed_rows = conn.execute(
            """
            SELECT DISTINCT sentence_index
            FROM attempts
            WHERE session_id = ?
              AND event_type = 'correct'
            ORDER BY sentence_index
            """,
            (int(session_id),),
        ).fetchall()
        items = _practice_items_for_session(conn, int(session_id))

    completed_indices = {int(item["sentence_index"]) for item in completed_rows}
    total = int(row["total_items"] or 0)

    resume_index = 0
    if total > 0:
        resume_index = total - 1
        for candidate in range(total):
            if candidate not in completed_indices:
                resume_index = candidate
                break

    return {
        "id": int(row["id"]),
        "learner_id": int(row["learner_id"] or get_default_learner_id()),
        "learner_name": row["learner_name"] or DEFAULT_LEARNER_NAME,
        "video_id": row["video_id"],
        "video_title": row["video_title"] or "",
        "source_type": row["source_type"] or "youtube",
        "media_id": row["media_id"],
        "source_url": row["source_url"],
        "language": row["language"] or "",
        "is_generated": bool(row["is_generated"]),
        "total_items": total,
        "completed_sentences": int(row["completed_sentences"] or 0),
        "last_sentence_index": int(row["last_sentence_index"] or 0),
        "resume_index": resume_index,
        "completed": total > 0 and len(completed_indices) >= total,
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "segmentation_version": row["segmentation_version"] or "",
        "items": items,
    }


def get_session_history(
    limit: int = 50,
    learner_id: int | None = None,
) -> list[dict[str, Any]]:
    learner_id = _coerce_learner_id(learner_id)
    limit = max(1, min(int(limit), 200))

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                ps.id,
                ps.video_id,
                ps.video_title,
                ps.source_type,
                ps.media_id,
                ps.source_url,
                ps.language,
                ps.is_generated,
                ps.total_items,
                ps.last_sentence_index,
                ps.completed_sentences,
                ps.started_at,
                ps.updated_at,
                COALESCE(SUM(CASE WHEN a.event_type != 'correct' THEN 1 ELSE 0 END), 0)
                    AS error_count
            FROM practice_sessions ps
            LEFT JOIN attempts a ON a.session_id = ps.id
            WHERE COALESCE(ps.learner_id, ?) = ?
            GROUP BY ps.id
            ORDER BY ps.updated_at DESC, ps.id DESC
            LIMIT ?
            """,
            (learner_id, learner_id, limit),
        ).fetchall()

    result = []
    for row in rows:
        total = int(row["total_items"] or 0)
        completed = int(row["completed_sentences"] or 0)
        result.append(
            {
                "id": int(row["id"]),
                "video_id": row["video_id"],
                "video_title": row["video_title"] or "",
                "source_type": row["source_type"] or "youtube",
                "media_id": row["media_id"],
                "source_url": row["source_url"],
                "language": row["language"] or "",
                "is_generated": bool(row["is_generated"]),
                "total_items": total,
                "completed_sentences": completed,
                "last_sentence_index": int(row["last_sentence_index"] or 0),
                "error_count": int(row["error_count"] or 0),
                "completed": total > 0 and completed >= total,
                "progress_percent": (
                    round(completed * 100.0 / total, 1) if total else 0.0
                ),
                "started_at": row["started_at"],
                "updated_at": row["updated_at"],
            }
        )
    return result


def _window_clause(days: int | None, alias: str) -> tuple[str, tuple]:
    if days is None:
        return "", ()
    if days <= 1:
        return (
            f"AND date({alias}.created_at, 'localtime') = date('now', 'localtime')",
            (),
        )
    return (
        f"AND datetime({alias}.created_at, 'localtime') >= "
        "datetime('now', 'localtime', ?)",
        (f"-{days - 1} days",),
    )


def _window_summary(
    learner_id: int,
    days: int | None,
) -> dict[str, Any]:
    attempt_window, attempt_params = _window_clause(days, "a")
    event_window, event_params = _window_clause(days, "e")

    with connect() as conn:
        attempts = conn.execute(
            f"""
            SELECT
                COUNT(*) AS checks,
                SUM(CASE WHEN a.event_type != 'correct' THEN 1 ELSE 0 END) AS errors,
                COUNT(DISTINCT CASE
                    WHEN a.event_type = 'correct'
                    THEN a.session_id || ':' || a.sentence_index
                END) AS completed_sentences,
                COUNT(DISTINCT a.session_id) AS sessions
            FROM attempts a
            JOIN practice_sessions ps ON ps.id = a.session_id
            WHERE COALESCE(ps.learner_id, ?) = ?
            {attempt_window}
            """,
            (learner_id, learner_id, *attempt_params),
        ).fetchone()

        first_pass = conn.execute(
            f"""
            WITH ranked AS (
                SELECT
                    a.session_id,
                    a.sentence_index,
                    a.event_type,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.session_id, a.sentence_index
                        ORDER BY a.id
                    ) AS rn
                FROM attempts a
                JOIN practice_sessions ps ON ps.id = a.session_id
                WHERE COALESCE(ps.learner_id, ?) = ?
                {attempt_window}
            )
            SELECT
                COUNT(*) AS attempted_sentences,
                SUM(CASE WHEN event_type = 'correct' THEN 1 ELSE 0 END)
                    AS first_pass_correct
            FROM ranked
            WHERE rn = 1
            """,
            (learner_id, learner_id, *attempt_params),
        ).fetchone()

        events = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN e.event_type = 'play' THEN 1 ELSE 0 END) AS plays,
                SUM(CASE WHEN e.event_type = 'reveal' THEN 1 ELSE 0 END) AS reveals,
                SUM(CASE WHEN e.event_type = 'translation' THEN 1 ELSE 0 END)
                    AS translations,
                SUM(CASE WHEN e.event_type = 'word_lookup' THEN 1 ELSE 0 END)
                    AS word_lookups,
                SUM(CASE WHEN e.event_type = 'time_spent' THEN e.value_ms ELSE 0 END)
                    AS time_spent_ms
            FROM practice_events e
            JOIN practice_sessions ps ON ps.id = e.session_id
            WHERE COALESCE(ps.learner_id, ?) = ?
            {event_window}
            """,
            (learner_id, learner_id, *event_params),
        ).fetchone()

    attempted = int(first_pass["attempted_sentences"] or 0)
    first_correct = int(first_pass["first_pass_correct"] or 0)
    completed = int(attempts["completed_sentences"] or 0)
    errors = int(attempts["errors"] or 0)
    plays = int(events["plays"] or 0)

    return {
        "sessions": int(attempts["sessions"] or 0),
        "completed_sentences": completed,
        "errors": errors,
        "checks": int(attempts["checks"] or 0),
        "attempted_sentences": attempted,
        "first_pass_correct": first_correct,
        "first_pass_accuracy": (
            round(first_correct * 100.0 / attempted, 1) if attempted else None
        ),
        "errors_per_completed_sentence": (
            round(errors / completed, 2) if completed else None
        ),
        "plays": plays,
        "replays_per_completed_sentence": (
            round(max(0, plays - completed) / completed, 2) if completed else None
        ),
        "reveals": int(events["reveals"] or 0),
        "translations_used": int(events["translations"] or 0),
        "word_lookups": int(events["word_lookups"] or 0),
        "time_spent_ms": int(events["time_spent_ms"] or 0),
        "time_spent_minutes": round(int(events["time_spent_ms"] or 0) / 60000, 1),
    }


def _performance_assessment(summary: dict[str, Any]) -> dict[str, Any]:
    attempted = int(summary.get("attempted_sentences") or 0)
    accuracy = summary.get("first_pass_accuracy")

    if attempted < 10 or accuracy is None:
        return {
            "label": "数据不足",
            "score": None,
            "confidence": "low",
            "note": "至少完成约 10 个听写句子后，评估才开始具有参考意义。",
        }

    errors_per = float(summary.get("errors_per_completed_sentence") or 0.0)
    replays = float(summary.get("replays_per_completed_sentence") or 0.0)
    reveal_penalty = min(
        10.0,
        float(summary.get("reveals") or 0) * 100.0 / max(1, attempted) * 0.15,
    )

    score = round(
        max(
            0.0,
            min(
                100.0,
                float(accuracy)
                - min(25.0, errors_per * 6.0)
                - min(15.0, replays * 4.0)
                - reveal_penalty,
            ),
        ),
        1,
    )

    if score >= 88:
        label = "听写表现很强"
    elif score >= 75:
        label = "听写表现较强"
    elif score >= 60:
        label = "听写表现中等"
    else:
        label = "当前材料需要强化"

    confidence = "high" if attempted >= 100 else "medium" if attempted >= 30 else "low"
    return {
        "label": label,
        "score": score,
        "confidence": confidence,
        "note": (
            "该指标综合首遍正确率、纠错、重复播放和查看原文行为，"
            "用于跟踪同一学习者的趋势，不等同于 CEFR。"
        ),
    }


def get_learning_report(
    learner_id: int | None = None,
) -> dict[str, Any]:
    learner_id = _coerce_learner_id(learner_id)
    today = _window_summary(learner_id, 1)
    seven_days = _window_summary(learner_id, 7)
    thirty_days = _window_summary(learner_id, 30)
    overall = _window_summary(learner_id, None)

    with connect() as conn:
        top_errors = conn.execute(
            """
            SELECT
                LOWER(COALESCE(NULLIF(a.correct_word, ''), a.wrong_word)) AS word,
                COUNT(*) AS count
            FROM attempts a
            JOIN practice_sessions ps ON ps.id = a.session_id
            WHERE a.event_type != 'correct'
              AND COALESCE(NULLIF(a.correct_word, ''), a.wrong_word) IS NOT NULL
              AND COALESCE(ps.learner_id, ?) = ?
            GROUP BY LOWER(COALESCE(NULLIF(a.correct_word, ''), a.wrong_word))
            ORDER BY count DESC, word
            LIMIT 12
            """,
            (learner_id, learner_id),
        ).fetchall()

        today_top_errors = conn.execute(
            """
            SELECT
                LOWER(COALESCE(NULLIF(a.correct_word, ''), a.wrong_word)) AS word,
                COUNT(*) AS count
            FROM attempts a
            JOIN practice_sessions ps ON ps.id = a.session_id
            WHERE a.event_type != 'correct'
              AND COALESCE(NULLIF(a.correct_word, ''), a.wrong_word) IS NOT NULL
              AND COALESCE(ps.learner_id, ?) = ?
              AND date(a.created_at, 'localtime') = date('now', 'localtime')
            GROUP BY LOWER(COALESCE(NULLIF(a.correct_word, ''), a.wrong_word))
            ORDER BY count DESC, word
            LIMIT 8
            """,
            (learner_id, learner_id),
        ).fetchall()

    return {
        "learner_id": learner_id,
        "today": today,
        "seven_days": seven_days,
        "thirty_days": thirty_days,
        "overall": overall,
        "assessment": _performance_assessment(thirty_days if thirty_days["attempted_sentences"] >= 10 else overall),
        "sentence_review": get_sentence_review_stats(learner_id, 30),
        "top_errors": [
            {"word": row["word"], "count": int(row["count"])}
            for row in top_errors
            if row["word"]
        ],
        "today_top_errors": [
            {"word": row["word"], "count": int(row["count"])}
            for row in today_top_errors
            if row["word"]
        ],
    }


def get_review_sentences(
    learner_id: int | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    learner_id = _coerce_learner_id(learner_id)
    limit = max(1, min(int(limit), 100))

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                a.session_id,
                a.sentence_index,
                COALESCE(pi.text, a.sentence_text) AS text,
                COALESCE(pi.start, 0) AS start,
                COALESCE(pi.end, 0) AS end,
                COALESCE(pi.duration, 0) AS duration,
                ps.video_id,
                ps.video_title,
                ps.source_type,
                ps.media_id,
                ps.source_url,
                COUNT(*) AS error_count,
                MAX(a.created_at) AS last_error_at
            FROM attempts a
            JOIN practice_sessions ps ON ps.id = a.session_id
            LEFT JOIN practice_items pi
              ON pi.session_id = a.session_id
             AND pi.sentence_index = a.sentence_index
            WHERE a.event_type != 'correct'
              AND COALESCE(ps.learner_id, ?) = ?
            GROUP BY
                a.session_id,
                a.sentence_index,
                text,
                start,
                end,
                duration,
                ps.video_id,
                ps.video_title,
                ps.source_type,
                ps.media_id,
                ps.source_url
            ORDER BY error_count DESC, last_error_at DESC
            LIMIT ?
            """,
            (learner_id, learner_id, limit),
        ).fetchall()

    return [
        {
            "session_id": int(row["session_id"]),
            "sentence_index": int(row["sentence_index"]),
            "text": row["text"],
            "start": float(row["start"] or 0),
            "end": float(row["end"] or 0),
            "duration": float(row["duration"] or 0),
            "video_id": row["video_id"],
            "video_title": row["video_title"] or "",
            "source_type": row["source_type"] or "youtube",
            "media_id": row["media_id"],
            "source_url": row["source_url"],
            "error_count": int(row["error_count"] or 0),
            "last_error_at": row["last_error_at"],
        }
        for row in rows
    ]


def record_sentence_review(
    *,
    learner_id: int | None,
    original_session_id: int,
    sentence_index: int,
    sentence_text: str,
    answer_before: str,
    is_correct: bool,
) -> None:
    learner_id = _coerce_learner_id(learner_id)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO sentence_reviews (
                learner_id,
                original_session_id,
                sentence_index,
                sentence_text,
                answer_before,
                is_correct
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                learner_id,
                int(original_session_id),
                max(0, int(sentence_index)),
                sentence_text,
                answer_before,
                1 if is_correct else 0,
            ),
        )


def get_sentence_review_stats(
    learner_id: int | None = None,
    days: int | None = 30,
) -> dict[str, Any]:
    learner_id = _coerce_learner_id(learner_id)
    params: list[Any] = [learner_id]
    window = ""
    if days is not None:
        if days <= 1:
            window = "AND date(created_at, 'localtime') = date('now', 'localtime')"
        else:
            window = (
                "AND datetime(created_at, 'localtime') >= "
                "datetime('now', 'localtime', ?)"
            )
            params.append(f"-{days - 1} days")

    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS attempts,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct
            FROM sentence_reviews
            WHERE learner_id = ?
            {window}
            """,
            tuple(params),
        ).fetchone()

    attempts = int(row["attempts"] or 0)
    correct = int(row["correct"] or 0)
    return {
        "attempts": attempts,
        "correct": correct,
        "accuracy": round(correct * 100.0 / attempts, 1) if attempts else None,
    }


def get_translation(
    source_text: str,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str = "sentence-v2",
) -> dict[str, Any] | None:
    with connect() as conn:
        if provider and model:
            row = conn.execute(
                """
                SELECT translation, model, provider, service_tier, prompt_version
                FROM translation_cache_v2
                WHERE source_text = ?
                  AND provider = ?
                  AND model = ?
                  AND prompt_version = ?
                """,
                (source_text, provider, model, prompt_version),
            ).fetchone()
            if row is not None:
                return dict(row)

        # Legacy compatibility only when no exact cache identity was requested.
        if not provider and not model:
            row = conn.execute(
                """
                SELECT translation, model
                FROM translations
                WHERE source_text = ?
                """,
                (source_text,),
            ).fetchone()
            if row is not None:
                return {
                    "translation": row["translation"],
                    "model": row["model"],
                    "provider": "legacy",
                    "service_tier": "",
                    "prompt_version": "legacy",
                }
    return None


def save_translation(
    *,
    source_text: str,
    translation: str,
    model: str,
    provider: str = "legacy",
    service_tier: str = "",
    prompt_version: str = "sentence-v2",
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO translation_cache_v2 (
                source_text,
                provider,
                model,
                prompt_version,
                translation,
                service_tier
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_text, provider, model, prompt_version) DO UPDATE SET
                translation = excluded.translation,
                service_tier = excluded.service_tier,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source_text,
                provider,
                model,
                prompt_version,
                translation,
                service_tier,
            ),
        )


def get_word_translation(
    normalized_word: str,
    context_sentence: str,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str = "word-v2",
) -> dict[str, Any] | None:
    with connect() as conn:
        if provider and model:
            row = conn.execute(
                """
                SELECT
                    display_word,
                    translation,
                    model,
                    provider,
                    service_tier,
                    prompt_version
                FROM word_translation_cache_v2
                WHERE normalized_word = ?
                  AND context_sentence = ?
                  AND provider = ?
                  AND model = ?
                  AND prompt_version = ?
                """,
                (
                    normalized_word,
                    context_sentence,
                    provider,
                    model,
                    prompt_version,
                ),
            ).fetchone()
            if row is not None:
                return dict(row)

        if not provider and not model:
            row = conn.execute(
                """
                SELECT display_word, translation, model
                FROM word_translations
                WHERE normalized_word = ?
                  AND context_sentence = ?
                """,
                (normalized_word, context_sentence),
            ).fetchone()
            if row is not None:
                return {
                    "word": row["display_word"],
                    "display_word": row["display_word"],
                    "translation": row["translation"],
                    "model": row["model"],
                    "provider": "legacy",
                    "service_tier": "",
                    "prompt_version": "legacy",
                }
    return None


def save_word_translation(
    *,
    normalized_word: str,
    display_word: str,
    context_sentence: str,
    translation: str,
    model: str,
    provider: str = "legacy",
    service_tier: str = "",
    prompt_version: str = "word-v2",
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO word_translation_cache_v2 (
                normalized_word,
                context_sentence,
                provider,
                model,
                prompt_version,
                display_word,
                translation,
                service_tier
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(
                normalized_word,
                context_sentence,
                provider,
                model,
                prompt_version
            ) DO UPDATE SET
                display_word = excluded.display_word,
                translation = excluded.translation,
                service_tier = excluded.service_tier,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                normalized_word,
                context_sentence,
                provider,
                model,
                prompt_version,
                display_word,
                translation,
                service_tier,
            ),
        )


def add_vocabulary_word(
    *,
    normalized_word: str,
    display_word: str,
    translation: str,
    context_sentence: str,
    video_id: str | None = None,
    source_url: str | None = None,
    learner_id: int | None = None,
    session_id: int | None = None,
    sentence_index: int | None = None,
) -> dict[str, Any]:
    learner_id = _coerce_learner_id(learner_id)

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO vocabulary_entries (
                learner_id,
                normalized_word,
                display_word,
                meaning
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(learner_id, normalized_word, meaning) DO UPDATE SET
                display_word = excluded.display_word,
                updated_at = CURRENT_TIMESTAMP
            """,
            (learner_id, normalized_word, display_word, translation),
        )
        row = conn.execute(
            """
            SELECT *
            FROM vocabulary_entries
            WHERE learner_id = ?
              AND normalized_word = ?
              AND meaning = ?
            """,
            (learner_id, normalized_word, translation),
        ).fetchone()
        entry_id = int(row["id"])

        conn.execute(
            """
            INSERT OR IGNORE INTO vocabulary_occurrences (
                entry_id,
                context_sentence,
                video_id,
                source_url,
                session_id,
                sentence_index
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                context_sentence,
                video_id,
                source_url,
                session_id,
                sentence_index,
            ),
        )

    return get_vocabulary_entry(entry_id) or {}


def get_vocabulary_entry(entry_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM vocabulary_entries
            WHERE id = ?
            """,
            (int(entry_id),),
        ).fetchone()
        if row is None:
            return None

        occurrences = conn.execute(
            """
            SELECT
                id,
                context_sentence,
                video_id,
                source_url,
                session_id,
                sentence_index,
                created_at
            FROM vocabulary_occurrences
            WHERE entry_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(entry_id),),
        ).fetchall()

    return {
        "id": int(row["id"]),
        "learner_id": int(row["learner_id"]),
        "word": row["display_word"],
        "normalized_word": row["normalized_word"],
        "translation": row["meaning"],
        "review_stage": int(row["review_stage"] or 0),
        "review_count": int(row["review_count"] or 0),
        "due_at": row["due_at"],
        "last_reviewed_at": row["last_reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "occurrences": [dict(item) for item in occurrences],
        "context_sentence": (
            occurrences[0]["context_sentence"] if occurrences else ""
        ),
        "added_count": len(occurrences),
    }


def get_vocabulary(
    limit: int = 200,
    learner_id: int | None = None,
    due_only: bool = False,
) -> list[dict[str, Any]]:
    learner_id = _coerce_learner_id(learner_id)
    limit = max(1, min(int(limit), 500))
    due_clause = "AND ve.due_at <= CURRENT_TIMESTAMP" if due_only else ""

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT ve.id
            FROM vocabulary_entries ve
            WHERE ve.learner_id = ?
            {due_clause}
            ORDER BY
                CASE WHEN ve.due_at <= CURRENT_TIMESTAMP THEN 0 ELSE 1 END,
                ve.due_at,
                ve.updated_at DESC
            LIMIT ?
            """,
            (learner_id, limit),
        ).fetchall()

    return [
        item
        for item in (get_vocabulary_entry(int(row["id"])) for row in rows)
        if item is not None
    ]


def review_vocabulary(
    entry_id: int,
    rating: str,
) -> dict[str, Any]:
    rating = str(rating or "").strip().lower()
    if rating not in {"again", "hard", "good", "easy"}:
        raise ValueError("rating must be again, hard, good, or easy")

    with connect() as conn:
        row = conn.execute(
            "SELECT review_stage FROM vocabulary_entries WHERE id = ?",
            (int(entry_id),),
        ).fetchone()
        if row is None:
            raise ValueError("Vocabulary entry not found.")

        stage = int(row["review_stage"] or 0)
        if rating == "again":
            next_stage = 0
            delay = "+10 minutes"
        elif rating == "hard":
            next_stage = max(1, stage)
            delay = "+1 day"
        elif rating == "good":
            next_stage = min(stage + 1, 8)
            intervals = [1, 3, 7, 14, 30, 60, 120, 240, 365]
            delay = f"+{intervals[next_stage]} days"
        else:
            next_stage = min(stage + 2, 8)
            intervals = [1, 3, 7, 14, 30, 60, 120, 240, 365]
            delay = f"+{intervals[next_stage]} days"

        conn.execute(
            """
            UPDATE vocabulary_entries
            SET
                review_stage = ?,
                review_count = review_count + 1,
                due_at = datetime('now', ?),
                last_reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (next_stage, delay, int(entry_id)),
        )

    return get_vocabulary_entry(int(entry_id)) or {}


def export_learner_data(
    learner_id: int | None = None,
) -> dict[str, Any]:
    learner_id = _coerce_learner_id(learner_id)

    with connect() as conn:
        learner = conn.execute(
            """
            SELECT id, name, created_at, updated_at
            FROM learners
            WHERE id = ?
            """,
            (learner_id,),
        ).fetchone()
        if learner is None:
            raise ValueError("Learner not found.")

        sessions = conn.execute(
            """
            SELECT
                id, video_id, video_title, source_type, media_id, source_url,
                language, is_generated,
                total_items, last_sentence_index, completed_sentences,
                segmentation_version, started_at, updated_at
            FROM practice_sessions
            WHERE COALESCE(learner_id, ?) = ?
            ORDER BY id
            """,
            (learner_id, learner_id),
        ).fetchall()

        attempts = conn.execute(
            """
            SELECT
                a.id, a.session_id, a.sentence_index, a.sentence_text,
                a.answer_before, a.event_type, a.wrong_word, a.correct_word,
                a.created_at
            FROM attempts a
            JOIN practice_sessions ps ON ps.id = a.session_id
            WHERE COALESCE(ps.learner_id, ?) = ?
            ORDER BY a.id
            """,
            (learner_id, learner_id),
        ).fetchall()

        events = conn.execute(
            """
            SELECT
                e.id, e.session_id, e.sentence_index, e.event_type,
                e.value_ms, e.detail, e.created_at
            FROM practice_events e
            JOIN practice_sessions ps ON ps.id = e.session_id
            WHERE COALESCE(ps.learner_id, ?) = ?
            ORDER BY e.id
            """,
            (learner_id, learner_id),
        ).fetchall()

        reviews = conn.execute(
            """
            SELECT
                id, original_session_id, sentence_index, sentence_text,
                answer_before, is_correct, created_at
            FROM sentence_reviews
            WHERE learner_id = ?
            ORDER BY id
            """,
            (learner_id,),
        ).fetchall()

        items = conn.execute(
            """
            SELECT
                pi.session_id, pi.sentence_index, pi.text, pi.start,
                pi.end, pi.duration
            FROM practice_items pi
            JOIN practice_sessions ps ON ps.id = pi.session_id
            WHERE COALESCE(ps.learner_id, ?) = ?
            ORDER BY pi.session_id, pi.sentence_index
            """,
            (learner_id, learner_id),
        ).fetchall()

        vocab_rows = conn.execute(
            """
            SELECT id
            FROM vocabulary_entries
            WHERE learner_id = ?
            ORDER BY id
            """,
            (learner_id,),
        ).fetchall()

    return {
        "export_version": 1,
        "schema_version": get_schema_version(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "learner": dict(learner),
        "report": get_learning_report(learner_id),
        "sessions": [dict(row) for row in sessions],
        "practice_items": [dict(row) for row in items],
        "attempts": [dict(row) for row in attempts],
        "practice_events": [dict(row) for row in events],
        "sentence_reviews": [
            {
                **dict(row),
                "is_correct": bool(row["is_correct"]),
            }
            for row in reviews
        ],
        "vocabulary": [
            item
            for item in (
                get_vocabulary_entry(int(row["id"]))
                for row in vocab_rows
            )
            if item is not None
        ],
    }


def get_stats() -> dict[str, Any]:
    with connect() as conn:
        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS sessions,
                COALESCE(SUM(completed_sentences), 0) AS completed_sentences
            FROM practice_sessions
            """
        ).fetchone()
        errors = conn.execute(
            "SELECT COUNT(*) AS error_count FROM attempts WHERE event_type != 'correct'"
        ).fetchone()
        translations = conn.execute(
            "SELECT COUNT(*) AS translation_count FROM translation_cache_v2"
        ).fetchone()
        learners = conn.execute(
            "SELECT COUNT(*) AS learner_count FROM learners"
        ).fetchone()

    return {
        "sessions": int(summary["sessions"] or 0),
        "completed_sentences": int(summary["completed_sentences"] or 0),
        "errors": int(errors["error_count"] or 0),
        "translations": int(translations["translation_count"] or 0),
        "learners": int(learners["learner_count"] or 0),
        "schema_version": get_schema_version(),
    }
