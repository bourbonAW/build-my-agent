"""Promptfoo provider for deterministic minimal memory retrieval eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bourbon.memory.cues import expand_query_terms, generate_cues, normalize_cues


def _record_cues(record: dict[str, Any]) -> tuple[str, ...]:
    if "cues" in record:
        return normalize_cues(record.get("cues", []))
    return generate_cues(str(record["content"]))


def _semantic_terms(record: dict[str, Any]) -> tuple[str, ...]:
    return normalize_cues(record.get("semantic_terms", []))


def _normalize_semantic_text(value: str) -> str:
    return " ".join(value.casefold().strip().strip("?？!.。").split())


def _score_record(
    record: dict[str, Any],
    terms: tuple[str, ...],
    *,
    query: str,
    use_cues: bool,
    use_semantic: bool,
) -> int:
    haystack = str(record["content"]).casefold()
    if use_cues:
        haystack += "\n" + "\n".join(_record_cues(record)).casefold()
    score = sum(1 for term in terms if term.casefold() in haystack)
    if use_semantic:
        normalized_query = _normalize_semantic_text(query)
        for term in _semantic_terms(record):
            normalized_term = _normalize_semantic_text(term)
            if normalized_term and (
                normalized_term in normalized_query or normalized_query in normalized_term
            ):
                score += 2
    return score


def _rank(
    records: list[dict[str, Any]],
    query: str,
    *,
    use_cues: bool,
    expand_query: bool,
    use_semantic: bool = False,
) -> list[str]:
    terms = expand_query_terms(query) if expand_query else (query,)
    scored = [
        (
            _score_record(
                record,
                terms,
                query=query,
                use_cues=use_cues,
                use_semantic=use_semantic,
            ),
            str(record["id"]),
        )
        for record in records
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [record_id for score, record_id in scored if score > 0]


def _recall_at(ranked_ids: list[str], expected_id: str, k: int) -> float:
    return 1.0 if expected_id in ranked_ids[:k] else 0.0


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del prompt, options
    vars_data = context.get("vars", {})
    fixture_path = Path("evals/fixtures") / str(vars_data["fixture"])
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    records = list(data["records"])
    cases = list(data["cases"])

    metrics: dict[str, dict[str, float]] = {}
    variants = {
        "content_only": {"use_cues": False, "expand_query": False, "use_semantic": False},
        "content_plus_cues": {"use_cues": True, "expand_query": False, "use_semantic": False},
        "expanded_query_plus_cues": {
            "use_cues": True,
            "expand_query": True,
            "use_semantic": False,
        },
        "hybrid_semantic": {"use_cues": True, "expand_query": True, "use_semantic": True},
    }
    for name, settings in variants.items():
        recalls = []
        for case in cases:
            ranked = _rank(
                records,
                str(case["query"]),
                use_cues=bool(settings["use_cues"]),
                expand_query=bool(settings["expand_query"]),
                use_semantic=bool(settings["use_semantic"]),
            )
            recalls.append(_recall_at(ranked, str(case["expected_id"]), 3))
        metrics[name] = {"recall_at_3": sum(recalls) / len(recalls)}

    output = {
        "metrics": metrics,
        "thresholds": {
            "expanded_query_plus_cues_recall_at_3_min": 0.7,
            "hybrid_semantic_recall_at_3_min": 0.8,
        },
    }
    return {"output": json.dumps(output)}
