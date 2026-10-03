from __future__ import annotations

import gc
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any

from werkzeug.utils import secure_filename

from transcript_service import merge_caption_fragments


ALLOWED_MEDIA_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
}


def media_dir() -> Path:
    raw = os.getenv("MEDIA_DICTATION_MEDIA_DIR", "data/media").strip()
    path = Path(raw or "data/media")
    path.mkdir(parents=True, exist_ok=True)
    return path


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def max_upload_bytes() -> int:
    raw = os.getenv("MEDIA_MAX_UPLOAD_MB", "1024").strip()
    try:
        mb = max(10, min(int(raw), 4096))
    except ValueError:
        mb = 1024
    return mb * 1024 * 1024


def persist_uploaded_media(file_storage) -> dict[str, Any]:
    original_name = secure_filename(file_storage.filename or "")
    if not original_name:
        raise ValueError("没有选择媒体文件。")

    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_MEDIA_EXTENSIONS:
        raise ValueError(
            "不支持该文件类型。支持 MP3/WAV/M4A/AAC/FLAC/OGG/OPUS/"
            "MP4/WEBM/MOV/MKV。"
        )

    media_id = uuid.uuid4().hex
    stored_filename = f"{media_id}{suffix}"
    path = media_dir() / stored_filename

    file_storage.save(path)
    size = path.stat().st_size
    if size <= 0:
        path.unlink(missing_ok=True)
        raise ValueError("上传的媒体文件为空。")
    if size > max_upload_bytes():
        path.unlink(missing_ok=True)
        raise ValueError("媒体文件超过配置的最大上传大小。")

    mime_type = (
        file_storage.mimetype
        or mimetypes.guess_type(original_name)[0]
        or "application/octet-stream"
    )

    return {
        "id": media_id,
        "original_name": original_name,
        "stored_filename": stored_filename,
        "path": path,
        "mime_type": mime_type,
        "size_bytes": size,
        "title": Path(original_name).stem,
    }


def resolve_media_path(stored_filename: str) -> Path:
    name = Path(str(stored_filename)).name
    path = media_dir() / name
    return path


def _word_units_from_segments(segments) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []

    for segment in segments:
        words = getattr(segment, "words", None) or []
        if words:
            for word in words:
                text = str(getattr(word, "word", "") or "").strip()
                if not text or not re.search(r"[A-Za-z0-9]", text):
                    continue
                start = float(getattr(word, "start", 0) or 0)
                end = float(getattr(word, "end", start + 0.05) or (start + 0.05))
                units.append(
                    {
                        "text": text,
                        "start": start,
                        "end": max(end, start + 0.03),
                        "duration": max(0.03, end - start),
                    }
                )
            continue

        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        start = float(getattr(segment, "start", 0) or 0)
        end = float(getattr(segment, "end", start + 0.25) or (start + 0.25))
        units.append(
            {
                "text": text,
                "start": start,
                "end": max(end, start + 0.25),
                "duration": max(0.25, end - start),
            }
        )

    return units


def whisper_segments_to_practice_items(segments) -> list[dict[str, Any]]:
    units = _word_units_from_segments(segments)
    return merge_caption_fragments(units)


def _device_candidates() -> list[tuple[str, str]]:
    configured = os.getenv("WHISPER_DEVICE", "auto").strip().lower() or "auto"
    cuda_compute = (
        os.getenv("WHISPER_COMPUTE_TYPE_CUDA", "int8_float16").strip()
        or "int8_float16"
    )
    cpu_compute = (
        os.getenv("WHISPER_COMPUTE_TYPE_CPU", "int8").strip()
        or "int8"
    )

    if configured == "cuda":
        return [("cuda", cuda_compute)]
    if configured == "cpu":
        return [("cpu", cpu_compute)]
    return [("cuda", cuda_compute), ("cpu", cpu_compute)]


def transcribe_media(
    path: Path,
    progress_callback=None,
) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError(
            "尚未安装 faster-whisper。请运行 setup_whisper_windows.bat。"
        ) from exc

    model_name = os.getenv("WHISPER_MODEL", "small.en").strip() or "small.en"
    language = os.getenv("WHISPER_LANGUAGE", "en").strip() or "en"
    last_error: Exception | None = None

    def report(progress: int, stage: str, detail: str = "") -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(max(0, min(100, int(progress))), stage, detail)
        except Exception:
            pass

    report(2, "preparing", "Preparing Whisper transcription")

    for device, compute_type in _device_candidates():
        model = None
        try:
            report(
                5,
                "loading_model",
                f"Loading {model_name} on {device} ({compute_type})",
            )
            download_root = os.getenv("WHISPER_DOWNLOAD_ROOT", "").strip()
            model_kwargs = {
                "device": device,
                "compute_type": compute_type,
            }
            if download_root:
                Path(download_root).mkdir(parents=True, exist_ok=True)
                model_kwargs["download_root"] = download_root

            model = WhisperModel(
                model_name,
                **model_kwargs,
            )
            report(12, "transcribing", "Whisper model loaded")
            segments, info = model.transcribe(
                str(path),
                language=language,
                beam_size=5,
                vad_filter=True,
                word_timestamps=True,
                condition_on_previous_text=False,
            )

            duration = float(getattr(info, "duration", 0) or 0)
            segment_list = []
            for segment in segments:
                segment_list.append(segment)
                if duration > 0:
                    segment_end = float(getattr(segment, "end", 0) or 0)
                    fraction = max(0.0, min(1.0, segment_end / duration))
                    report(
                        12 + int(fraction * 76),
                        "transcribing",
                        f"Transcribing {fraction * 100:.0f}%",
                    )

            report(90, "segmenting", "Building dictation phrases")
            items = whisper_segments_to_practice_items(segment_list)
            if not items:
                raise RuntimeError("Whisper 没有产生可用于听写的英文内容。")

            report(98, "finalizing", "Finalizing transcript")
            result = {
                "items": items,
                "language": getattr(info, "language", language) or language,
                "duration": float(getattr(info, "duration", 0) or 0),
                "whisper_model": model_name,
                "whisper_device": device,
                "whisper_compute_type": compute_type,
            }
            report(100, "completed", "Transcription complete")
            return result
        except Exception as exc:
            last_error = exc
            if os.getenv("WHISPER_DEVICE", "auto").strip().lower() in {
                "cuda",
                "cpu",
            }:
                break
        finally:
            if model is not None:
                del model
            gc.collect()

    raise RuntimeError(
        "Whisper 转写失败。"
        + (f"最后错误：{last_error}" if last_error is not None else "")
    )
