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
from semantic_segmentation import segment_timed_words, SEMANTIC_VERSION
from transcript_service import merge_caption_fragments

REVISION_VERSION = SEMANTIC_VERSION
AUDIO_SOURCE_VERSION = "whisper-words-v1"


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


def get_revision(video_id: str, *, require_current: bool = False):
    with connect() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT transcript_json FROM youtube_transcript_revisions WHERE video_id=? AND revision_version=?",
            (video_id, REVISION_VERSION),
        ).fetchone()
        if row is None and not require_current:
            row = conn.execute(
                "SELECT transcript_json FROM youtube_transcript_revisions WHERE video_id=? "
                "AND revision_version<>? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (video_id, AUDIO_SOURCE_VERSION),
            ).fetchone()
            if row:
                payload = json.loads(row["transcript_json"])
                payload["revision_outdated"] = True
                return payload
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


def revise_youtube(video_id: str, progress_callback=None, provider_override=None, *, force=False):
    def report(p, stage, detail):
        if progress_callback:
            progress_callback(p, stage, detail)
    cached = get_revision(video_id, require_current=True)
    if cached is not None and not force:
        return cached, True
    with connect() as conn:
        _ensure_table(conn)
        source = conn.execute(
            "SELECT transcript_json FROM youtube_transcript_revisions "
            "WHERE video_id=? AND revision_version=?", (video_id, AUDIO_SOURCE_VERSION),
        ).fetchone()
    if source and not force:
        result = json.loads(source["transcript_json"])
        report(90, 'audio_cached', '已读取逐词转写缓存，无需重复 Whisper')
    else:
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
        # Save the expensive transcription before calling the LLM. A failed
        # semantic request can be retried without re-downloading/transcribing.
        with connect() as conn:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO youtube_transcript_revisions "
                "(video_id, revision_version, transcript_json) VALUES (?, ?, ?) "
                "ON CONFLICT(video_id, revision_version) DO UPDATE SET "
                "transcript_json=excluded.transcript_json, created_at=CURRENT_TIMESTAMP",
                (video_id, AUDIO_SOURCE_VERSION, json.dumps(result, ensure_ascii=False)),
            )
    report(91, 'semantic_segmenting', '正在根据上下文划分逻辑意群')
    timed_words = result.get("words", [])
    semantic_items, models = segment_timed_words(
        timed_words,
        provider_override=provider_override,
        progress_callback=lambda fraction: report(
            91 + int(fraction * 5), 'semantic_segmenting',
            f'逻辑意群分段 {fraction * 100:.0f}%'),
    )

    payload = {
        "items": semantic_items,
        "words": timed_words,
        "segmentation_method": "semantic",
        "segmentation_unit": "thought_group",
        "segmentation_models": models,
        "alignment_method": "whisper-word-timestamps",
        "alignment_fallback": False,
        "language": result.get("language", "en"),
        "duration": result.get("duration", 0),
        "is_generated": True,
        "segmentation_version": REVISION_VERSION,
        "revision": True,
    }
    report(97, 'saving', '正在保存数据库')
    with connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO youtube_transcript_revisions "
            "(video_id, revision_version, transcript_json) VALUES (?, ?, ?) "
            "ON CONFLICT(video_id, revision_version) DO UPDATE SET "
            "transcript_json=excluded.transcript_json, created_at=CURRENT_TIMESTAMP",
            (video_id, REVISION_VERSION, json.dumps(payload, ensure_ascii=False)),
        )
    return get_revision(video_id) or payload, False
