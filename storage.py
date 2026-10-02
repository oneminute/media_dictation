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


def _summary_for_where(where_sql: str = "", params: tuple = ()) -> dict[str, Any]:
    session_where = f"WHERE {where_sql}" if where_sql else ""
    attempt_join_where = f"AND {where_sql.replace('started_at', 'ps.started_at')}" if where_sql else ""

    with connect() as conn:
        summary = conn.execute(
            f"""
            SELECT
                COUNT(*) AS sessions,
                COALESCE(SUM(completed_sentences), 0) AS completed_sentences,
                COALESCE(SUM(total_items), 0) AS total_items
            FROM practice_sessions
            {session_where}
            """,
            params,
        ).fetchone()

        attempts = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN a.event_type != 'correct' THEN 1 ELSE 0 END) AS errors,
                COUNT(*) AS checks
            FROM attempts a
            JOIN practice_sessions ps ON ps.id = a.session_id
            WHERE 1=1
            {attempt_join_where}
            """,
            params,
        ).fetchone()

        first_pass = conn.execute(
            f"""
            WITH first_events AS (
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
                WHERE 1=1
                {attempt_join_where}
            )
            SELECT
                COUNT(*) AS attempted_sentences,
                SUM(CASE WHEN event_type = 'correct' THEN 1 ELSE 0 END)
                    AS first_pass_correct
            FROM first_events
            WHERE rn = 1
            """,
            params,
        ).fetchone()

    attempted = int(first_pass["attempted_sentences"] or 0)
    first_correct = int(first_pass["first_pass_correct"] or 0)
    completed = int(summary["completed_sentences"] or 0)
    errors = int(attempts["errors"] or 0)

    return {
        "sessions": int(summary["sessions"] or 0),
        "completed_sentences": completed,
        "total_items": int(summary["total_items"] or 0),
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
    score = round(
        max(
            0.0,
            min(
                100.0,
                float(accuracy) - min(30.0, errors_per * 7.5),
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
            "这是基于当前练习的首遍正确率和纠错次数得到的内部听写表现指标，"
            "不等同于 CEFR 等标准化英语等级。"
        ),
    }


def get_session_history(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                ps.id,
                ps.video_id,
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
            GROUP BY ps.id
            ORDER BY ps.updated_at DESC, ps.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for row in rows:
        total = int(row["total_items"] or 0)
        completed = int(row["completed_sentences"] or 0)
        result.append(
            {
                "id": int(row["id"]),
                "video_id": row["video_id"],
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


def get_session_detail(session_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM practice_sessions
            WHERE id = ?
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
        "video_id": row["video_id"],
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
    }


def get_learning_report() -> dict[str, Any]:
    overall = _summary_for_where()
    today = _summary_for_where("date(started_at, 'localtime') = date('now', 'localtime')")

    with connect() as conn:
        top_errors = conn.execute(
            """
            SELECT
                LOWER(COALESCE(NULLIF(correct_word, ''), wrong_word)) AS word,
                COUNT(*) AS count
            FROM attempts
            WHERE event_type != 'correct'
              AND COALESCE(NULLIF(correct_word, ''), wrong_word) IS NOT NULL
            GROUP BY LOWER(COALESCE(NULLIF(correct_word, ''), wrong_word))
            ORDER BY count DESC, word
            LIMIT 12
            """
        ).fetchall()

        today_top_errors = conn.execute(
            """
            SELECT
                LOWER(COALESCE(NULLIF(a.correct_word, ''), a.wrong_word)) AS word,
                COUNT(*) AS count
            FROM attempts a
            WHERE a.event_type != 'correct'
              AND COALESCE(NULLIF(a.correct_word, ''), a.wrong_word) IS NOT NULL
              AND date(a.created_at, 'localtime') = date('now', 'localtime')
            GROUP BY LOWER(COALESCE(NULLIF(a.correct_word, ''), a.wrong_word))
            ORDER BY count DESC, word
            LIMIT 8
            """
        ).fetchall()

    return {
        "overall": overall,
        "today": today,
        "assessment": _performance_assessment(overall),
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
