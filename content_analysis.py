from __future__ import annotations

import math
import re
from statistics import median
from typing import Any, Iterable

ANALYSIS_VERSION = "content-v1"

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")
_CLAUSE_MARKERS = {
    "although", "though", "whereas", "while", "unless", "despite", "because",
    "since", "therefore", "however", "moreover", "nevertheless", "whether",
    "which", "that", "whose", "whom", "whenever", "wherever", "provided",
    "assuming", "consequently", "furthermore", "instead", "otherwise",
}
_LEVEL_ORDER = {"A2": 0, "B1": 1, "B2": 2, "C1": 3}


def _words(text: str) -> list[str]:
    return [match.group(0).lower().replace("’", "'") for match in _WORD_RE.finditer(text or "")]


def _syllables(word: str) -> int:
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 0
    groups = len(_VOWEL_GROUP_RE.findall(cleaned))
    if cleaned.endswith("e") and groups > 1 and not cleaned.endswith(("le", "ye")):
        groups -= 1
    if cleaned.endswith("es") and groups > 1 and len(cleaned) > 4:
        groups -= 1
    return max(1, groups)


def _mean_window_ttr(words: list[str], window: int = 50) -> float:
    if not words:
        return 0.0
    if len(words) <= window:
        return len(set(words)) / len(words)
    ratios = []
    for start in range(0, len(words), window):
        chunk = words[start : start + window]
        if len(chunk) < max(15, window // 2):
            break
        ratios.append(len(set(chunk)) / len(chunk))
    return sum(ratios) / len(ratios) if ratios else len(set(words)) / len(words)


def _duration(items: list[dict[str, Any]]) -> float:
    starts = []
    ends = []
    summed = 0.0
    for item in items:
        try:
            start = float(item.get("start", 0) or 0)
            duration = max(0.0, float(item.get("duration", 0) or 0))
            end = float(item.get("end", start + duration) or (start + duration))
        except (TypeError, ValueError):
            continue
        starts.append(start)
        ends.append(max(start, end))
        summed += duration
    if starts and ends:
        span = max(ends) - min(starts)
        if span > 0:
            return span
    return summed


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def analyze_transcript(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in items if str(item.get("text", "")).strip()]
    texts = [str(item.get("text", "")).strip() for item in rows]
    tokens = [word for text in texts for word in _words(text)]
    word_count = len(tokens)
    phrase_count = len(texts)
    duration = _duration(rows)

    if not word_count:
        return {
            "analysis_version": ANALYSIS_VERSION,
            "cefr_level": "A2",
            "difficulty_score": 0.0,
            "confidence": "low",
            "word_count": 0,
            "phrase_count": phrase_count,
            "duration": round(duration, 2),
            "wpm": 0.0,
            "avg_phrase_words": 0.0,
            "avg_word_length": 0.0,
            "lexical_diversity": 0.0,
            "complex_word_ratio": 0.0,
            "clause_markers_per_100_words": 0.0,
            "flesch_kincaid_grade": 0.0,
            "reasons": ["字幕文字不足，难度估计置信度较低。"],
        }

    syllables = sum(_syllables(word) for word in tokens)
    complex_words = sum(1 for word in tokens if _syllables(word) >= 3)
    clause_markers = sum(1 for word in tokens if word in _CLAUSE_MARKERS)
    avg_phrase_words = word_count / max(1, phrase_count)
    avg_word_length = sum(len(re.sub(r"[^a-z]", "", word)) for word in tokens) / word_count
    lexical_diversity = _mean_window_ttr(tokens)
    complex_ratio = complex_words / word_count
    clause_rate = clause_markers * 100.0 / word_count
    wpm = (word_count * 60.0 / duration) if duration >= 5 else 0.0

    # The caption chunks are shorter than normal written sentences. A softened
    # Flesch-Kincaid grade is therefore combined with speech pace and lexical
    # features rather than used as the CEFR result by itself.
    fk_grade = (
        0.39 * avg_phrase_words
        + 11.8 * (syllables / word_count)
        - 15.59
    )
    fk_grade = _clamp(fk_grade, 0.0, 16.0)

    reading_score = _clamp((fk_grade - 2.0) / 10.0, 0.0, 1.0)
    lexical_score = _clamp(
        (complex_ratio - 0.035) / 0.16
        + max(0.0, avg_word_length - 4.2) / 5.0,
        0.0,
        1.0,
    )
    syntax_score = _clamp(
        (avg_phrase_words - 6.0) / 13.0 + clause_rate / 10.0,
        0.0,
        1.0,
    )
    pace_score = 0.0 if not wpm else _clamp((wpm - 105.0) / 95.0, 0.0, 1.0)

    score = 100.0 * (
        0.42 * reading_score
        + 0.23 * lexical_score
        + 0.20 * syntax_score
        + 0.15 * pace_score
    )
    score = round(_clamp(score, 0.0, 100.0), 1)

    if score < 30:
        level = "A2"
    elif score < 48:
        level = "B1"
    elif score < 68:
        level = "B2"
    else:
        level = "C1"

    if word_count >= 600:
        confidence = "high"
    elif word_count >= 220:
        confidence = "medium"
    else:
        confidence = "low"

    reasons: list[str] = []
    if wpm >= 175:
        reasons.append(f"语速较快（约 {wpm:.0f} WPM）。")
    elif wpm and wpm <= 115:
        reasons.append(f"语速较慢（约 {wpm:.0f} WPM）。")
    if avg_phrase_words >= 13:
        reasons.append("字幕片段平均较长，听写时需要保持更多短时信息。")
    if complex_ratio >= 0.12:
        reasons.append("多音节词比例较高，词汇负担偏大。")
    if clause_rate >= 3.0:
        reasons.append("从句/逻辑连接词较多，句法关系更复杂。")
    if fk_grade >= 9:
        reasons.append("文本可读性指标接近较高年级英文。")
    if not reasons:
        reasons.append("语速、词汇和句法指标整体较平衡。")
    if confidence == "low":
        reasons.append("字幕样本较短，建议把分级当作初步估计。")

    return {
        "analysis_version": ANALYSIS_VERSION,
        "cefr_level": level,
        "difficulty_score": score,
        "confidence": confidence,
        "word_count": word_count,
        "phrase_count": phrase_count,
        "duration": round(duration, 2),
        "wpm": round(wpm, 1),
        "avg_phrase_words": round(avg_phrase_words, 1),
        "avg_word_length": round(avg_word_length, 2),
        "lexical_diversity": round(lexical_diversity, 3),
        "complex_word_ratio": round(complex_ratio, 3),
        "clause_markers_per_100_words": round(clause_rate, 2),
        "flesch_kincaid_grade": round(fk_grade, 1),
        "reasons": reasons,
    }


def level_recommendation(resource_level: str, learner_level: str | None) -> dict[str, str]:
    resource = _LEVEL_ORDER.get(str(resource_level or "").upper())
    learner = _LEVEL_ORDER.get(str(learner_level or "").upper())
    if resource is None or learner is None:
        return {
            "fit": "unknown",
            "label": "先完成水平评估",
            "detail": "完成水平评估后，资源库会显示这份材料与你当前水平的匹配度。",
        }

    gap = resource - learner
    if gap <= -2:
        return {"fit": "easy", "label": "偏容易", "detail": "适合快速复习或练习流利度。"}
    if gap <= 0:
        return {"fit": "good", "label": "合适", "detail": "与当前听力水平接近，适合作为常规练习。"}
    if gap == 1:
        return {"fit": "challenge", "label": "有挑战", "detail": "比当前水平高一档，适合有意识地挑战。"}
    return {"fit": "hard", "label": "偏难", "detail": "建议先练较低一级的材料，再回来挑战。"}


def rank_resources_for_next_practice(
    resources: Iterable[dict[str, Any]],
    learner_level: str | None,
    sessions: Iterable[dict[str, Any]] | None = None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Rank saved resources for the learner's next listening practice.

    The score is intentionally explainable and deterministic. It favors
    unfinished work, level fit, novelty, a practical session length, and
    higher-confidence content analysis. It does not call an LLM.
    """

    resource_list = [dict(item) for item in resources]
    if not resource_list:
        return []

    history: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in sessions or []:
        session = dict(raw)
        key = (
            str(session.get("source_type") or "youtube").lower(),
            str(session.get("video_id") or ""),
        )
        history.setdefault(key, []).append(session)

    normalized_learner = str(learner_level or "").upper()
    learner_index = _LEVEL_ORDER.get(normalized_learner)
    difficulty_values = [
        float((item.get("analysis") or {}).get("difficulty_score")
              or item.get("difficulty_score")
              or 0)
        for item in resource_list
    ]
    middle_difficulty = median(difficulty_values) if difficulty_values else 50.0

    ranked: list[dict[str, Any]] = []
    for item in resource_list:
        analysis = dict(item.get("analysis") or {})
        resource_level = str(
            analysis.get("cefr_level") or item.get("cefr_level") or ""
        ).upper()
        resource_index = _LEVEL_ORDER.get(resource_level)
        fit = level_recommendation(resource_level, normalized_learner)

        score = 0.0
        reasons: list[str] = []

        if learner_index is not None and resource_index is not None:
            gap = resource_index - learner_index
            if gap == 0:
                score += 40
                reasons.append(f"与当前 {normalized_learner} 水平匹配。")
            elif gap == 1:
                score += 31
                reasons.append(
                    f"比当前 {normalized_learner} 高一档，适合作为挑战。"
                )
            elif gap == -1:
                score += 23
                reasons.append("比当前水平低一档，适合巩固和提高流利度。")
            elif gap <= -2:
                score += 8
                reasons.append("材料明显偏容易，优先级较低。")
            else:
                score -= 25
                reasons.append("材料高出当前水平两档以上，暂时不优先。")
        else:
            difficulty = float(
                analysis.get("difficulty_score")
                or item.get("difficulty_score")
                or 0
            )
            score += max(
                5.0,
                30.0 - min(25.0, abs(difficulty - middle_difficulty) * 0.8),
            )
            reasons.append("尚未完成水平评估，先从资源库中等难度材料开始。")

        key = (
            str(item.get("source_type") or "youtube").lower(),
            str(item.get("source_id") or ""),
        )
        resource_sessions = history.get(key, [])
        latest = resource_sessions[0] if resource_sessions else None
        session_count = max(
            int(item.get("session_count") or 0),
            len(resource_sessions),
        )
        next_action = "new"
        resume_session_id = None

        if latest and not bool(latest.get("completed")):
            progress = float(latest.get("progress_percent") or 0)
            score += 65
            next_action = "resume"
            resume_session_id = latest.get("id")
            reasons.insert(
                0,
                f"上次练到 {progress:.0f}%，优先继续完成，保持学习连续性。",
            )
        elif session_count == 0:
            score += 30
            reasons.append("这份材料还没练过，优先增加新的听力输入。")
        elif session_count == 1:
            score += 10
            reasons.append("只练过一次，仍有复习价值。")
        else:
            score -= min(24, (session_count - 1) * 6)

        if latest and bool(latest.get("completed")):
            total_items = max(1, int(latest.get("total_items") or 0))
            error_count = max(0, int(latest.get("error_count") or 0))
            errors_per_item = error_count / total_items
            if errors_per_item >= 0.5:
                score += 10
                reasons.append("上次错误较多，再练一次有巩固价值。")
            elif errors_per_item <= 0.1 and session_count >= 1:
                score -= 8

        confidence = str(analysis.get("confidence") or "").lower()
        if confidence == "high":
            score += 8
        elif confidence == "medium":
            score += 4
        elif confidence == "low":
            score -= 4

        duration = float(analysis.get("duration") or item.get("duration") or 0)
        if 240 <= duration <= 1200:
            score += 10
            reasons.append(
                f"约 {format_duration(duration)}，适合一次完整听写练习。"
            )
        elif 120 <= duration <= 1800:
            score += 5
        elif duration and duration < 60:
            score -= 6
        elif duration > 2700:
            score -= 7

        word_count = int(
            analysis.get("word_count") or item.get("word_count") or 0
        )
        if word_count >= 300:
            score += 4
        elif word_count and word_count < 100:
            score -= 8

        if bool(item.get("is_generated")):
            score -= 2

        ranked.append(
            {
                **item,
                "recommendation": fit,
                "recommendation_score": round(score, 1),
                "recommendation_reasons": reasons[:4],
                "next_action": next_action,
                "resume_session_id": resume_session_id,
            }
        )

    ranked.sort(
        key=lambda item: (
            float(item.get("recommendation_score") or 0),
            -int(item.get("session_count") or 0),
            float((item.get("analysis") or {}).get("word_count") or 0),
        ),
        reverse=True,
    )
    return ranked[: max(1, min(int(limit), 10))]


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds or 0)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"
