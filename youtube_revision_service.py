"""Opt-in YouTube audio re-transcription with persistent SQLite caching."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from media_service import transcribe_media, whisper_available
from storage import connect

REVISION_VERSION = "whisper-word-v1"


def _ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_transcript_revisions (
            video_id TEXT NOT NULL,
            revision_version TEXT NOT NULL,
            transcript_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (video_id, revision_version)
        )
    """)


def get_revision(video_id: str):
    with connect() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT transcript_json FROM youtube_transcript_revisions WHERE video_id=? AND revision_version=?",
            (video_id, REVISION_VERSION),
        ).fetchone()
    return json.loads(row["transcript_json"]) if row else None


def revise_youtube(video_id: str):
    cached = get_revision(video_id)
    if cached is not None:
        return cached, True
    if not whisper_available():
        raise RuntimeError("Whisper 未安装，请先运行 setup_whisper_windows.bat。")
    with tempfile.TemporaryDirectory(prefix="media-dictation-yt-") as directory:
        output = str(Path(directory) / "audio.%(ext)s")
        url = "https://www.youtube.com/watch?v=" + video_id
        try:
            subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--no-playlist",
                 "--extract-audio", "--output", output, url],
                check=True, capture_output=True, text=True, timeout=600,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("下载 YouTube 音频失败，请确认已安装 yt-dlp 且视频可访问。") from exc
        candidates = [p for p in Path(directory).glob("audio.*") if p.is_file()]
        if not candidates:
            raise RuntimeError("未找到下载后的音频文件。")
        result = transcribe_media(candidates[0])
    payload = {
        "items": result["items"],
        "language": result.get("language", "en"),
        "duration": result.get("duration", 0),
        "is_generated": True,
        "segmentation_version": REVISION_VERSION,
        "revision": True,
    }
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT OR IGNORE INTO youtube_transcript_revisions "
            "(video_id, revision_version, transcript_json) VALUES (?, ?, ?)",
            (video_id, REVISION_VERSION, json.dumps(payload, ensure_ascii=False)),
        )
    return get_revision(video_id) or payload, False
