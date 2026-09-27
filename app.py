from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

from flask import Flask, jsonify, request, send_from_directory
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__, static_folder="static")


def extract_video_id(value: str) -> str:
    value = (value or "").strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", value):
        return value

    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()

        if host.endswith("youtu.be"):
            return parsed.path.strip("/").split("/")[0]

        if "youtube.com" in host:
            query = parse_qs(parsed.query)
            if query.get("v"):
                return query["v"][0]

            match = re.search(r"/(?:shorts|embed)/([^/?]+)", parsed.path)
            if match:
                return match.group(1)
    except Exception:
        pass

    match = re.search(
        r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{6,})",
        value,
    )
    return match.group(1) if match else ""


def snippet_to_dict(snippet) -> dict:
    if isinstance(snippet, dict):
        text = snippet.get("text", "")
        start = snippet.get("start", 0)
        duration = snippet.get("duration", 0)
    else:
        text = getattr(snippet, "text", "")
        start = getattr(snippet, "start", 0)
        duration = getattr(snippet, "duration", 0)

    return {
        "text": clean_caption_text(str(text)),
        "start": float(start or 0),
        "duration": max(0.0, float(duration or 0)),
    }


def clean_caption_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_non_speech_caption(text: str) -> bool:
    lowered = text.lower().strip()
    return bool(
        re.fullmatch(
            r"[\[(](?:music|applause|laughter|laughing|cheering|inaudible|"
            r"foreign language|silence|sound effects?)[^\])]*[\])]",
            lowered,
        )
    )


def merge_caption_fragments(snippets: list[dict]) -> list[dict]:
    """Merge small caption fragments into practical sentence-sized units."""

    clean = [
        item
        for item in snippets
        if item["text"] and not is_non_speech_caption(item["text"])
    ]
    if not clean:
        return []

    sentences: list[dict] = []
    buffer: list[str] = []
    start: float | None = None
    end = 0.0
    previous_end: float | None = None

    def flush() -> None:
        nonlocal buffer, start, end
        if not buffer or start is None:
            return

        text = re.sub(r"\s+", " ", " ".join(buffer)).strip()
        if text:
            sentences.append(
                {
                    "text": text,
                    "start": round(start, 3),
                    "end": round(max(end, start + 0.25), 3),
                }
            )

        buffer = []
        start = None
        end = 0.0

    for item in clean:
        text = item["text"]
        item_start = item["start"]
        item_end = item_start + max(item["duration"], 0.25)

        gap = 0.0 if previous_end is None else max(0.0, item_start - previous_end)
        if buffer and gap > 1.4:
            flush()

        if start is None:
            start = item_start

        buffer.append(text)
        end = max(end, item_end)
        previous_end = item_end

        combined = " ".join(buffer)
        elapsed = end - (start or 0.0)
        word_count = len(re.findall(r"\b\w+[’']?\w*\b", combined))

        has_sentence_end = bool(re.search(r'[.!?…]["\'’”)]*$', text))
        is_long_enough = elapsed >= 11.0 or word_count >= 26

        if has_sentence_end or is_long_enough:
            flush()

    flush()

    # Caption durations sometimes overlap the next sentence. Never play through
    # the next sentence's start.
    for index in range(len(sentences) - 1):
        next_start = sentences[index + 1]["start"]
        if sentences[index]["end"] > next_start:
            sentences[index]["end"] = max(
                sentences[index]["start"] + 0.25,
                next_start,
            )

    for sentence in sentences:
        sentence["duration"] = round(
            max(0.25, sentence["end"] - sentence["start"]),
            3,
        )

    return sentences


def fetch_best_transcript(video_id: str):
    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    selected = None

    try:
        selected = transcript_list.find_manually_created_transcript(
            ["en", "en-US", "en-GB"]
        )
    except Exception:
        pass

    if selected is None:
        try:
            selected = transcript_list.find_transcript(["en", "en-US", "en-GB"])
        except Exception:
            pass

    if selected is None:
        for transcript in transcript_list:
            selected = transcript
            break

    if selected is None:
        raise RuntimeError("No transcript is available for this video.")

    fetched = selected.fetch()
    snippets = [snippet_to_dict(item) for item in fetched]

    return {
        "language": getattr(selected, "language", ""),
        "language_code": getattr(selected, "language_code", ""),
        "is_generated": bool(getattr(selected, "is_generated", False)),
        "items": merge_caption_fragments(snippets),
    }


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/transcript")
def transcript():
    value = request.args.get("url", "")
    video_id = extract_video_id(value)

    if not video_id:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "无法识别 YouTube 链接或 Video ID。",
                }
            ),
            400,
        )

    try:
        result = fetch_best_transcript(video_id)
        if not result["items"]:
            raise RuntimeError("The transcript contains no usable spoken captions.")

        return jsonify(
            {
                "ok": True,
                "video_id": video_id,
                **result,
            }
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": (
                        "无法取得字幕。该视频可能没有可用字幕，字幕可能受限制，"
                        "或者 YouTube 暂时阻止了字幕请求。\n\n"
                        f"{exc}"
                    ),
                }
            ),
            500,
        )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
