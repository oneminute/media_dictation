from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

import llm_service
from media_service import (
    max_upload_bytes,
    media_dir,
    persist_uploaded_media,
    resolve_media_path,
    transcribe_media,
    whisper_available,
)
from llm_service import (
    SENTENCE_PROMPT_VERSION,
    WORD_PROMPT_VERSION,
    cache_candidates,
    llm_provider,
    normalize_lookup_word,
    ollama_available,
    ollama_base_url,
    ollama_model,
    ollama_timeout_seconds,
    openai_service_tier,
    result_identity,
    translate_to_chinese,
    translate_word_in_context,
    unload_configured_ollama_models,
)
from transcript_service import (
    SEGMENTATION_VERSION,
    build_youtube_api,
    clean_caption_text,
    extract_video_id,
    fetch_best_transcript,
    fetch_video_title,
    merge_caption_fragments,
)

from storage import (
    add_vocabulary_word,
    create_learner,
    create_session,
    export_learner_data,
    get_default_learner_id,
    get_learning_report,
    get_media_source,
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
    record_sentence_review,
    review_vocabulary,
    save_media_source,
    save_translation,
    save_word_translation,
)

load_dotenv()

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = max_upload_bytes()
init_db()


@app.errorhandler(413)
def too_large(_error):
    return jsonify(
        {
            "ok": False,
            "error": (
                "上传文件过大。当前上限为 "
                f"{max_upload_bytes() // (1024 * 1024)} MB。"
            ),
        }
    ), 413


def request_learner_id() -> int:
    raw = request.args.get("learner_id")
    if raw is None and request.is_json:
        payload = request.get_json(silent=True) or {}
        raw = payload.get("learner_id")
    try:
        return int(raw) if raw is not None else get_default_learner_id()
    except (TypeError, ValueError):
        return get_default_learner_id()


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/learning")
def learning_center():
    return send_from_directory("static", "learning.html")


@app.get("/review")
def review_center():
    return send_from_directory("static", "review.html")


@app.get("/media/<media_id>")
def media_file(media_id: str):
    source = get_media_source(media_id)
    if source is None:
        return jsonify({"ok": False, "error": "找不到媒体文件。"}), 404

    path = resolve_media_path(source["stored_filename"])
    if not path.exists():
        return jsonify({"ok": False, "error": "媒体文件已不存在。"}), 404

    return send_from_directory(
        str(media_dir()),
        source["stored_filename"],
        mimetype=source["mime_type"] or None,
        conditional=True,
    )


@app.post("/api/media/transcribe")
def transcribe_local_media():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "没有上传媒体文件。"}), 400

    file_storage = request.files["file"]
    saved = None
    try:
        saved = persist_uploaded_media(file_storage)

        release_ollama = os.getenv(
            "WHISPER_RELEASE_OLLAMA",
            "true",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if release_ollama and ollama_available():
            unload_configured_ollama_models()

        result = transcribe_media(saved["path"])

        source = save_media_source(
            media_id=saved["id"],
            original_name=saved["original_name"],
            stored_filename=saved["stored_filename"],
            mime_type=saved["mime_type"],
            size_bytes=saved["size_bytes"],
            title=saved["title"],
            learner_id=request.form.get("learner_id"),
        )

        return jsonify(
            {
                "ok": True,
                "source_type": "local",
                "media_id": source["id"],
                "video_id": source["id"],
                "video_title": source["title"],
                "source_url": f"/media/{source['id']}",
                "segmentation_version": (
                    f"{SEGMENTATION_VERSION}+whisper-word-timestamps"
                ),
                "language": result["language"],
                "is_generated": True,
                "items": result["items"],
                "whisper_model": result["whisper_model"],
                "whisper_device": result["whisper_device"],
                "whisper_compute_type": result["whisper_compute_type"],
                "duration": result["duration"],
            }
        )
    except Exception as exc:
        if saved is not None:
            try:
                saved["path"].unlink(missing_ok=True)
            except Exception:
                pass
        return jsonify({"ok": False, "error": f"本地媒体转写失败：{exc}"}), 500


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
            "schema_version": get_schema_version(),
            "segmentation_version": SEGMENTATION_VERSION,
            "whisper_available": whisper_available(),
            "whisper_model": os.getenv("WHISPER_MODEL", "small.en"),
            "whisper_device": os.getenv("WHISPER_DEVICE", "auto"),
            "whisper_release_ollama": os.getenv(
                "WHISPER_RELEASE_OLLAMA",
                "true",
            ).strip().lower() in {"1", "true", "yes", "on"},
            "media_max_upload_mb": max_upload_bytes() // (1024 * 1024),
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
            "ollama_auto_translation_timeout_seconds": ollama_timeout_seconds(
                "OLLAMA_AUTO_TRANSLATION_TIMEOUT_SECONDS",
                12.0,
            ),
            "ollama_word_model": ollama_model("OLLAMA_WORD_MODEL"),
            "ollama_word_timeout_seconds": ollama_timeout_seconds(
                "OLLAMA_WORD_TIMEOUT_SECONDS",
                45.0,
            ),
            "ollama_auto_word_timeout_seconds": ollama_timeout_seconds(
                "OLLAMA_AUTO_WORD_TIMEOUT_SECONDS",
                7.0,
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
            "openai_word_model": os.getenv(
                "OPENAI_WORD_MODEL",
                "gpt-5.6-luna",
            ),
            "openai_word_service_tier": openai_service_tier(
                "OPENAI_WORD_SERVICE_TIER",
                "default",
            ),
        }
    )


