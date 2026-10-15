"""Progressive sentence-memory drill: core clause to complete original."""
import json
import re
from llm_service import (normalize_provider, ollama_model, ollama_chat,
    ollama_timeout_seconds, openai_service_tier, openai_timeout_seconds,
    reasoning_kwargs)
from openai import OpenAI
import os

PROMPT_VERSION = "sentence-ladder-v1"
INSTRUCTIONS = """You are an expert English grammar instructor. Return ONLY valid JSON:
{"steps":[{"label":"主干","text":"..."},{"label":"添加修饰","text":"..."},...]}
Build 3-6 progressively expanded grammatical English sentences from the exact
given source sentence, starting with its minimal meaningful independent main
clause (subject + finite verb + needed complement). Add adjectives, adverbs,
prepositional phrases, and subordinate clauses in a pedagogically sensible
order. Each step must be a complete natural sentence, should add material rather
than paraphrase or alter previously retained words, and the FINAL text must be
EXACTLY the source sentence, including punctuation. Never invent facts.
Keep only English in text fields; Chinese short labels. If the original lacks a
clear finite main clause, output one step containing the source unchanged."""


def build_ladder(text, provider_override=None):
    provider = normalize_provider(provider_override)
    def local():
        model = ollama_model("OLLAMA_TRANSLATION_MODEL")
        output = ollama_chat(
            model=model, system_prompt=INSTRUCTIONS, user_prompt=text,
            timeout=ollama_timeout_seconds("OLLAMA_TRANSLATION_TIMEOUT_SECONDS", 60.0))
        return output, "ollama:" + model
    def cloud():
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("未配置 OPENAI_API_KEY")
        model = os.getenv("OPENAI_TRANSLATION_MODEL", "gpt-5.6-luna").strip()
        client = OpenAI(api_key=key, timeout=openai_timeout_seconds("OPENAI_TRANSLATION_TIMEOUT_SECONDS", 45.0), max_retries=0)
        response = client.responses.create(model=model, instructions=INSTRUCTIONS,
            input=text, max_output_tokens=1300,
            service_tier=openai_service_tier("OPENAI_TRANSLATION_SERVICE_TIER", "flex"),
            **reasoning_kwargs(model))
        return response.output_text, model
    if provider == "ollama":
        raw, model = local()
    elif provider == "openai":
        raw, model = cloud()
    else:
        try:
            raw, model = local()
        except Exception:
            raw, model = cloud()
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        raise ValueError("模型未返回可解析的分层练习")
    data = json.loads(match.group())
    stages = data.get("steps", [])
    if not isinstance(stages, list):
        raise ValueError("练习步骤格式不正确")
    valid = []
    for stage in stages[:6]:
        if not isinstance(stage, dict):
            continue
        phrase = str(stage.get("text", "")).strip()
        if not phrase:
            continue
        valid.append({"label": str(stage.get("label", "扩展句子"))[:30], "text": phrase})
    # Do not allow the model to omit or change the original final sentence.
    if not valid or valid[-1]["text"] != text:
        valid.append({"label": "完整原句", "text": text})
    else:
        valid[-1]["label"] = "完整原句"
    if len(valid) < 2:
        valid = [{"label": "完整原句", "text": text}]
    return {"steps": valid, "model": model, "version": PROMPT_VERSION}
