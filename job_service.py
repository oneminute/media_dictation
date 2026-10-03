from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from llm_service import ollama_available, unload_configured_ollama_models
from media_service import resolve_media_path, transcribe_media
from storage import (
    get_media_source,
    get_transcription_job,
    update_media_transcription,
    update_transcription_job,
)
from transcript_service import SEGMENTATION_VERSION


_executor = ThreadPoolExecutor(
    max_workers=max(
        1,
        min(
            2,
            int(os.getenv("MEDIA_TRANSCRIPTION_WORKERS", "1") or 1),
        ),
    ),
    thread_name_prefix="media-whisper",
)
_submitted: set[str] = set()
_lock = Lock()


def enqueue_transcription(job_id: str) -> bool:
    """Queue one persisted transcription job if it is not already active."""
    job_id = str(job_id)
    with _lock:
        if job_id in _submitted:
            return False
        _submitted.add(job_id)

    future = _executor.submit(_run_job, job_id)

    def cleanup(_future) -> None:
        with _lock:
            _submitted.discard(job_id)

    future.add_done_callback(cleanup)
    return True


def _run_job(job_id: str) -> None:
    job = get_transcription_job(job_id)
    if job is None:
        return

    media = get_media_source(job["media_id"])
    if media is None:
        update_transcription_job(
            job_id,
            status="failed",
            progress=0,
            stage="failed",
            error="Media source no longer exists.",
        )
        return

    path = resolve_media_path(media["stored_filename"])
    if not path.exists():
        update_transcription_job(
            job_id,
            status="failed",
            progress=0,
            stage="failed",
            error="Media file no longer exists on disk.",
        )
        return

    try:
        update_transcription_job(
            job_id,
            status="running",
            progress=1,
            stage="preparing",
            detail="Preparing local transcription",
            error="",
        )

        release_ollama = os.getenv(
            "WHISPER_RELEASE_OLLAMA",
            "true",
        ).strip().lower() in {"1", "true", "yes", "on"}
        if release_ollama and ollama_available():
            update_transcription_job(
                job_id,
                progress=3,
                stage="releasing_vram",
                detail="Releasing Ollama GPU memory for Whisper",
            )
            unload_configured_ollama_models()

        def progress(percent: int, stage: str, detail: str) -> None:
            update_transcription_job(
                job_id,
                status="running",
                progress=percent,
                stage=stage,
                detail=detail,
            )

        result = transcribe_media(path, progress_callback=progress)
        update_media_transcription(
            media["id"],
            status="ready",
            transcript=result,
        )

        payload = {
            "source_type": "local",
            "media_id": media["id"],
            "video_id": media["id"],
            "video_title": media["title"] or media["original_name"],
            "source_url": f"/media/{media['id']}",
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
        update_transcription_job(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            detail="Ready to practice",
            result=payload,
        )
    except Exception as exc:
        update_media_transcription(media["id"], status="failed")
        update_transcription_job(
            job_id,
            status="failed",
            stage="failed",
            error=str(exc),
            detail="Transcription failed",
        )
