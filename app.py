from __future__ import annotations

import html
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

from storage import (
    add_vocabulary_word,
    create_learner,
    create_session,
    get_default_learner_id,
    get_learning_report,
    get_review_sentences,
    get_schema_version,
    get_session_detail,
    get_session_history,
    get_stats,
    get_translation,
    get_vocabulary,
    get_word_translation,
    init_db,
    list_learners,
    record_attempt,
    record_practice_event,
    review_vocabulary,
    save_translation,
    save_word_translation,
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
SEGMENTATION_VERSION = "v3"
SENTENCE_PROMPT_VERSION = "sentence-v2"
WORD_PROMPT_VERSION = "word-v2"

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


def fetch_video_title(video_id: str) -> str:
    """Best-effort YouTube title lookup; practice still works if it fails."""
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


def llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto"
    if provider not in {"auto", "ollama", "openai"}:
        raise RuntimeError(
            "LLM_PROVIDER 必须是 auto、ollama 或 openai。"
        )
    return provider


def ollama_base_url() -> str:
    return (
        os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        .strip()
        .rstrip("/")
    )


def ollama_model(env_name: str) -> str:
    default = "hf.co/unsloth/Qwen3.5-9B-GGUF:UD-Q4_K_XL"
    return os.getenv(env_name, default).strip() or default


def ollama_timeout_seconds(
    env_name: str,
    default: float,
) -> float:
    raw = os.getenv(env_name, str(default)).strip()
    try:
        return max(3.0, min(float(raw), 120.0))
    except ValueError:
        return default


def ollama_chat(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
        },
    }

    request_body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{ollama_base_url()}/api/chat",
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama 返回 HTTP {exc.code}：{detail}"
        ) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"无法连接本地 Ollama（{ollama_base_url()}）：{reason}"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"本地 Ollama 请求超时（{timeout:g} 秒）。"
        ) from exc

    content = (
        (data.get("message") or {}).get("content")
        if isinstance(data, dict)
        else None
    )
    content = str(content or "").strip()

    if not content:
        raise RuntimeError("Ollama 返回了空结果。")

    return content


def ollama_available(timeout: float = 1.5) -> bool:
    req = Request(f"{ollama_base_url()}/api/tags", method="GET")
    try:
        with urlopen(req, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def openai_timeout_seconds(
    env_name: str = "OPENAI_TRANSLATION_TIMEOUT_SECONDS",
    default: float = 15.0,
) -> float:
    raw = os.getenv(env_name, str(default)).strip()
    try:
        return max(3.0, min(float(raw), 120.0))
    except ValueError:
        return default


def openai_service_tier(env_name: str, default: str) -> str:
    value = os.getenv(env_name, default).strip().lower()
    return value or default


def reasoning_kwargs(model: str) -> dict:
    # GPT-5.x supports disabling reasoning for simple translation/lookups.
    if model.lower().startswith("gpt-5"):
        return {"reasoning": {"effort": "none"}}
    return {}


def translate_to_chinese_openai(text: str) -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "未配置 OPENAI_API_KEY。请在项目根目录 .env 中设置 API key。"
        )

    model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-5.6-luna").strip()
    if not model:
        model = "gpt-5.6-luna"

    service_tier = openai_service_tier(
        "OPENAI_TRANSLATION_SERVICE_TIER",
        "flex",
    )
    timeout = openai_timeout_seconds(
        "OPENAI_TRANSLATION_TIMEOUT_SECONDS",
        45.0,
    )

    client = OpenAI(
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    )

    try:
        response = client.responses.create(
            model=model,
            instructions=(
                "Translate the supplied English sentence into natural Simplified Chinese. "
                "Preserve the meaning and tone. Return only the Chinese translation, "
                "with no labels, notes, alternatives, or quotation marks."
            ),
            input=text,
            max_output_tokens=200,
            service_tier=service_tier,
            **reasoning_kwargs(model),
        )
    except AuthenticationError as exc:
        raise RuntimeError(
            "OpenAI API key 无效或未被当前项目接受。请检查 .env 中的 OPENAI_API_KEY。"
        ) from exc
    except PermissionDeniedError as exc:
        raise RuntimeError(
            f"当前 API 项目没有权限使用模型 {model}。请更换模型或检查项目权限。"
        ) from exc
    except NotFoundError as exc:
        raise RuntimeError(
            f"找不到模型 {model}，或当前 API 项目无权访问该模型。"
        ) from exc
    except RateLimitError as exc:
        raise RuntimeError(
            "OpenAI API 返回限流/额度错误。请检查 API 项目的余额、预算或速率限制。"
        ) from exc
    except APITimeoutError as exc:
        raise RuntimeError(
            f"连接 OpenAI API 超时（{timeout:g} 秒）。请检查本机网络、代理或防火墙。"
        ) from exc
    except APIConnectionError as exc:
        raise RuntimeError(
            "无法连接 OpenAI API。请检查本机网络、代理、防火墙或 DNS。"
        ) from exc
    except BadRequestError as exc:
        raise RuntimeError(
            f"OpenAI API 拒绝了请求：{exc}"
        ) from exc

    translation = (response.output_text or "").strip()
    if not translation:
        raise RuntimeError("OpenAI API 返回了空翻译。")

    actual_tier = getattr(response, "service_tier", None) or service_tier
    return translation, model, actual_tier


