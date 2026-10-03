from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


ASSESSMENT_VERSION = "cefr-screening-v1"

_ITEMS = [
    {
        "id": "a2-1",
        "level": "A2",
        "text": "My brother takes the bus to school every morning.",
        "rate": 0.90,
    },
    {
        "id": "a2-2",
        "level": "A2",
        "text": "We bought some fruit and bread after work.",
        "rate": 0.90,
    },
    {
        "id": "a2-3",
        "level": "A2",
        "text": "Please call me when you arrive at the station.",
        "rate": 0.90,
    },
    {
        "id": "b1-1",
        "level": "B1",
        "text": "I was planning to cook dinner, but the meeting ended much later than expected.",
        "rate": 0.96,
    },
    {
        "id": "b1-2",
        "level": "B1",
        "text": "Even though the weather looked bad, we decided to continue with our weekend trip.",
        "rate": 0.96,
    },
    {
        "id": "b1-3",
        "level": "B1",
        "text": "The teacher explained the problem again so that everyone could understand the instructions.",
        "rate": 0.96,
    },
    {
        "id": "b2-1",
        "level": "B2",
        "text": "Although the proposal sounded reasonable at first, several details became questionable once we examined the costs.",
        "rate": 1.00,
    },
    {
        "id": "b2-2",
        "level": "B2",
        "text": "People often underestimate how much their daily habits influence the decisions they make under pressure.",
        "rate": 1.00,
    },
    {
        "id": "b2-3",
        "level": "B2",
        "text": "By the time the researchers published their findings, the original theory had already been revised twice.",
        "rate": 1.00,
    },
    {
        "id": "c1-1",
        "level": "C1",
        "text": "What initially appeared to be a minor disagreement gradually exposed a deeper conflict over how responsibility should be shared.",
        "rate": 1.03,
    },
    {
        "id": "c1-2",
        "level": "C1",
        "text": "Had the committee anticipated the unintended consequences, it might have introduced the policy far more cautiously.",
        "rate": 1.03,
    },
    {
        "id": "c1-3",
        "level": "C1",
        "text": "The argument is persuasive not because every assumption is certain, but because the alternatives account for considerably less evidence.",
        "rate": 1.03,
    },
]

_ITEM_BY_ID = {item["id"]: item for item in _ITEMS}
_LEVELS = ["A2", "B1", "B2", "C1"]


def assessment_items() -> list[dict[str, Any]]:
    # Text is needed by browser speech synthesis. The page never renders it as
    # source text during the assessment.
    return [
        {
            "id": item["id"],
            "level": item["level"],
            "tts_text": item["text"],
            "rate": item["rate"],
        }
        for item in _ITEMS
    ]


def expected_text(item_id: str) -> str:
    item = _ITEM_BY_ID.get(str(item_id))
    if item is None:
        raise ValueError("Unknown assessment item.")
    return item["text"]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", str(text).lower())


def token_accuracy(expected: str, answer: str) -> float:
    expected_tokens = _tokens(expected)
    answer_tokens = _tokens(answer)
    if not expected_tokens:
        return 1.0 if not answer_tokens else 0.0

    matcher = SequenceMatcher(
        None,
        expected_tokens,
        answer_tokens,
        autojunk=False,
    )
    matched = sum(block.size for block in matcher.get_matching_blocks())
    insertions_or_extras = max(0, len(answer_tokens) - matched)
    raw = (matched - 0.35 * insertions_or_extras) / len(expected_tokens)
    return round(max(0.0, min(1.0, raw)), 4)


def score_answer(
    item_id: str,
    answer: str,
    replays: int = 0,
) -> dict[str, Any]:
    item = _ITEM_BY_ID.get(str(item_id))
    if item is None:
        raise ValueError("Unknown assessment item.")

    accuracy = token_accuracy(item["text"], answer)
    exact = _tokens(item["text"]) == _tokens(answer)

    # Replays are useful diagnostic information. They apply a small screening
    # penalty rather than converting a correct transcription into zero.
    replay_penalty = min(0.18, max(0, int(replays)) * 0.035)
    adjusted = max(0.0, accuracy - replay_penalty)

    return {
        "item_id": item["id"],
        "level": item["level"],
        "expected_text": item["text"],
        "token_accuracy": accuracy,
        "adjusted_accuracy": round(adjusted, 4),
        "exact_correct": exact,
        "replays": max(0, int(replays)),
    }


def summarize_responses(
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    by_level: dict[str, list[dict[str, Any]]] = {
        level: [] for level in _LEVELS
    }
    for response in responses:
        level = str(response.get("level", ""))
        if level in by_level:
            by_level[level].append(response)

    level_stats: dict[str, dict[str, Any]] = {}
    highest = "Below A2"
    passed_levels: list[str] = []

    for level in _LEVELS:
        group = by_level[level]
        if not group:
            level_stats[level] = {
                "average_accuracy": None,
                "passed_items": 0,
                "items": 0,
            }
            continue

        adjusted_values = [
            float(
                response.get(
                    "adjusted_accuracy",
                    response.get("token_accuracy", 0),
                )
            )
            for response in group
        ]
        avg = sum(adjusted_values) / len(adjusted_values)
        passed_items = sum(1 for value in adjusted_values if value >= 0.70)
        level_pass = avg >= 0.74 and passed_items >= 2

        level_stats[level] = {
            "average_accuracy": round(avg * 100, 1),
            "passed_items": passed_items,
            "items": len(group),
            "passed": level_pass,
        }
        if level_pass:
            highest = level
            passed_levels.append(level)
        else:
            # CEFR levels are cumulative for this screen. Do not skip a failed
            # lower band and assign a higher one from a lucky item set.
            break

    total = len(responses)
    all_adjusted = [
        float(
            response.get(
                "adjusted_accuracy",
                response.get("token_accuracy", 0),
            )
        )
        for response in responses
    ]
    score = (
        round(sum(all_adjusted) * 100.0 / len(all_adjusted), 1)
        if all_adjusted
        else 0.0
    )

    if total < len(_ITEMS):
        confidence = "low"
    elif len(passed_levels) in {0, len(_LEVELS)}:
        confidence = "medium"
    else:
        confidence = "medium-high"

    return {
        "score": score,
        "estimated_level": highest,
        "confidence": confidence,
        "level_stats": level_stats,
        "answered_items": total,
        "total_items": len(_ITEMS),
        "note": (
            "This is a CEFR-aligned listening/dictation screening estimate "
            "using fixed in-app material and local browser speech synthesis. "
            "It is not an official CEFR examination or certification."
        ),
    }
