from __future__ import annotations

import html
import os
import re
from urllib.parse import parse_qs, urlparse

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv
from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

from storage import (
    create_session,
    get_learning_report,
    get_session_detail,
    get_session_history,
    get_stats,
    get_translation,
    init_db,
    record_attempt,
    save_translation,
)

load_dotenv()

app = Flask(__name__, static_folder="static")
init_db()

NON_SPEECH_CUES = (
    "music",
    "applause",
    "laughter",
    "laughing",
    "cheering",
    "inaudible",
    "foreign language",
    "silence",
    "sound effect",
    "sound effects",
)

# Dictation segmentation targets. These are deliberately shorter than normal
# written sentences because the unit of practice should be a natural listening
# phrase rather than a long paragraph-like subtitle.
TARGET_WORDS = 10
SOFT_MAX_WORDS = 14
HARD_MAX_WORDS = 18
MIN_PHRASE_WORDS = 4
PAUSE_BREAK_SECONDS = 0.75

WORD_RE = re.compile(r"\b[A-Za-z0-9]+(?:[’'][A-Za-z0-9]+)*\b")
STRONG_END_RE = re.compile(r'[.!?…]["\'’”)]*$')
WEAK_END_RE = re.compile(r'[,;:—-]["\'’”)]*$')

# A break immediately after one of these words usually sounds unnatural.
UNSAFE_END_WORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "with",
    "from",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "may",
    "might",
    "must",
    "not",
    "and",
    "or",
    "but",
    "if",
    "because",
    "that",
    "which",
    "who",
    "whose",
    "than",
    "then",
}

# Starting a new phrase with these words usually means the previous fragment
# was cut too early.
UNSAFE_START_WORDS = {
    "of",
    "to",
    "for",
    "with",
    "from",
    "by",
    "than",
    "as",
    "and",
    "or",
}

# These often introduce a new spoken clause and are useful soft breakpoints.
CLAUSE_STARTERS = {
    "but",
    "so",
    "because",
    "although",
    "though",
    "however",
    "then",
    "meanwhile",
    "while",
    "when",
    "if",
    "since",
    "therefore",
    "instead",
    "yet",
}

PRONOUN_STARTERS = {
    "i",
    "you",
    "we",
    "they",
    "he",
    "she",
    "it",
    "there",
    "this",
    "that",
}


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


