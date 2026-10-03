from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

SENTENCE_PROMPT_VERSION = "sentence-v2"
WORD_PROMPT_VERSION = "word-v2"


def normalize_provider(value: str | None) -> str:
    provider = str(value or "").strip().lower()
    if provider in {"", "default"}:
        provider = os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto"
    if provider not in {"auto", "ollama", "openai"}:
        raise RuntimeError("LLM provider 必须是 auto、ollama 或 openai。")
    return provider


def llm_provider() -> str:
    return normalize_provider(None)


def ollama_base_url() -> str:
    return (
        os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        .strip()
        .rstrip("/")
    )


def ollama_model(env_name: str) -> str:
    default = "hf.co/unsloth/Qwen3.5-9B-GGUF:UD-Q4_K_XL"
    return os.getenv(env_name, default).strip() or default


def ollama_timeout_seconds(env_name: str, default: float) -> float:
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
        "options": {"temperature": 0},
    }
    req = Request(
        f"{ollama_base_url()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama 返回 HTTP {exc.code}：{detail}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"无法连接本地 Ollama（{ollama_base_url()}）：{reason}"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(f"本地 Ollama 请求超时（{timeout:g} 秒）。") from exc

    content = (
        (data.get("message") or {}).get("content")
        if isinstance(data, dict)
        else None
    )
    content = str(content or "").strip()
    if not content:
        raise RuntimeError("Ollama 返回了空结果。")
    return content


def unload_ollama_model(model: str, timeout: float = 5.0) -> bool:
    if not model:
        return False
    payload = {
        "model": model,
        "keep_alive": 0,
    }
    req = Request(
        f"{ollama_base_url()}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def unload_configured_ollama_models() -> None:
    models = {
        ollama_model("OLLAMA_TRANSLATION_MODEL"),
        ollama_model("OLLAMA_WORD_MODEL"),
    }
    for model in models:
        unload_ollama_model(model)


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
    if model.lower().startswith("gpt-5"):
        return {"reasoning": {"effort": "none"}}
    return {}


def translate_to_chinese_openai(text: str) -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY。请在项目根目录 .env 中设置 API key。")

    model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
    service_tier = openai_service_tier("OPENAI_TRANSLATION_SERVICE_TIER", "flex")
    timeout = openai_timeout_seconds("OPENAI_TRANSLATION_TIMEOUT_SECONDS", 45.0)
    client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

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
        raise RuntimeError("OpenAI API key 无效或未被当前项目接受。") from exc
    except PermissionDeniedError as exc:
        raise RuntimeError(f"当前 API 项目没有权限使用模型 {model}。") from exc
    except NotFoundError as exc:
        raise RuntimeError(f"找不到模型 {model}，或当前 API 项目无权访问。") from exc
    except RateLimitError as exc:
        raise RuntimeError("OpenAI API 返回限流/额度错误。") from exc
    except APITimeoutError as exc:
        raise RuntimeError(f"连接 OpenAI API 超时（{timeout:g} 秒）。") from exc
    except APIConnectionError as exc:
        raise RuntimeError("无法连接 OpenAI API。") from exc
    except BadRequestError as exc:
        raise RuntimeError(f"OpenAI API 拒绝了请求：{exc}") from exc

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
        else ollama_timeout_seconds("OLLAMA_TRANSLATION_TIMEOUT_SECONDS", 60.0)
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


def translate_to_chinese(
    text: str,
    provider_override: str | None = None,
) -> tuple[str, str, str]:
    provider = normalize_provider(provider_override)
    if provider == "ollama":
        return translate_to_chinese_ollama(text)
    if provider == "openai":
        return translate_to_chinese_openai(text)

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


def generate_learning_summary_openai(
    report: dict,
) -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY。")

    model = (
        os.getenv(
            "OPENAI_REPORT_MODEL",
            os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-5.6-luna"),
        ).strip()
        or "gpt-5.6-luna"
    )
    service_tier = openai_service_tier(
        "OPENAI_REPORT_SERVICE_TIER",
        "flex",
    )
    timeout = openai_timeout_seconds(
        "OPENAI_REPORT_TIMEOUT_SECONDS",
        45.0,
    )
    client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

    instructions = (
        "You are an English listening coach. Based only on the supplied "
        "practice statistics, write a concise Simplified Chinese learning report. "
        "Use four short sections: 最近表现, 做得好的地方, 需要加强, 接下来7天. "
        "Be concrete and practical. Mention uncertainty when the sample is small. "
        "Do not claim a CEFR level and do not invent facts not present in the data."
    )

    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=json.dumps(report, ensure_ascii=False),
            max_output_tokens=700,
            service_tier=service_tier,
            **reasoning_kwargs(model),
        )
    except AuthenticationError as exc:
        raise RuntimeError("OpenAI API key 无效或未被当前项目接受。") from exc
    except PermissionDeniedError as exc:
        raise RuntimeError(f"当前 API 项目没有权限使用模型 {model}。") from exc
    except NotFoundError as exc:
        raise RuntimeError(f"找不到模型 {model}，或当前 API 项目无权访问。") from exc
    except RateLimitError as exc:
        raise RuntimeError("OpenAI API 返回限流/额度错误。") from exc
    except APITimeoutError as exc:
        raise RuntimeError(f"OpenAI 学习总结超时（{timeout:g} 秒）。") from exc
    except APIConnectionError as exc:
        raise RuntimeError("无法连接 OpenAI API。") from exc
    except BadRequestError as exc:
        raise RuntimeError(f"OpenAI API 拒绝了学习总结请求：{exc}") from exc

    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("OpenAI 返回了空的学习总结。")
    tier = getattr(response, "service_tier", None) or service_tier
    return text, model, tier


def generate_learning_summary_ollama(
    report: dict,
    timeout_override: float | None = None,
) -> tuple[str, str, str]:
    model = (
        os.getenv(
            "OLLAMA_REPORT_MODEL",
            ollama_model("OLLAMA_TRANSLATION_MODEL"),
        ).strip()
        or ollama_model("OLLAMA_TRANSLATION_MODEL")
    )
    timeout = (
        float(timeout_override)
        if timeout_override is not None
        else ollama_timeout_seconds("OLLAMA_REPORT_TIMEOUT_SECONDS", 60.0)
    )
    text = ollama_chat(
        model=model,
        system_prompt=(
            "你是一名英语听力训练教练。只根据提供的学习统计生成简洁、具体的中文总结。"
            "固定包含四个短小部分：最近表现、做得好的地方、需要加强、接下来7天。"
            "样本不足时明确说明，不要推断CEFR等级，不要编造数据。"
        ),
        user_prompt=json.dumps(report, ensure_ascii=False),
        timeout=timeout,
    )
    return text, f"ollama:{model}", "local"


def generate_learning_summary(
    report: dict,
    provider_override: str | None = None,
) -> tuple[str, str, str]:
    provider = normalize_provider(provider_override)
    if provider == "ollama":
        return generate_learning_summary_ollama(report)
    if provider == "openai":
        return generate_learning_summary_openai(report)

    local_budget = ollama_timeout_seconds(
        "OLLAMA_AUTO_REPORT_TIMEOUT_SECONDS",
        20.0,
    )
    try:
        return generate_learning_summary_ollama(
            report,
            timeout_override=local_budget,
        )
    except Exception as local_exc:
        try:
            return generate_learning_summary_openai(report)
        except Exception as cloud_exc:
            raise RuntimeError(
                f"本地总结失败：{local_exc}；OpenAI fallback 也失败：{cloud_exc}"
            ) from cloud_exc


def normalize_lookup_word(word: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "", word.lower())


def translate_word_in_context_openai(
    word: str,
    context_sentence: str,
) -> tuple[str, str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY。请在项目根目录 .env 中设置 API key。")

    model = os.getenv("OPENAI_WORD_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
    service_tier = openai_service_tier("OPENAI_WORD_SERVICE_TIER", "default")
    timeout = openai_timeout_seconds("OPENAI_WORD_TIMEOUT_SECONDS", 15.0)
    client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)

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
        raise RuntimeError("OpenAI API key 无效或未被当前项目接受。") from exc
    except PermissionDeniedError as exc:
        raise RuntimeError(f"当前 API 项目没有权限使用模型 {model}。") from exc
    except NotFoundError as exc:
        raise RuntimeError(f"找不到模型 {model}，或当前 API 项目无权访问。") from exc
    except RateLimitError as exc:
        raise RuntimeError("OpenAI API 返回限流/额度错误。") from exc
    except APITimeoutError as exc:
        raise RuntimeError(f"连接 OpenAI API 超时（{timeout:g} 秒）。") from exc
    except APIConnectionError as exc:
        raise RuntimeError("无法连接 OpenAI API。") from exc
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
        else ollama_timeout_seconds("OLLAMA_WORD_TIMEOUT_SECONDS", 45.0)
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
        user_prompt=f"Target word: {word}\nSentence: {context_sentence}",
        timeout=timeout,
    )
    return translation, f"ollama:{model}", "local"


def translate_word_in_context(
    word: str,
    context_sentence: str,
    provider_override: str | None = None,
) -> tuple[str, str, str]:
    provider = normalize_provider(provider_override)
    if provider == "ollama":
        return translate_word_in_context_ollama(word, context_sentence)
    if provider == "openai":
        return translate_word_in_context_openai(word, context_sentence)

    local_budget = ollama_timeout_seconds("OLLAMA_AUTO_WORD_TIMEOUT_SECONDS", 7.0)
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


def cache_candidates(
    *,
    word: bool = False,
    provider_override: str | None = None,
) -> list[tuple[str, str]]:
    provider = normalize_provider(provider_override)
    local_model = ollama_model(
        "OLLAMA_WORD_MODEL" if word else "OLLAMA_TRANSLATION_MODEL"
    )
    openai_model = os.getenv(
        "OPENAI_WORD_MODEL" if word else "OPENAI_TRANSLATION_MODEL",
        "gpt-5.6-luna",
    ).strip() or "gpt-5.6-luna"
    if provider == "ollama":
        return [("ollama", local_model)]
    if provider == "openai":
        return [("openai", openai_model)]
    return [("ollama", local_model), ("openai", openai_model)]
