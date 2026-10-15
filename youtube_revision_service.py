"""Opt-in YouTube audio re-transcription with persistent SQLite caching."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
import subprocess
import sys
import tempfile
from pathlib import Path

from media_service import transcribe_media, whisper_available
from storage import connect
from transcript_service import fetch_best_transcript, merge_caption_fragments

REVISION_VERSION = "caption-align-v2"


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


def _normalize(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower().replace("’", "'"))


def align_caption_to_whisper(caption_items, timed_words):
    """Preserve captions only when enough monotonic audio word anchors agree."""
    caption_tokens = []
    for item_index, item in enumerate(caption_items):
        for m in re.finditer(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*", item["text"]):
            caption_tokens.append((item_index, _normalize(m.group())))
    if not caption_tokens or not timed_words:
        return None
    audio_tokens = [_normalize(word["text"]) for word in timed_words]
    matcher = SequenceMatcher(None, [t for _, t in caption_tokens], audio_tokens, autojunk=False)
    matched = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            matched[block.a + offset] = block.b + offset
    if len(matched) / len(caption_tokens) < 0.80:
        return None
    positions = {}
    for i, (segment, _) in enumerate(caption_tokens):
        positions.setdefault(segment, []).append(i)
    units = []
    for segment, item in enumerate(caption_items):
        positions_here = positions.get(segment, [])
        anchors = [matched[i] for i in positions_here if i in matched]
        if not positions_here or len(anchors) / len(positions_here) < 0.70:
            return None
        if not any(i in matched for i in positions_here[:2]):
            return None
        if not any(i in matched for i in positions_here[-2:]):
            return None
        start = float(timed_words[min(anchors)]["start"])
        end = float(timed_words[max(anchors)]["end"])
        if end <= start or end - start > 45:
            return None
        units.append({"text": item["text"], "start": start, "end": end})
    if any(units[i]["start"] < units[i - 1]["start"] for i in range(1, len(units))):
        return None
    return merge_caption_fragments(units)


def revise_youtube(video_id: str, progress_callback=None):
    def report(p, stage, detail):
        if progress_callback:
            progress_callback(p, stage, detail)
    cached = get_revision(video_id)
    if cached is not None:
        return cached, True
    if not whisper_available():
        raise RuntimeError("Whisper 未安装，请先运行 setup_whisper_windows.bat。")
    report(3, 'downloading', '正在下载视频音频')
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
        report(15, 'loading_model', '正在加载 Whisper 模型')
        result = transcribe_media(candidates[0], include_words=True, progress_callback=lambda p, stage, detail: report(15 + int(p * 0.75), stage, detail))
    report(91, 'aligning', '正在重新对齐字幕')
    aligned_items = None
    caption_source = None
    try:
        caption_source = fetch_best_transcript(video_id)
        aligned_items = align_caption_to_whisper(
            caption_source["items"], result.get("words", [])
        )
    except Exception:
        pass

    payload = {
        "items": aligned_items or result["items"],
        "alignment_method": "youtube-caption+whisper" if aligned_items else "whisper-only",
        "alignment_fallback": aligned_items is None,
        "language": result.get("language", "en"),
        "duration": result.get("duration", 0),
        "is_generated": bool(caption_source.get("is_generated", True)) if aligned_items else True,
        "segmentation_version": REVISION_VERSION,
        "revision": True,
    }
    report(97, 'saving', '正在保存数据库')
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT OR IGNORE INTO youtube_transcript_revisions "
            "(video_id, revision_version, transcript_json) VALUES (?, ?, ?)",
            (video_id, REVISION_VERSION, json.dumps(payload, ensure_ascii=False)),
        )
    return get_revision(video_id) or payload, False