def translate_to_chinese_ollama(
    text: str,
    timeout_override: float | None = None,
) -> tuple[str, str, str]:
    model = ollama_model("OLLAMA_TRANSLATION_MODEL")
    timeout = (
        float(timeout_override)
        if timeout_override is not None
        else ollama_timeout_seconds(
            "OLLAMA_TRANSLATION_TIMEOUT_SECONDS",
            60.0,
        )
    )

    translation = ollama_chat(
        model=model,
        system_prompt=(
            "Translate English into natural Simplified Chinese. "
            "Return only the Chinese translation. Do not explain, "
            "do not add labels, and do not quote the answer."
        ),
        user_prompt=text,
        timeout=timeout,
    )
    return translation, f"ollama:{model}", "local"


def translate_to_chinese(text: str) -> tuple[str, str, str]:
    provider = llm_provider()

    if provider == "ollama":
        return translate_to_chinese_ollama(text)

    if provider == "openai":
        return translate_to_chinese_openai(text)

    # auto: use a short local budget so cloud fallback still has time to finish.
    local_budget = ollama_timeout_seconds(
        "OLLAMA_AUTO_TRANSLATION_TIMEOUT_SECONDS",
        12.0,
    )
    try:
        return translate_to_chinese_ollama(text, timeout_override=local_budget)
    except Exception as local_exc:
        try:
            return translate_to_chinese_openai(text)
        except Exception as cloud_exc:
            raise RuntimeError(
                f"本地 Ollama 失败：{local_exc}；OpenAI fallback 也失败：{cloud_exc}"
            ) from cloud_exc


def normalize_lookup_word(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", word.lower())


def translate_word_in_context_openai(
    word: str,
    context_sentence: str,
) -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "未配置 OPENAI_API_KEY。请在项目根目录 .env 中设置 API key。"
        )

    model = os.getenv("OPENAI_WORD_MODEL", "gpt-5.6-luna").strip()
    if not model:
        model = "gpt-5.6-luna"

    service_tier = openai_service_tier(
        "OPENAI_WORD_SERVICE_TIER",
        "default",
    )
    timeout = openai_timeout_seconds(
        "OPENAI_WORD_TIMEOUT_SECONDS",
        15.0,
    )
    client = OpenAI(
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    )

    prompt = (
        f"Target word: {word}\n"
        f"Sentence: {context_sentence}\n\n"
        "Give the concise Simplified Chinese meaning of the target word as used "
        "in this sentence. Return only the Chinese meaning, normally 1-8 Chinese "
        "characters or a very short phrase. Do not explain and do not translate "
        "the full sentence."
    )

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=80,
            service_tier=service_tier,
            **reasoning_kwargs(model),
        )
    except AuthenticationError as exc:
        raise RuntimeError(
            "OpenAI API key 无效或未被当前项目接受。请检查 .env 中的 OPENAI_API_KEY。"
        ) from exc
    except PermissionDeniedError as exc:
        raise RuntimeError(
            f"当前 API 项目没有权限使用模型 {model}。"
        ) from exc
    except NotFoundError as exc:
        raise RuntimeError(
            f"找不到模型 {model}，或当前 API 项目无权访问该模型。"
        ) from exc
    except RateLimitError as exc:
        raise RuntimeError(
            "OpenAI API 返回限流/额度错误。请检查 API 项目的余额、预算或速率限制。"
        ) from exc
    except APITimeoutError as exc:
        raise RuntimeError(
            f"连接 OpenAI API 超时（{timeout:g} 秒）。"
        ) from exc
    except APIConnectionError as exc:
        raise RuntimeError(
            "无法连接 OpenAI API。请检查本机网络、代理、防火墙或 DNS。"
        ) from exc
    except BadRequestError as exc:
        raise RuntimeError(f"OpenAI API 拒绝了请求：{exc}") from exc

    translation = (response.output_text or "").strip()
    if not translation:
        raise RuntimeError("OpenAI API 返回了空的单词释义。")

    actual_tier = getattr(response, "service_tier", None) or service_tier
    return translation, model, actual_tier


