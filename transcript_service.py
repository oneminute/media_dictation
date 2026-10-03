from __future__ import annotations

import html
import os
import re
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import json

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig


TARGET_WORDS = 10
SOFT_MAX_WORDS = 14
HARD_MAX_WORDS = 18
MIN_PHRASE_WORDS = 4
PAUSE_BREAK_SECONDS = 0.75
SEGMENTATION_VERSION = "v3"

NON_SPEECH_CUES = (
    "music", "applause", "laughter", "laughing", "cheering",
    "inaudible", "foreign language", "silence", "sound effect", "sound effects",
)

WORD_RE = re.compile(r"\b[A-Za-z0-9]+(?:[’'][A-Za-z0-9]+)*\b")
STRONG_END_RE = re.compile(r'[.!?…]["\'’”)]*$')
WEAK_END_RE = re.compile(r'[,;:—-]["\'’”)]*$')

UNSAFE_END_WORDS = {
    "a","an","the","to","of","in","on","at","for","with","from","by","as",
    "is","are","was","were","be","been","being","have","has","had","do",
    "does","did","can","could","would","should","will","may","might","must",
    "not","and","or","but","if","because","that","which","who","whose",
    "than","then",
}
UNSAFE_START_WORDS = {"of","to","for","with","from","by","than","as","and","or"}
CLAUSE_STARTERS = {
    "but","so","because","although","though","however","then","meanwhile",
    "while","when","if","since","therefore","instead","yet",
}
PRONOUN_STARTERS = {"i","you","we","they","he","she","it","there","this","that"}


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


def buffer_word_count(buffer: list[dict]) -> int:
    return sum(word_count(item["text"]) for item in buffer)


def starts_new_clause(text: str) -> bool:
    tokens = words(text)[:2]
    if not tokens:
        return False
    if tokens[0] in CLAUSE_STARTERS:
        return True
    return tokens[0] == "and" and len(tokens) > 1 and tokens[1] in PRONOUN_STARTERS


def boundary_score(left: dict, right: dict, phrase_words: int) -> int:
    left_text = left["text"]
    right_text = right["text"]
    if STRONG_END_RE.search(left_text):
        return 1000

    score = 0
    if WEAK_END_RE.search(left_text):
        score += 90

    gap = max(0.0, right["start"] - left["end"])
    if gap >= 1.0:
        score += 95
    elif gap >= 0.75:
        score += 80
    elif gap >= 0.5:
        score += 55
    elif gap >= 0.3:
        score += 25

    if starts_new_clause(right_text):
        score += 45

    left_words = words(left_text)
    right_words = words(right_text)
    if left_words and left_words[-1] in UNSAFE_END_WORDS:
        score -= 120
    if right_words and right_words[0] in UNSAFE_START_WORDS:
        score -= 60

    score += max(0, 28 - abs(phrase_words - TARGET_WORDS) * 4)
    if phrase_words > SOFT_MAX_WORDS:
        score -= (phrase_words - SOFT_MAX_WORDS) * 8
    return score


def choose_break(buffer: list[dict], force: bool = False):
    running_words = 0
    best = None
    for index in range(len(buffer) - 1):
        running_words += word_count(buffer[index]["text"])
        if running_words < MIN_PHRASE_WORDS:
            continue
        if running_words > HARD_MAX_WORDS:
            break
        score = boundary_score(buffer[index], buffer[index + 1], running_words)
        if best is None or score > best[0]:
            best = (score, index + 1)
    if best and (best[0] >= 45 or force):
        return best[1]
    return None


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

    def split_long_buffer(force: bool) -> None:
        while len(buffer) > 1 and buffer_word_count(buffer) > SOFT_MAX_WORDS:
            break_index = choose_break(
                buffer,
                force=force or buffer_word_count(buffer) >= HARD_MAX_WORDS,
            )
            if break_index is None:
                return
            emit(break_index)

    for index, item in enumerate(clean):
        buffer.append(item)
        next_item = clean[index + 1] if index + 1 < len(clean) else None
        split_long_buffer(force=False)

        if STRONG_END_RE.search(item["text"]):
            split_long_buffer(force=True)
            emit()
            continue

        if next_item is not None:
            gap = max(0.0, next_item["start"] - item["end"])
            if gap >= PAUSE_BREAK_SECONDS and buffer_word_count(buffer) >= MIN_PHRASE_WORDS:
                emit()

    if buffer:
        split_long_buffer(force=True)
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
