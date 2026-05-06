"""Tests for bourbon.memory.cues.models."""

from __future__ import annotations

from datetime import UTC, datetime
from math import nan

import pytest

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    DomainConcept,
    MemoryConcept,
    MemoryCueMetadata,
    QueryCue,
    RecallNeed,
    RetrievalCue,
    TimeHint,
)
from bourbon.memory.models import MemoryKind, MemoryScope


def test_memory_concept_values_are_stable() -> None:
    assert {item.value for item in MemoryConcept} == {
        "user_preference",
        "behavior_rule",
        "project_context",
        "architecture_decision",
        "implementation_pattern",
        "workflow",
        "risk_or_lesson",
        "trade_off",
        "how_it_works",
        "external_reference",
    }


def test_cue_quality_flag_values_are_stable() -> None:
    assert {item.value for item in CueQualityFlag} == {
        "llm_generation_failed",
        "llm_interpretation_failed",
        "partial_output",
        "low_cue_coverage",
        "no_decision_question_cue",
        "missing_runtime_file_cue",
        "overbroad_cue",
        "concept_mismatch",
        "invalid_file_hint",
        "malformed_cue_metadata",
        "fallback_used",
    }


def test_query_cue_enum_values_are_stable() -> None:
    assert {item.value for item in RecallNeed} == {"none", "weak", "strong"}
    assert {item.value for item in TimeHint} == {
        "none",
        "recent",
        "last_session",
        "older",
        "explicit_range",
    }


def test_retrieval_cue_validates_text_and_confidence() -> None:
    cue = RetrievalCue(
        text="why not prompt injection",
        kind=CueKind.DECISION_QUESTION,
        source=CueSource.LLM,
        confidence=0.8,
    )

    assert cue.text == "why not prompt injection"

    with pytest.raises(ValueError, match="text"):
        RetrievalCue(text="", kind=CueKind.USER_PHRASE, source=CueSource.USER, confidence=1.0)

    with pytest.raises(ValueError, match="confidence"):
        RetrievalCue(text="x", kind=CueKind.USER_PHRASE, source=CueSource.USER, confidence=1.5)

    with pytest.raises(ValueError, match="confidence"):
        RetrievalCue(text="x", kind=CueKind.USER_PHRASE, source=CueSource.USER, confidence=nan)


def test_domain_concept_requires_namespace_for_skill_and_project_sources() -> None:
    concept = DomainConcept(
        namespace="investment",
        value="risk_model",
        source="skill",
        schema_version="cue.v1",
    )

    assert concept.key == "investment:risk_model"

    with pytest.raises(ValueError, match="namespace"):
        DomainConcept(namespace="", value="risk_model", source="skill", schema_version="cue.v1")

    with pytest.raises(ValueError, match="source"):
        DomainConcept(
            namespace="investment",
            value="risk_model",
            source="not-valid",
            schema_version="cue.v1",
        )


def test_memory_cue_metadata_round_trips_frontmatter_dict() -> None:
    generated_at = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    metadata = MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.ARCHITECTURE_DECISION, MemoryConcept.TRADE_OFF],
        retrieval_cues=[
            RetrievalCue(
                text="why not per-prompt memory injection",
                kind=CueKind.DECISION_QUESTION,
                source=CueSource.LLM,
                confidence=0.84,
            ),
            RetrievalCue(
                text="src/bourbon/memory/prompt.py",
                kind=CueKind.FILE_OR_SYMBOL,
                source=CueSource.RUNTIME,
                confidence=1.0,
            ),
            RetrievalCue(
                text="memory prompt anchor",
                kind=CueKind.TASK_PHRASE,
                source=CueSource.LLM,
                confidence=0.7,
            ),
        ],
        files=["src/bourbon/memory/prompt.py"],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
        domain_concepts=[
            DomainConcept(
                namespace="bourbon",
                value="prompt_anchor",
                source="project",
                schema_version="cue.v1",
            )
        ],
        generated_at=generated_at,
        quality_flags=[],
    )

    raw = metadata.to_frontmatter()
    loaded = MemoryCueMetadata.from_frontmatter(raw)

    assert raw["schema_version"] == "cue.v1"
    assert raw["concepts"] == ["architecture_decision", "trade_off"]
    assert raw["domain_concepts"] == [
        {
            "namespace": "bourbon",
            "value": "prompt_anchor",
            "source": "project",
            "schema_version": "cue.v1",
        }
    ]
    assert loaded == metadata


def test_memory_cue_metadata_validates_minimum_global_concept() -> None:
    with pytest.raises(ValueError, match="concepts"):
        MemoryCueMetadata(
            schema_version="cue.v1",
            generator_version="record-cue-v1",
            concepts=[],
            retrieval_cues=[
                RetrievalCue(
                    text="query",
                    kind=CueKind.USER_PHRASE,
                    source=CueSource.USER,
                    confidence=1.0,
                )
            ],
            files=[],
            symbols=[],
            generation_status=CueGenerationStatus.GENERATED,
        )