def translate_word_in_context_ollama(
    word: str,
    context_sentence: str,
    timeout_override: float | None = None,
) -> tuple[str, str, str]:
    model = ollama_model("OLLAMA_WORD_MODEL")
    timeout = (
        float(timeout_override)
        if timeout_override is not None
        else ollama_timeout_seconds(
            "OLLAMA_WORD_TIMEOUT_SECONDS",
            45.0,
        )
    )

    translation = ollama_chat(
        model=model,
        system_prompt=(
            "You explain English vocabulary to a Chinese learner. "
            "Given one English target word and its sentence, return only the "
            "concise Simplified Chinese meaning of that word in this exact context. "
            "Usually use 1-8 Chinese characters or a very short phrase. "
            "Do not explain and do not translate the whole sentence."
        ),
        user_prompt=(
            f"Target word: {word}\n"
            f"Sentence: {context_sentence}"
        ),
        timeout=timeout,
    )
    return translation, f"ollama:{model}", "local"


def translate_word_in_context(
    word: str,
    context_sentence: str,
) -> tuple[str, str, str]:
    provider = llm_provider()

    if provider == "ollama":
        return translate_word_in_context_ollama(word, context_sentence)

    if provider == "openai":
        return translate_word_in_context_openai(word, context_sentence)

    local_budget = ollama_timeout_seconds(
        "OLLAMA_AUTO_WORD_TIMEOUT_SECONDS",
        7.0,
    )
    try:
        return translate_word_in_context_ollama(
            word,
            context_sentence,
            timeout_override=local_budget,
        )
    except Exception as local_exc:
        try:
            return translate_word_in_context_openai(word, context_sentence)
        except Exception as cloud_exc:
            raise RuntimeError(
                f"本地 Ollama 失败：{local_exc}；OpenAI fallback 也失败：{cloud_exc}"
            ) from cloud_exc


def result_identity(model_label: str) -> tuple[str, str]:
    if model_label.startswith("ollama:"):
        return "ollama", model_label[len("ollama:"):]
    return "openai", model_label


def cache_candidates(*, word: bool = False) -> list[tuple[str, str]]:
    provider = llm_provider()
    local_model = ollama_model("OLLAMA_WORD_MODEL" if word else "OLLAMA_TRANSLATION_MODEL")
    openai_model = os.getenv(
        "OPENAI_WORD_MODEL" if word else "OPENAI_TRANSLATION_MODEL",
        "gpt-5.6-luna",
    ).strip() or "gpt-5.6-luna"

    if provider == "ollama":
        return [("ollama", local_model)]
    if provider == "openai":
        return [("openai", openai_model)]
    return [("ollama", local_model), ("openai", openai_model)]