@app.get("/api/learners")
def learners_list():
    return jsonify(
        {
            "ok": True,
            "learners": list_learners(),
            "default_learner_id": get_default_learner_id(),
        }
    )


@app.post("/api/learners")
def learner_create():
    payload = request.get_json(silent=True) or {}
    try:
        learner = create_learner(str(payload.get("name", "")))
        return jsonify({"ok": True, "learner": learner})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"创建学习者失败：{exc}"}), 400


@app.post("/api/session")
def start_session():
    payload = request.get_json(silent=True) or {}
    video_id = str(payload.get("video_id", "")).strip()
    source_url = str(payload.get("source_url", "")).strip()
    language = str(payload.get("language", "")).strip()
    items = payload.get("items") or []

    if not video_id or not source_url:
        return jsonify({"ok": False, "error": "缺少 video_id 或 source_url。"}), 400
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "items 必须是数组。"}), 400

    try:
        session_id = create_session(
            video_id=video_id,
            source_url=source_url,
            language=language,
            is_generated=bool(payload.get("is_generated", False)),
            total_items=int(payload.get("total_items", 0) or 0),
            learner_id=payload.get("learner_id"),
            video_title=str(payload.get("video_title", "")).strip(),
            items=items,
            segmentation_version=str(
                payload.get("segmentation_version", SEGMENTATION_VERSION)
            ),
            source_type=str(payload.get("source_type", "youtube") or "youtube"),
            media_id=(
                str(payload.get("media_id")).strip()
                if payload.get("media_id")
                else None
            ),
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
    if not sentence_text:
        return jsonify({"ok": False, "error": "缺少 sentence_text。"}), 400

    try:
        record_attempt(
            session_id=session_id,
            sentence_index=sentence_index,
            sentence_text=sentence_text,
            answer_before=str(payload.get("answer_before", "")),
            event_type=str(payload.get("event_type", "")).strip(),
            wrong_word=(
                str(payload.get("wrong_word"))
                if payload.get("wrong_word") is not None
                else None
            ),
            correct_word=(
                str(payload.get("correct_word"))
                if payload.get("correct_word") is not None
                else None
            ),
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"保存听写记录失败：{exc}"}), 500


@app.post("/api/event")
def save_practice_event():
    payload = request.get_json(silent=True) or {}
    try:
        record_practice_event(
            session_id=int(payload.get("session_id")),
            sentence_index=(
                None
                if payload.get("sentence_index") is None
                else int(payload.get("sentence_index"))
            ),
            event_type=str(payload.get("event_type", "")).strip(),
            value_ms=int(payload.get("value_ms", 0) or 0),
            detail=str(payload.get("detail", "")),
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"保存练习事件失败：{exc}"}), 400


@app.get("/api/stats")
def stats():
    return jsonify({"ok": True, **get_stats()})


@app.get("/api/export")
def export_data():
    try:
        return jsonify(
            {
                "ok": True,
                **export_learner_data(request_learner_id()),
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"导出失败：{exc}"}), 400