def build_youtube_api() -> tuple[YouTubeTranscriptApi, str]:
    """Build the transcript client.

    Local use needs no configuration. Cloud environments such as GitHub Codespaces
    can opt into a residential/generic proxy by setting environment variables.
    """

    webshare_username = os.getenv("YT_WEBSHARE_PROXY_USERNAME", "").strip()
    webshare_password = os.getenv("YT_WEBSHARE_PROXY_PASSWORD", "").strip()

    if webshare_username and webshare_password:
        locations = [
            code.strip().lower()
            for code in os.getenv("YT_WEBSHARE_PROXY_LOCATIONS", "us").split(",")
            if code.strip()
        ]
        return (
            YouTubeTranscriptApi(
                proxy_config=WebshareProxyConfig(
                    proxy_username=webshare_username,
                    proxy_password=webshare_password,
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
    text = html.unescape(text)
    text = text.replace("\n", " ")

    cue_names = "|".join(re.escape(cue) for cue in NON_SPEECH_CUES)

    # Remove non-speech markers even when they are embedded in spoken text:
    # "[Music] Hello everyone" -> "Hello everyone".
    text = re.sub(
        rf"\[(?:{cue_names})\b[^\]]*\]",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"\s+", " ", text).strip()
    return text


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
    return [
        match.group(0).lower().replace("’", "'")
        for match in WORD_RE.finditer(text)
    ]


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

    # "and I...", "and we...", etc. are often a new spoken clause,
    # while a bare "and" before a noun phrase is not a good break.
    return (
        tokens[0] == "and"
        and len(tokens) > 1
        and tokens[1] in PRONOUN_STARTERS
    )


def boundary_score(left: dict, right: dict, phrase_words: int) -> int:
    """Score how natural it is to end a dictation phrase at this boundary."""

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

    # Prefer a compact phrase near the target length.
    score += max(0, 28 - abs(phrase_words - TARGET_WORDS) * 4)

    if phrase_words > SOFT_MAX_WORDS:
        score -= (phrase_words - SOFT_MAX_WORDS) * 8

    return score


def choose_break(buffer: list[dict], force: bool = False):
    """Choose the best existing caption boundary in the current buffer.

    We only cut at real YouTube caption boundaries so playback timestamps remain
    accurate. When possible we use punctuation, pauses, or clause starts instead
    of cutting at an arbitrary word count.
    """

    running_words = 0
    best = None

    for index in range(len(buffer) - 1):
        running_words += word_count(buffer[index]["text"])

        if running_words < MIN_PHRASE_WORDS:
            continue

        if running_words > HARD_MAX_WORDS:
            break

        score = boundary_score(
            buffer[index],
            buffer[index + 1],
            running_words,
        )

        if best is None or score > best[0]:
            best = (score, index + 1)

    if best and (best[0] >= 45 or force):
        return best[1]

    return None


def make_segment(units: list[dict]) -> dict:
    text = re.sub(
        r"\s+",
        " ",
        " ".join(item["text"] for item in units),
    ).strip()

    start = units[0]["start"]
    end = max(units[-1]["end"], start + 0.25)

    return {
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(max(0.25, end - start), 3),
    }


def merge_caption_fragments(snippets: list[dict]) -> list[dict]:
    """Turn YouTube caption fragments into short, natural dictation phrases.

    Priority:
    1. Real sentence-ending punctuation.
    2. Audible pauses.
    3. Commas/semicolons and likely clause boundaries.
    4. Only as a last resort, a safe caption boundary near the target length.

    This avoids the old behavior of blindly cutting after N words/seconds.
    """

    clean = [item for item in snippets if item["text"]]
    if not clean:
        return []

    segments: list[dict] = []
    buffer: list[dict] = []

    def emit(count: int | None = None) -> None:
        nonlocal buffer

        if not buffer:
            return

        if count is None:
            count = len(buffer)

        chunk = buffer[:count]
        buffer = buffer[count:]

        if chunk:
            segment = make_segment(chunk)
            if segment["text"]:
                segments.append(segment)

    def split_long_buffer(force: bool) -> None:
        while (
            len(buffer) > 1
            and buffer_word_count(buffer) > SOFT_MAX_WORDS
        ):
            break_index = choose_break(
                buffer,
                force=force
                or buffer_word_count(buffer) >= HARD_MAX_WORDS,
            )

            if break_index is None:
                return

            emit(break_index)

    for index, item in enumerate(clean):
        buffer.append(item)

        next_item = clean[index + 1] if index + 1 < len(clean) else None

        # If the phrase has become long, try to cut at the best natural boundary
        # already present in the buffer. Do not blindly cut at the current item.
        split_long_buffer(force=False)

        # A real sentence end is always a valid boundary. If the sentence itself
        # is long, break it into shorter clauses first.
        if STRONG_END_RE.search(item["text"]):
            split_long_buffer(force=True)
            emit()
            continue

        # A noticeable pause is a strong spoken-language boundary even when
        # auto-generated captions contain no punctuation.
        if next_item is not None:
            gap = max(0.0, next_item["start"] - item["end"])
            if (
                gap >= PAUSE_BREAK_SECONDS
                and buffer_word_count(buffer) >= MIN_PHRASE_WORDS
            ):
                emit()

    if buffer:
        split_long_buffer(force=True)
        emit()

    # Prevent a segment from playing into the next segment when YouTube caption
    # durations overlap slightly.
    for index in range(len(segments) - 1):
        next_start = segments[index + 1]["start"]
        if segments[index]["end"] > next_start:
            segments[index]["end"] = max(
                segments[index]["start"] + 0.25,
                next_start,
            )
            segments[index]["duration"] = round(
                max(
                    0.25,
                    segments[index]["end"] - segments[index]["start"],
                ),
                3,
            )

    return segments


def translate_to_chinese(text: str) -> tuple[str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OpenAI translation is not configured. Set OPENAI_API_KEY in .env "
            "or in your environment."
        )

    model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-4o-mini").strip()
    if not model:
        model = "gpt-4o-mini"

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        instructions=(
            "Translate the supplied English sentence into natural Simplified Chinese. "
            "Preserve the meaning and tone. Return only the Chinese translation, "
            "with no labels, notes, alternatives, or quotation marks."
        ),
        input=text,
        max_output_tokens=200,
    )

    translation = (response.output_text or "").strip()
    if not translation:
        raise RuntimeError("OpenAI returned an empty translation.")

    return translation, model


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


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/learning")
def learning_center():
    return send_from_directory("static", "learning.html")


@app.get("/api/health")
def health():
    _, proxy_mode = build_youtube_api()
    return jsonify(
        {
            "ok": True,
            "proxy_mode": proxy_mode,
            "sqlite_enabled": True,
            "translation_enabled": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "translation_model": os.getenv(
                "OPENAI_TRANSLATION_MODEL",
                "gpt-4o-mini",
            ),
        }
    )


@app.post("/api/session")
def start_session():
    payload = request.get_json(silent=True) or {}

    video_id = str(payload.get("video_id", "")).strip()
    source_url = str(payload.get("source_url", "")).strip()
    language = str(payload.get("language", "")).strip()
    total_items = payload.get("total_items", 0)

    if not video_id or not source_url:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "缺少 video_id 或 source_url。",
                }
            ),
            400,
        )

    try:
        session_id = create_session(
            video_id=video_id,
            source_url=source_url,
            language=language,
            is_generated=bool(payload.get("is_generated", False)),
            total_items=int(total_items or 0),
        )
        return jsonify({"ok": True, "session_id": session_id})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"创建练习记录失败：{exc}"}), 500


