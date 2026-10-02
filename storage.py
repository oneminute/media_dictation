from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


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
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
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

            CREATE TABLE IF NOT EXISTS translations (
                source_text TEXT PRIMARY KEY,
                translation TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def create_session(
    *,
    video_id: str,
    source_url: str,
    language: str,
    is_generated: bool,
    total_items: int,
) -> int:
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO practice_sessions (
                video_id,
                source_url,
                language,
                is_generated,
                total_items
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                video_id,
                source_url,
                language,
                1 if is_generated else 0,
                max(0, int(total_items)),
            ),
        )
        return int(cursor.lastrowid)


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
                SET
                    last_sentence_index = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    max(0, int(sentence_index)),
                    int(session_id),
                ),
            )


def get_translation(source_text: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT translation, model
            FROM translations
            WHERE source_text = ?
            """,
            (source_text,),
        ).fetchone()

    if row is None:
        return None

    return {
        "translation": row["translation"],
        "model": row["model"],
    }


def save_translation(
    *,
    source_text: str,
    translation: str,
    model: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO translations (
                source_text,
                translation,
                model
            )
            VALUES (?, ?, ?)
            ON CONFLICT(source_text) DO UPDATE SET
                translation = excluded.translation,
                model = excluded.model,
                updated_at = CURRENT_TIMESTAMP
            """,
            (source_text, translation, model),
        )


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
            """
            SELECT COUNT(*) AS error_count
            FROM attempts
            WHERE event_type != 'correct'
            """
        ).fetchone()

        translations = conn.execute(
            """
            SELECT COUNT(*) AS translation_count
            FROM translations
            """
        ).fetchone()

    return {
        "sessions": int(summary["sessions"]),
        "completed_sentences": int(summary["completed_sentences"]),
        "errors": int(errors["error_count"]),
        "translations": int(translations["translation_count"]),
    }