def cached_service_tier(model: str, *, word: bool = False) -> str:
    if str(model or "").startswith("ollama:"):
        return "local"

    if word:
        return openai_service_tier(
            "OPENAI_WORD_SERVICE_TIER",
            "default",
        )

    return openai_service_tier(
        "OPENAI_TRANSLATION_SERVICE_TIER",
        "flex",
    )


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
    provider = llm_provider()
    local_ready = ollama_available()
    openai_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())

    return jsonify(
        {
            "ok": True,
            "proxy_mode": proxy_mode,
            "sqlite_enabled": True,
            "llm_provider": provider,
            "translation_enabled": (
                local_ready
                if provider == "ollama"
                else openai_ready
                if provider == "openai"
                else local_ready or openai_ready
            ),
            "ollama_available": local_ready,
            "ollama_base_url": ollama_base_url(),
            "ollama_translation_model": ollama_model(
                "OLLAMA_TRANSLATION_MODEL"
            ),
            "ollama_translation_timeout_seconds": ollama_timeout_seconds(
                "OLLAMA_TRANSLATION_TIMEOUT_SECONDS",
                60.0,
            ),
            "ollama_word_model": ollama_model("OLLAMA_WORD_MODEL"),
            "ollama_word_timeout_seconds": ollama_timeout_seconds(
                "OLLAMA_WORD_TIMEOUT_SECONDS",
                45.0,
            ),
            "openai_enabled": openai_ready,
            "openai_translation_model": os.getenv(
                "OPENAI_TRANSLATION_MODEL",
                "gpt-5.6-luna",
            ),
            "openai_translation_service_tier": openai_service_tier(
                "OPENAI_TRANSLATION_SERVICE_TIER",
                "flex",
            ),
            "openai_translation_timeout_seconds": openai_timeout_seconds(
                "OPENAI_TRANSLATION_TIMEOUT_SECONDS",
                45.0,
            ),
            "openai_word_model": os.getenv(
                "OPENAI_WORD_MODEL",
                "gpt-5.6-luna",
            ),
            "openai_word_service_tier": openai_service_tier(
                "OPENAI_WORD_SERVICE_TIER",
                "default",
            ),
            "openai_word_timeout_seconds": openai_timeout_seconds(
                "OPENAI_WORD_TIMEOUT_SECONDS",
                15.0,
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


@app.post("/api/word-lookup")
def word_lookup():
    payload = request.get_json(silent=True) or {}
    display_word = str(payload.get("word", "")).strip()
    context_sentence = str(payload.get("context", "")).strip()

    normalized_word = normalize_lookup_word(display_word)
    if not normalized_word:
        return jsonify({"ok": False, "error": "没有可查询的单词。"}), 400

    if not context_sentence:
        return jsonify({"ok": False, "error": "缺少当前句子的语境。"}), 400

    if len(display_word) > 100 or len(context_sentence) > 2000:
        return jsonify({"ok": False, "error": "查询内容过长。"}), 400

    cached = get_word_translation(normalized_word, context_sentence)
    if cached is not None:
        return jsonify(
            {
                "ok": True,
                "word": display_word,
                "normalized_word": normalized_word,
                "translation": cached["translation"],
                "model": cached["model"],
                "service_tier": cached_service_tier(
                    cached["model"],
                    word=True,
                ),
                "cached": True,
            }
        )

    try:
        translation, model, actual_tier = translate_word_in_context(
            display_word,
            context_sentence,
        )
        save_word_translation(
            normalized_word=normalized_word,
            display_word=display_word,
            context_sentence=context_sentence,
            translation=translation,
            model=model,
        )
        return jsonify(
            {
                "ok": True,
                "word": display_word,
                "normalized_word": normalized_word,
                "translation": translation,
                "model": model,
                "service_tier": actual_tier,
                "cached": False,
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"单词查询失败：{exc}"}), 500


@app.get("/api/vocabulary")
def vocabulary_list():
    try:
        limit = int(request.args.get("limit", "200"))
    except ValueError:
        limit = 200

    return jsonify({"ok": True, "items": get_vocabulary(limit=limit)})


@app.post("/api/vocabulary")
def vocabulary_add():
    payload = request.get_json(silent=True) or {}

    display_word = str(payload.get("word", "")).strip()
    normalized_word = normalize_lookup_word(display_word)
    translation = str(payload.get("translation", "")).strip()
    context_sentence = str(payload.get("context", "")).strip()
    video_id = str(payload.get("video_id", "")).strip() or None
    source_url = str(payload.get("source_url", "")).strip() or None

    if not normalized_word or not translation:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "缺少单词或中文释义。",
                }
            ),
            400,
        )

    try:
        item = add_vocabulary_word(
            normalized_word=normalized_word,
            display_word=display_word,
            translation=translation,
            context_sentence=context_sentence,
            video_id=video_id,
            source_url=source_url,
        )
        return jsonify({"ok": True, "item": item})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"加入生词本失败：{exc}"}), 500


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
                    "service_tier": cached_service_tier(
                        cached["model"],
                        word=False,
                    ),
                    "cached": True,
                }
            )

        translation, model, actual_tier = translate_to_chinese(text)
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
                "service_tier": actual_tier,
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
