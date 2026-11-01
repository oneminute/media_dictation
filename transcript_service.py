from __future__ import annotations

import html
import os
import re
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import json

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig


SEGMENTATION_VERSION = "punctuation-v4"

NON_SPEECH_CUES = (
    "music", "applause", "laughter", "laughing", "cheering",
    "inaudible", "foreign language", "silence", "sound effect", "sound effects",
)

WORD_RE = re.compile(r"\b[A-Za-z0-9]+(?:[’'][A-Za-z0-9]+)*\b")
STRONG_END_RE = re.compile(r'[.!?…]["\'’”)]*$')


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
            match = re.search(r"/(?:shorts|embed|podcast)/([^/?]+)", parsed.path)
            if match:
                return match.group(1)
    except Exception:
        pass
    match = re.search(
        r"(?:v=|youtu\.be/|shorts/|embed/|podcast/)([A-Za-z0-9_-]{6,})",
        value,
    )
    return match.group(1) if match else ""


def fetch_video_title(video_id: str) -> str:
    url = (
        "https://www.youtube.com/oembed?format=json&url="
        f"https://www.youtube.com/watch?v={video_id}"
    )
    req = Request(url, headers={"User-Agent": "MediaDictation/1.0"}, method="GET")
    try:
        with urlopen(req, timeout=4.0) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data.get("title", "")).strip()[:300]
    except Exception:
        return ""


def build_youtube_api() -> tuple[YouTubeTranscriptApi, str]:
    username = os.getenv("YT_WEBSHARE_PROXY_USERNAME", "").strip()
    password = os.getenv("YT_WEBSHARE_PROXY_PASSWORD", "").strip()
    if username and password:
        locations = [
            code.strip().lower()
            for code in os.getenv("YT_WEBSHARE_PROXY_LOCATIONS", "us").split(",")
            if code.strip()
        ]
        return (
            YouTubeTranscriptApi(
                proxy_config=WebshareProxyConfig(
                    proxy_username=username,
                    proxy_password=password,
                    filter_ip_locations=locations or None,
                )
            ),
            "webshare",
        )

    http_proxy = os.getenv("YT_HTTP_PROXY", "").strip()
    https_proxy = os.getenv("YT_HTTPS_PROXY", "").strip()
    if http_proxy or https_proxy:
        return (
            YouTubeTranscriptApi(
                proxy_config=GenericProxyConfig(
                    http_url=http_proxy or None,
                    https_url=https_proxy or None,
                )
            ),
            "generic",
        )
    return YouTubeTranscriptApi(), "direct"


def clean_caption_text(text: str) -> str:
    text = html.unescape(text).replace("\n", " ")
    cue_names = "|".join(re.escape(cue) for cue in NON_SPEECH_CUES)
    text = re.sub(
        rf"\[(?:{cue_names})\b[^\]]*\]",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


def snippet_to_dict(snippet) -> dict:
    if isinstance(snippet, dict):
        text = snippet.get("text", "")
        start = snippet.get("start", 0)
        duration = snippet.get("duration", 0)
    else:
        text = getattr(snippet, "text", "")
        start = getattr(snippet, "start", 0)
        duration = getattr(snippet, "duration", 0)

    start = float(start or 0)
    duration = max(0.0, float(duration or 0))
    return {
        "text": clean_caption_text(str(text)),
        "start": start,
        "end": start + max(duration, 0.25),
        "duration": duration,
    }


def words(text: str) -> list[str]:
    return [m.group(0).lower().replace("’", "'") for m in WORD_RE.finditer(text)]


def word_count(text: str) -> int:
    return len(words(text))


def make_segment(units: list[dict]) -> dict:
    text = re.sub(r"\s+", " ", " ".join(item["text"] for item in units)).strip()
    start = units[0]["start"]
    end = max(units[-1]["end"], start + 0.25)
    return {
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(max(0.25, end - start), 3),
    }


def merge_caption_fragments(snippets: list[dict]) -> list[dict]:
    clean = [item for item in snippets if item["text"]]
    if not clean:
        return []

    segments: list[dict] = []
    buffer: list[dict] = []

    def emit(count: int | None = None) -> None:
        nonlocal buffer
        if not buffer:
            return
        count = len(buffer) if count is None else count
        chunk, buffer = buffer[:count], buffer[count:]
        if chunk:
            segment = make_segment(chunk)
            if segment["text"]:
                segments.append(segment)

    # Preliminary captions only: no word-count or pause-based cuts. The opt-in
    # revision pipeline performs semantic segmentation with word-level times.
    for item in clean:
        buffer.append(item)
        if STRONG_END_RE.search(item["text"]):
            emit()
    emit()

    for index in range(len(segments) - 1):
        next_start = segments[index + 1]["start"]
        if segments[index]["end"] > next_start:
            segments[index]["end"] = max(segments[index]["start"] + 0.25, next_start)
            segments[index]["duration"] = round(
                max(0.25, segments[index]["end"] - segments[index]["start"]),
                3,
            )
    return segments


def fetch_best_transcript(video_id: str):
    api, proxy_mode = build_youtube_api()
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
        "proxy_mode": proxy_mode,
        "items": merge_caption_fragments(snippets),
    }