def test_query_cue_round_trips_frontmatter_dict() -> None:
    generated_at = datetime(2026, 5, 5, 9, 30, tzinfo=UTC)
    start = datetime(2026, 5, 1, tzinfo=UTC)
    end = datetime(2026, 5, 5, tzinfo=UTC)
    query_cue = QueryCue(
        schema_version="cue.v1",
        interpreter_version="query-cue-v1",
        recall_need=RecallNeed.STRONG,
        concepts=[MemoryConcept.ARCHITECTURE_DECISION],
        cue_phrases=[
            RetrievalCue(
                text="memory prompt anchor",
                kind=CueKind.TASK_PHRASE,
                source=CueSource.LLM,
                confidence=0.77,
            )
        ],
        file_hints=["src/bourbon/memory/prompt.py"],
        symbol_hints=["PromptBuilder"],
        kind_hints=[MemoryKind.PROJECT, MemoryKind.FEEDBACK],
        scope_hint=MemoryScope.PROJECT,
        uncertainty=0.25,
        domain_concepts=[
            DomainConcept(
                namespace="bourbon",
                value="memory",
                source="project",
                schema_version="cue.v1",
            )
        ],
        time_hint=TimeHint.EXPLICIT_RANGE,
        time_range=(start, end),
        generated_at=generated_at,
        fallback_used=True,
        quality_flags=[CueQualityFlag.FALLBACK_USED],
    )

    raw = query_cue.to_frontmatter()
    loaded = QueryCue.from_frontmatter(raw)

    assert raw == {
        "schema_version": "cue.v1",
        "interpreter_version": "query-cue-v1",
        "recall_need": "strong",
        "concepts": ["architecture_decision"],
        "domain_concepts": [
            {
                "namespace": "bourbon",
                "value": "memory",
                "source": "project",
                "schema_version": "cue.v1",
            }
        ],
        "cue_phrases": [
            {
                "text": "memory prompt anchor",
                "kind": "task_phrase",
                "source": "llm",
                "confidence": 0.77,
            }
        ],
        "file_hints": ["src/bourbon/memory/prompt.py"],
        "symbol_hints": ["PromptBuilder"],
        "kind_hints": ["project", "feedback"],
        "scope_hint": "project",
        "uncertainty": 0.25,
        "time_hint": "explicit_range",
        "time_range": [start.isoformat(), end.isoformat()],
        "generated_at": generated_at.isoformat(),
        "fallback_used": True,
        "quality_flags": ["fallback_used"],
    }
    assert loaded == query_cue


def test_query_cue_normalizes_and_deduplicates_file_and_symbol_hints() -> None:
    query_cue = QueryCue(
        schema_version="cue.v1",
        interpreter_version="query-cue-v1",
        recall_need=RecallNeed.WEAK,
        concepts=[],
        cue_phrases=[],
        file_hints=[
            " src/bourbon/memory/prompt.py ",
            "src/bourbon/memory/prompt.py",
            "",
        ],
        symbol_hints=[" PromptBuilder ", "PromptBuilder", ""],
        kind_hints=[],
        scope_hint=None,
        uncertainty=1.0,
    )

    assert query_cue.file_hints == ["src/bourbon/memory/prompt.py"]
    assert query_cue.symbol_hints == ["PromptBuilder"]


def test_query_cue_validates_bounds() -> None:
    with pytest.raises(ValueError, match="concepts"):
        QueryCue(
            schema_version="cue.v1",
            interpreter_version="query-cue-v1",
            recall_need=RecallNeed.WEAK,
            concepts=[
                MemoryConcept.USER_PREFERENCE,
                MemoryConcept.BEHAVIOR_RULE,
                MemoryConcept.PROJECT_CONTEXT,
                MemoryConcept.WORKFLOW,
            ],
            cue_phrases=[],
            file_hints=[],
            symbol_hints=[],
            kind_hints=[],
            scope_hint=None,
            uncertainty=0.0,
        )

    with pytest.raises(ValueError, match="cue_phrases"):
        QueryCue(
            schema_version="cue.v1",
            interpreter_version="query-cue-v1",
            recall_need=RecallNeed.WEAK,
            concepts=[],
            cue_phrases=[
                RetrievalCue(
                    text=f"phrase {index}",
                    kind=CueKind.USER_PHRASE,
                    source=CueSource.USER,
                    confidence=1.0,
                )
                for index in range(9)
            ],
            file_hints=[],
            symbol_hints=[],
            kind_hints=[],
            scope_hint=None,
            uncertainty=0.0,
        )

    with pytest.raises(ValueError, match="uncertainty"):
        QueryCue(
            schema_version="cue.v1",
            interpreter_version="query-cue-v1",
            recall_need=RecallNeed.WEAK,
            concepts=[],
            cue_phrases=[],
            file_hints=[],
            symbol_hints=[],
            kind_hints=[],
            scope_hint=None,
            uncertainty=nan,
        )

    with pytest.raises(ValueError, match="time_range"):
        QueryCue(
            schema_version="cue.v1",
            interpreter_version="query-cue-v1",
            recall_need=RecallNeed.WEAK,
            concepts=[],
            cue_phrases=[],
            file_hints=[],
            symbol_hints=[],
            kind_hints=[],
            scope_hint=None,
            uncertainty=0.0,
            time_hint=TimeHint.EXPLICIT_RANGE,
        )
