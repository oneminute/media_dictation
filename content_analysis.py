from __future__ import annotations

import math
import re
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


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds or 0)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"