@app.get("/api/history")
def history():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    return jsonify(
        {
            "ok": True,
            "sessions": get_session_history(
                limit=limit,
                learner_id=request_learner_id(),
            ),
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
    return jsonify(
        {
            "ok": True,
            **get_learning_report(learner_id=request_learner_id()),
        }
    )


@app.post("/api/review-sentences/attempt")
def review_sentence_attempt():
    payload = request.get_json(silent=True) or {}
    try:
        record_sentence_review(
            learner_id=payload.get("learner_id"),
            original_session_id=int(payload.get("session_id")),
            sentence_index=int(payload.get("sentence_index", 0)),
            sentence_text=str(payload.get("sentence_text", "")).strip(),
            answer_before=str(payload.get("answer_before", "")),
            is_correct=bool(payload.get("is_correct", False)),
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"保存错句复习记录失败：{exc}"}), 400


@app.get("/api/review-sentences")
def review_sentences():
    try:
        limit = int(request.args.get("limit", "30"))
    except ValueError:
        limit = 30
    return jsonify(
        {
            "ok": True,
            "items": get_review_sentences(
                learner_id=request_learner_id(),
                limit=limit,
            ),
        }
    )


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

    provider_override = payload.get("provider")
    for provider, model in cache_candidates(
        word=True,
        provider_override=provider_override,
    ):
        cached = get_word_translation(
            normalized_word,
            context_sentence,
            provider=provider,
            model=model,
            prompt_version=WORD_PROMPT_VERSION,
        )
        if cached is not None:
            label = f"ollama:{model}" if provider == "ollama" else model
            return jsonify(
                {
                    "ok": True,
                    "word": display_word,
                    "normalized_word": normalized_word,
                    "translation": cached["translation"],
                    "model": label,
                    "provider": provider,
                    "service_tier": cached.get("service_tier") or (
                        "local" if provider == "ollama" else "default"
                    ),
                    "cached": True,
                }
            )

    try:
        translation, model_label, actual_tier = translate_word_in_context(
            display_word,
            context_sentence,
            provider_override=provider_override,
        )
        provider, raw_model = result_identity(model_label)
        save_word_translation(
            normalized_word=normalized_word,
            display_word=display_word,
            context_sentence=context_sentence,
            translation=translation,
            model=raw_model,
            provider=provider,
            service_tier=actual_tier,
            prompt_version=WORD_PROMPT_VERSION,
        )
        return jsonify(
            {
                "ok": True,
                "word": display_word,
                "normalized_word": normalized_word,
                "translation": translation,
                "model": model_label,
                "provider": provider,
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
    due_only = request.args.get("due", "").lower() in {"1", "true", "yes"}
    return jsonify(
        {
            "ok": True,
            "items": get_vocabulary(
                limit=limit,
                learner_id=request_learner_id(),
                due_only=due_only,
            ),
        }
    )


@app.post("/api/vocabulary")
def vocabulary_add():
    payload = request.get_json(silent=True) or {}
    display_word = str(payload.get("word", "")).strip()
    normalized_word = normalize_lookup_word(display_word)
    translation = str(payload.get("translation", "")).strip()

    if not normalized_word or not translation:
        return jsonify({"ok": False, "error": "缺少单词或中文释义。"}), 400

    try:
        item = add_vocabulary_word(
            normalized_word=normalized_word,
            display_word=display_word,
            translation=translation,
            context_sentence=str(payload.get("context", "")).strip(),
            video_id=str(payload.get("video_id", "")).strip() or None,
            source_url=str(payload.get("source_url", "")).strip() or None,
            learner_id=payload.get("learner_id"),
            session_id=payload.get("session_id"),
            sentence_index=payload.get("sentence_index"),
        )
        return jsonify({"ok": True, "item": item})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"加入生词本失败：{exc}"}), 500


@app.post("/api/vocabulary/<int:entry_id>/review")
def vocabulary_review(entry_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        item = review_vocabulary(entry_id, str(payload.get("rating", "")))
        return jsonify({"ok": True, "item": item})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"更新复习计划失败：{exc}"}), 400


@app.post("/api/translate")
def translate():
    payload = request.get_json(silent=True) or {}
    source_text = str(payload.get("text", "")).strip()
    if not source_text:
        return jsonify({"ok": False, "error": "没有可翻译的英文句子。"}), 400
    if len(source_text) > 2000:
        return jsonify({"ok": False, "error": "当前句子过长，无法翻译。"}), 400

    provider_override = payload.get("provider")
    for provider, model in cache_candidates(
        word=False,
        provider_override=provider_override,
    ):
        cached = get_translation(
            source_text,
            provider=provider,
            model=model,
            prompt_version=SENTENCE_PROMPT_VERSION,
        )
        if cached is not None:
            label = f"ollama:{model}" if provider == "ollama" else model
            return jsonify(
                {
                    "ok": True,
                    "translation": cached["translation"],
                    "model": label,
                    "provider": provider,
                    "service_tier": cached.get("service_tier") or (
                        "local" if provider == "ollama" else "default"
                    ),
                    "cached": True,
                }
            )

    try:
        translation, model_label, actual_tier = translate_to_chinese(
            source_text,
            provider_override=provider_override,
        )
        provider, raw_model = result_identity(model_label)
        save_translation(
            source_text=source_text,
            translation=translation,
            model=raw_model,
            provider=provider,
            service_tier=actual_tier,
            prompt_version=SENTENCE_PROMPT_VERSION,
        )
        return jsonify(
            {
                "ok": True,
                "translation": translation,
                "model": model_label,
                "provider": provider,
                "service_tier": actual_tier,
                "cached": False,
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"翻译失败：{exc}"}), 500


@app.get("/api/transcript")
def transcript():
    value = request.args.get("url", "")
    video_id = extract_video_id(value)
    if not video_id:
        return jsonify(
            {"ok": False, "error": "无法识别 YouTube 链接或 Video ID。"}
        ), 400

    try:
        result = fetch_best_transcript(video_id)
        if not result["items"]:
            raise RuntimeError("The transcript contains no usable spoken captions.")
        return jsonify(
            {
                "ok": True,
                "video_id": video_id,
                "video_title": fetch_video_title(video_id),
                "segmentation_version": SEGMENTATION_VERSION,
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
                "本地运行通常可以直接使用。若在云服务器运行，请配置住宅代理。\n\n"
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
