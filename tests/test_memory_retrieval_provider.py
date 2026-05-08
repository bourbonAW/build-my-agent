"""Tests for deterministic memory retrieval eval provider."""

from __future__ import annotations

import json

from evals.memory_retrieval_provider import _rank, call_api


def test_rank_uses_generated_cues_when_record_omits_cues() -> None:
    records = [
        {
            "id": "mem_dark_mode",
            "target": "user",
            "content": "User prefers dark mode for UI components.",
        },
        {
            "id": "mem_concise_replies",
            "target": "user",
            "content": "User prefers concise replies.",
        },
    ]

    assert (
        _rank(records, "ui preference", use_cues=True, expand_query=True)[0]
        == "mem_dark_mode"
    )
    assert _rank(records, "ui preference", use_cues=False, expand_query=True) == []


def test_rank_uses_semantic_terms_for_mixed_language_query() -> None:
    records = [
        {
            "id": "mem_dark_mode",
            "target": "user",
            "content": "User prefers dark mode for UI components.",
            "semantic_terms": ["用户喜欢什么界面主题"],
        },
        {
            "id": "mem_concise_replies",
            "target": "user",
            "content": "User prefers concise replies.",
            "semantic_terms": ["简洁回复"],
        },
    ]

    assert (
        _rank(
            records,
            "用户喜欢什么界面主题？",
            use_cues=True,
            expand_query=True,
            use_semantic=True,
        )[0]
        == "mem_dark_mode"
    )
    assert (
        _rank(
            records,
            "用户喜欢什么界面主题？",
            use_cues=True,
            expand_query=True,
            use_semantic=False,
        )
        == []
    )


def test_provider_outputs_hybrid_semantic_metrics() -> None:
    output = call_api(
        "",
        {},
        {"vars": {"fixture": "memory_retrieval/retrieval-smoke.json"}},
    )["output"]
    metrics = json.loads(output)["metrics"]

    assert "hybrid_semantic" in metrics
    assert (
        metrics["hybrid_semantic"]["recall_at_3"]
        > metrics["expanded_query_plus_cues"]["recall_at_3"]
    )