@app.post("/api/attempt")
def save_attempt():
    payload = request.get_json(silent=True) or {}

    try:
        session_id = int(payload.get("session_id"))
        sentence_index = int(payload.get("sentence_index", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "无效的 session_id。"}), 400

    sentence_text = str(payload.get("sentence_text", "")).strip()
    answer_before = str(payload.get("answer_before", ""))
    event_type = str(payload.get("event_type", "")).strip()
    wrong_word = payload.get("wrong_word")
    correct_word = payload.get("correct_word")

    if not sentence_text:
        return jsonify({"ok": False, "error": "缺少 sentence_text。"}), 400

    try:
        record_attempt(
            session_id=session_id,
            sentence_index=sentence_index,
            sentence_text=sentence_text,
            answer_before=answer_before,
            event_type=event_type,
            wrong_word=str(wrong_word) if wrong_word is not None else None,
            correct_word=str(correct_word) if correct_word is not None else None,
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"保存听写记录失败：{exc}"}), 500


@app.get("/api/stats")
def stats():
    return jsonify({"ok": True, **get_stats()})


@app.get("/api/history")
def history():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50

    return jsonify(
        {
            "ok": True,
            "sessions": get_session_history(limit=limit),
        }
    )


@app.get("/api/session/<int:session_id>")
def session_detail(session_id: int):
    result = get_session_detail(session_id)
    if result is None:
        return jsonify({"ok": False, "error": "没有找到这条练习记录。"}), 404

    return jsonify({"ok": True, "session": result})


@app.get("/api/report")
def report():
    return jsonify({"ok": True, **get_learning_report()})


@app.post("/api/translate")
def translate():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()

    if not text:
        return jsonify({"ok": False, "error": "没有可翻译的英文句子。"}), 400

    if len(text) > 2000:
        return jsonify({"ok": False, "error": "当前句子过长，无法翻译。"}), 400

    try:
        cached = get_translation(text)
        if cached is not None:
            return jsonify(
                {
                    "ok": True,
                    "translation": cached["translation"],
                    "model": cached["model"],
                    "cached": True,
                }
            )

        translation, model = translate_to_chinese(text)
        save_translation(
            source_text=text,
            translation=translation,
            model=model,
        )

        return jsonify(
            {
                "ok": True,
                "translation": translation,
                "model": model,
                "cached": False,
            }
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"翻译失败：{exc}",
                }
            ),
            500,
        )


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
        message = str(exc)
        blocked = (
            "blocking requests from your ip" in message.lower()
            or "requestblocked" in message.lower()
            or "ipblocked" in message.lower()
        )

        if blocked:
            error = (
                "YouTube 已阻止当前服务器 IP。视频本身可能有字幕；"
                "GitHub Codespaces 等云服务器的出口 IP 经常被 YouTube 屏蔽。\n\n"
                "本地运行通常可以直接使用。若要在 Codespaces 中自动获取字幕，"
                "请配置住宅代理 Secret（推荐）或通用 HTTP/HTTPS 代理。\n\n"
                f"{message}"
            )
        else:
            error = (
                "无法取得字幕。该视频可能没有可用字幕、字幕受限制，"
                "或者 YouTube 暂时阻止了字幕请求。\n\n"
                f"{message}"
            )

        return jsonify({"ok": False, "error": error}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
