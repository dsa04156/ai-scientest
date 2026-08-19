"""Proposal-only recommendation scoring for generated research ideas.

The score ranks what to validate next. It deliberately does not claim that an
idea is scientifically correct or experimentally superior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_scientist.codex_cli import run_codex


RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rubric_version": {"type": "string"},
        "basis": {"type": "string"},
        "confidence": {"type": "string"},
        "recommended_index": {"type": "integer"},
        "summary": {"type": "string"},
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "idea_index": {"type": "integer"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "verdict": {"type": "string"},
                    "rationale": {"type": "string"},
                    "strength": {"type": "string"},
                    "main_risk": {"type": "string"},
                    "scores": {
                        "type": "object",
                        "properties": {
                            "novelty": {"type": "integer", "minimum": 0, "maximum": 25},
                            "falsifiability": {"type": "integer", "minimum": 0, "maximum": 25},
                            "feasibility": {"type": "integer", "minimum": 0, "maximum": 25},
                            "experimental_rigor": {"type": "integer", "minimum": 0, "maximum": 25},
                        },
                    },
                },
            },
        },
    },
}


SYSTEM_PROMPT = """You are a skeptical research program committee triaging proposed ML experiments.
Compare every proposal with the same rubric and recommend which one should be tested first.

This is proposal-only planning evidence. Never imply that a proposal has already worked,
is scientifically true, or is the final winner. Use these four equally weighted criteria:
- novelty (0-25): meaningful distinction from cited related work; penalize unsupported novelty.
- falsifiability (0-25): a precise hypothesis with outcomes that can discriminate explanations.
- feasibility (0-25): bounded implementation and compute for an academic lab.
- experimental_rigor (0-25): controls, metrics, ablations, generalization, and confound handling.

Use the sum of the four criteria as score. Select exactly one recommended_index: the best
next experiment, not the truest idea. Keep confidence as "low" because no experiment has
run. Set basis to "proposal_only" and rubric_version to "pre-experiment-v1".
Write summary, verdict, rationale, strength, and main_risk in concise Korean.
Verdict must be one of: "우선 검증", "유망", "보완 필요".
"""


def recommendation_path_for(idea_path: str | Path) -> Path:
    path = Path(idea_path)
    return path.with_name(f"{path.stem}.recommendations.json")


def _validate_recommendation(payload: Any, idea_count: int) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("recommendation payload must be an object")
    assessments = payload.get("assessments")
    if not isinstance(assessments, list) or len(assessments) != idea_count:
        raise ValueError("recommendation must assess every idea exactly once")

    indices: set[int] = set()
    for assessment in assessments:
        if not isinstance(assessment, dict):
            raise ValueError("each assessment must be an object")
        index = assessment.get("idea_index")
        if not isinstance(index, int) or not 0 <= index < idea_count:
            raise ValueError("assessment contains an invalid idea index")
        indices.add(index)
        scores = assessment.get("scores")
        if not isinstance(scores, dict):
            raise ValueError("assessment scores are missing")
        components = [
            scores.get("novelty"),
            scores.get("falsifiability"),
            scores.get("feasibility"),
            scores.get("experimental_rigor"),
        ]
        if any(not isinstance(value, int) or not 0 <= value <= 25 for value in components):
            raise ValueError("rubric component must be an integer from 0 to 25")
        if assessment.get("score") != sum(components):
            raise ValueError("recommendation score must equal the rubric component sum")
        if assessment.get("verdict") not in {"우선 검증", "유망", "보완 필요"}:
            raise ValueError("recommendation verdict is invalid")

    if indices != set(range(idea_count)):
        raise ValueError("recommendation idea indices must be unique and complete")
    recommended_index = payload.get("recommended_index")
    if recommended_index not in indices:
        raise ValueError("recommended index is invalid")
    highest_score = max(item["score"] for item in assessments)
    recommended = next(item for item in assessments if item["idea_index"] == recommended_index)
    if recommended["score"] != highest_score:
        raise ValueError("recommended idea must have the highest score")
    priority = [item for item in assessments if item.get("verdict") == "우선 검증"]
    if len(priority) != 1 or priority[0]["idea_index"] != recommended_index:
        raise ValueError("exactly the recommended idea must have the priority verdict")
    if payload.get("basis") != "proposal_only" or payload.get("confidence") != "low":
        raise ValueError("recommendation must preserve proposal-only, low-confidence semantics")
    payload["rubric_version"] = "pre-experiment-v1"
    return payload


def evaluate_ideas(
    ideas: list[dict[str, Any]],
    output_path: str | Path,
    *,
    model: str = "codex",
) -> dict[str, Any]:
    """Evaluate all ideas with one comparative pass and persist the validated result."""
    if not ideas:
        raise ValueError("at least one idea is required for recommendation")
    raw = run_codex(
        system_message=SYSTEM_PROMPT,
        user_message=(
            "다음 연구 제안들을 서로 비교해 같은 기준으로 평가하세요.\n\n"
            + json.dumps(ideas, ensure_ascii=False, indent=2)
        ),
        model=model,
        output_schema=RECOMMENDATION_SCHEMA,
    )
    payload = _validate_recommendation(json.loads(raw), len(ideas))
    destination = Path(output_path)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
