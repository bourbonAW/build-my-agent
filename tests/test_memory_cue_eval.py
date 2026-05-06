"""Tests for deterministic memory cue eval helpers."""

from __future__ import annotations

import json

import bourbon.memory.cues.eval as cue_eval
from bourbon.memory.cues.eval import (
    CueEvalCase,
    CueEvalResult,
    evaluate_ranked_results,
    rank_records_by_cues,
)
from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    MemoryConcept,
    MemoryCueMetadata,
    QueryCue,
    RecallNeed,
    RetrievalCue,
)


def _metadata(
    *texts: str,
    concepts: list[MemoryConcept] | None = None,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    cue_sources: list[CueSource] | None = None,
    cue_kinds: list[CueKind] | None = None,
    generation_status: CueGenerationStatus = CueGenerationStatus.GENERATED,
    quality_flags: list[CueQualityFlag] | None = None,
) -> MemoryCueMetadata:
    return MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=concepts or [MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text=text,
                kind=cue_kinds[index] if cue_kinds is not None else CueKind.USER_PHRASE,
                source=cue_sources[index] if cue_sources is not None else CueSource.USER,
                confidence=1.0,
            )
            for index, text in enumerate(texts)
        ],
        files=files or [],
        symbols=symbols or [],
        generation_status=generation_status,
        quality_flags=quality_flags or [],
    )


def _query_cue(
    *texts: str,
    concepts: list[MemoryConcept] | None = None,
    file_hints: list[str] | None = None,
    symbol_hints: list[str] | None = None,
    cue_sources: list[CueSource] | None = None,
) -> QueryCue:
    return QueryCue(
        schema_version="cue.v1",
        interpreter_version="query-cue-v1",
        recall_need=RecallNeed.STRONG,
        concepts=concepts or [],
        cue_phrases=[
            RetrievalCue(
                text=text,
                kind=CueKind.USER_PHRASE,
                source=cue_sources[index] if cue_sources is not None else CueSource.LLM,
                confidence=1.0,
            )
            for index, text in enumerate(texts)
        ],
        file_hints=file_hints or [],
        symbol_hints=symbol_hints or [],
        kind_hints=[],
        scope_hint=None,
        uncertainty=0.0,
    )


def _record(
    memory_id: str,
    *,
    name: str = "",
    description: str = "",
    content: str = "",
    cue_metadata: MemoryCueMetadata | None = None,
) -> cue_eval.RetrievalMemoryRecord:
    return cue_eval.RetrievalMemoryRecord(
        memory_id=memory_id,
        name=name,
        description=description,
        content=content,
        cue_metadata=cue_metadata,
    )


def test_rank_records_by_cues_scores_token_overlap() -> None:
    ranked = rank_records_by_cues(
        "database mocking policy",
        {
            "mem_a": _metadata("never mock database"),
            "mem_b": _metadata("prompt anchor budget"),
        },
        limit=2,
    )

    assert ranked[0] == "mem_a"


def test_evaluate_ranked_results_computes_recall_mrr_and_noise() -> None:
    case = CueEvalCase(
        query="database mocking policy",
        expected_memory_ids=["mem_a"],
        ranked_memory_ids=["mem_b", "mem_a", "mem_c"],
        k=3,
    )

    result = evaluate_ranked_results([case])

    assert result == CueEvalResult(recall_at_k=1.0, mrr=0.5, noise_at_k=2 / 3)


def test_evaluate_ranked_results_handles_miss() -> None:
    case = CueEvalCase(
        query="database mocking policy",
        expected_memory_ids=["mem_a"],
        ranked_memory_ids=["mem_b", "mem_c"],
        k=3,
    )

    result = evaluate_ranked_results([case])

    assert result.recall_at_k == 0.0
    assert result.mrr == 0.0
    assert result.noise_at_k == 1.0


def test_evaluate_ranked_results_computes_fractional_recall_for_multiple_expected_ids() -> None:
    case = CueEvalCase(
        query="memory cue design",
        expected_memory_ids=["mem_a", "mem_b"],
        ranked_memory_ids=["mem_a", "mem_c", "mem_d"],
        k=3,
    )

    result = evaluate_ranked_results([case])

    assert result.recall_at_k == 0.5
    assert result.mrr == 1.0
    assert result.noise_at_k == 2 / 3


def test_evaluate_cue_coverage_counts_top_k_probe_hits() -> None:
    cases = [
        cue_eval.CueCoverageCase(
            query="database mocking policy",
            expected_memory_id="mem_a",
            ranked_memory_ids=["mem_a", "mem_b"],
        ),
        cue_eval.CueCoverageCase(
            query="prompt anchor budget",
            expected_memory_id="mem_b",
            ranked_memory_ids=["mem_c", "mem_b"],
            k=2,
        ),
        cue_eval.CueCoverageCase(
            query="sandbox isolation provider",
            expected_memory_id="mem_d",
            ranked_memory_ids=["mem_x", "mem_y", "mem_z"],
        ),
    ]

    result = cue_eval.evaluate_cue_coverage(cases)

    assert result == cue_eval.CueCoverageResult(
        cue_coverage=2 / 3,
        covered_queries=2,
        total_queries=3,
        missed_queries=["sandbox isolation provider"],
    )


def test_evaluate_cue_coverage_handles_empty_cases() -> None:
    result = cue_eval.evaluate_cue_coverage([])

    assert result == cue_eval.CueCoverageResult(
        cue_coverage=0.0,
        covered_queries=0,
        total_queries=0,
        missed_queries=[],
    )


def test_build_generation_quality_report_summarizes_metadata_quality() -> None:
    report = cue_eval.build_generation_quality_report(
        {
            "mem_a": _metadata(
                "database policy",
                "never mock database",
                "integration tests",
                concepts=[MemoryConcept.BEHAVIOR_RULE, MemoryConcept.WORKFLOW],
                files=["tests/test_database.py"],
            ),
            "mem_b": _metadata(
                "fallback memory",
                generation_status=CueGenerationStatus.FAILED,
                quality_flags=[
                    CueQualityFlag.LLM_GENERATION_FAILED,
                    CueQualityFlag.FALLBACK_USED,
                ],
            ),
            "mem_c": _metadata(
                "prompt anchor",
                "managed memory block",
                generation_status=CueGenerationStatus.PARTIAL,
                quality_flags=[CueQualityFlag.LOW_CUE_COVERAGE],
            ),
        }
    )

    assert report == cue_eval.GenerationQualityReport(
        total_records=3,
        generation_status_counts={
            "generated": 1,
            "partial": 1,
            "failed": 1,
            "not_run": 0,
        },
        quality_flag_counts={
            "fallback_used": 1,
            "llm_generation_failed": 1,
            "low_cue_coverage": 1,
        },
        average_retrieval_cues_per_record=2.0,
        average_concepts_per_record=4 / 3,
        average_files_per_record=1 / 3,
        records_with_file_evidence=1,
        records_with_quality_flags=2,
        failed_memory_ids=["mem_b"],
    )


def test_build_generation_quality_report_handles_empty_records() -> None:
    report = cue_eval.build_generation_quality_report({})

    assert report == cue_eval.GenerationQualityReport(
        total_records=0,
        generation_status_counts={
            "generated": 0,
            "partial": 0,
            "failed": 0,
            "not_run": 0,
        },
        quality_flag_counts={},
        average_retrieval_cues_per_record=0.0,
        average_concepts_per_record=0.0,
        average_files_per_record=0.0,
        records_with_file_evidence=0,
        records_with_quality_flags=0,
        failed_memory_ids=[],
    )


def test_evaluate_retrieval_variants_reports_record_query_cues_mrr_lift() -> None:
    records = [
        _record(
            "mem_a_decoy",
            name="Database testing note",
            description="Flaky database setup",
            content="Database tests can be flaky when containers restart.",
            cue_metadata=_metadata("container restart troubleshooting"),
        ),
        _record(
            "mem_z_policy",
            name="Testing preference",
            description="Policy for persistence tests",
            content="When testing persistence behavior, prefer integration coverage.",
            cue_metadata=_metadata("never mock database persistence policy"),
        ),
    ]
    cases = [
        cue_eval.RetrievalEvalCase(
            query="database testing",
            expected_memory_ids=["mem_z_policy"],
            query_cue=_query_cue("never mock database persistence policy"),
            k=2,
        )
    ]

    result = cue_eval.evaluate_retrieval_variants(records, cases, k=2)

    baseline = result[cue_eval.RetrievalVariant.BASELINE_CONTENT]
    cue_based = result[cue_eval.RetrievalVariant.RECORD_QUERY_CUES]
    assert baseline.mrr == 0.5
    assert cue_based.mrr == 1.0
    assert cue_based.mrr_lift >= 1.0


def test_ablation_variants_remove_expected_signals() -> None:
    records = [
        _record(
            "mem_concept",
            name="Weak workflow note",
            content="Generic project note.",
            cue_metadata=_metadata(
                "general project context",
                concepts=[MemoryConcept.ARCHITECTURE_DECISION],
            ),
        ),
        _record(
            "mem_file",
            name="Weak file note",
            content="Generic project note.",
            cue_metadata=_metadata(
                "general project context",
                files=["src/bourbon/memory/store.py"],
                symbols=["MemoryStore"],
            ),
        ),
        _record(
            "mem_llm",
            name="Weak generated note",
            content="Generic project note.",
            cue_metadata=_metadata(
                "semantic preference profile",
                cue_sources=[CueSource.LLM],
            ),
        ),
        _record(
            "mem_runtime",
            name="Weak runtime note",
            content="Generic project note.",
            cue_metadata=_metadata(
                "runtime sandbox evidence",
                cue_sources=[CueSource.RUNTIME],
            ),
        ),
    ]

    concept_case = cue_eval.RetrievalEvalCase(
        query="architecture decision",
        expected_memory_ids=["mem_concept"],
        query_cue=_query_cue(
            concepts=[MemoryConcept.ARCHITECTURE_DECISION],
        ),
        k=1,
    )
    file_case = cue_eval.RetrievalEvalCase(
        query="memory store",
        expected_memory_ids=["mem_file"],
        query_cue=_query_cue(
            file_hints=["src/bourbon/memory/store.py"],
            symbol_hints=["MemoryStore"],
        ),
        k=1,
    )
    llm_case = cue_eval.RetrievalEvalCase(
        query="semantic profile",
        expected_memory_ids=["mem_llm"],
        query_cue=_query_cue("semantic preference profile", cue_sources=[CueSource.LLM]),
        k=1,
    )
    runtime_case = cue_eval.RetrievalEvalCase(
        query="sandbox evidence",
        expected_memory_ids=["mem_runtime"],
        query_cue=_query_cue("runtime sandbox evidence", cue_sources=[CueSource.RUNTIME]),
        k=1,
    )

    assert (
        cue_eval.evaluate_retrieval_variants(
            records,
            [concept_case],
            variants=[
                cue_eval.RetrievalVariant.RECORD_QUERY_CUES,
                cue_eval.RetrievalVariant.ABLATION_CONCEPTS,
            ],
            k=1,
        )[cue_eval.RetrievalVariant.RECORD_QUERY_CUES].recall_at_k
        == 1.0
    )
    assert (
        cue_eval.evaluate_retrieval_variants(
            records,
            [concept_case],
            variants=[cue_eval.RetrievalVariant.ABLATION_CONCEPTS],
            k=1,
        )[cue_eval.RetrievalVariant.ABLATION_CONCEPTS].recall_at_k
        == 0.0
    )
    assert (
        cue_eval.evaluate_retrieval_variants(
            records,
            [file_case],
            variants=[cue_eval.RetrievalVariant.ABLATION_FILES],
            k=1,
        )[cue_eval.RetrievalVariant.ABLATION_FILES].recall_at_k
        == 0.0
    )
    assert (
        cue_eval.evaluate_retrieval_variants(
            records,
            [llm_case],
            variants=[cue_eval.RetrievalVariant.ABLATION_LLM_CUES],
            k=1,
        )[cue_eval.RetrievalVariant.ABLATION_LLM_CUES].recall_at_k
        == 0.0
    )
    assert (
        cue_eval.evaluate_retrieval_variants(
            records,
            [runtime_case],
            variants=[cue_eval.RetrievalVariant.ABLATION_RUNTIME_CUES],
            k=1,
        )[cue_eval.RetrievalVariant.ABLATION_RUNTIME_CUES].recall_at_k
        == 0.0
    )


def test_density_curve_runs_with_synthetic_decoys_and_cues_degrade_slower() -> None:
    target = _record(
        "mem_z_policy",
        name="Persistence testing",
        content="Use integration coverage for persistent behavior.",
        cue_metadata=_metadata("never mock database persistence policy"),
    )
    decoys = [
        _record(
            f"mem_a_decoy_{index:03d}",
            name="Database testing decoy",
            description="Flaky database setup",
            content="database testing flaky container setup",
            cue_metadata=_metadata("container restart troubleshooting"),
        )
        for index in range(30)
    ]
    cases = [
        cue_eval.RetrievalEvalCase(
            query="database testing",
            expected_memory_ids=["mem_z_policy"],
            query_cue=_query_cue("never mock database persistence policy"),
            k=3,
        )
    ]

    curve = cue_eval.evaluate_density_curve(
        [target],
        cases,
        densities=[1, 10, 31],
        decoy_records=decoys,
        k=3,
    )

    assert [point.density for point in curve] == [1, 10, 31]
    baseline_drop = curve[0].baseline_content.mrr - curve[-1].baseline_content.mrr
    cue_drop = curve[0].record_query_cues.mrr - curve[-1].record_query_cues.mrr
    assert baseline_drop > cue_drop
    assert curve[-1].record_query_cues.mrr > curve[-1].baseline_content.mrr


def test_build_field_metrics_report_uses_safe_event_fields() -> None:
    report = cue_eval.build_field_metrics_report(
        [
            cue_eval.CueEvalEvent(
                event_type="query_cue_interpreted",
                schema_version="cue.v1",
                generator_version=None,
                interpreter_version="query-cue-v1",
                query_hash="hash-a",
                concept_count=2,
                cue_count=4,
                memory_ids_returned=[],
                memory_ids_used=[],
                latency_ms=10,
                fallback_used=False,
                quality_flags=[],
            ),
            cue_eval.CueEvalEvent(
                event_type="query_cue_interpreted",
                schema_version="cue.v1",
                generator_version=None,
                interpreter_version="query-cue-v1",
                query_hash="hash-b",
                concept_count=1,
                cue_count=2,
                memory_ids_returned=[],
                memory_ids_used=[],
                latency_ms=100,
                fallback_used=True,
                quality_flags=[
                    CueQualityFlag.FALLBACK_USED,
                    CueQualityFlag.LLM_INTERPRETATION_FAILED,
                ],
            ),
            cue_eval.CueEvalEvent(
                event_type="memory_search_with_cues",
                schema_version="cue.v1",
                generator_version=None,
                interpreter_version="query-cue-v1",
                query_hash="hash-b",
                concept_count=1,
                cue_count=2,
                memory_ids_returned=["mem_a", "mem_b", "mem_c"],
                memory_ids_used=["mem_b"],
                latency_ms=30,
                fallback_used=True,
                quality_flags=[CueQualityFlag.FALLBACK_USED],
            ),
            cue_eval.CueEvalEvent(
                event_type="memory_result_used",
                schema_version="cue.v1",
                generator_version=None,
                interpreter_version=None,
                query_hash="hash-b",
                concept_count=0,
                cue_count=0,
                memory_ids_returned=[],
                memory_ids_used=["mem_b"],
                latency_ms=0,
                fallback_used=False,
                quality_flags=[],
            ),
        ]
    )

    assert report.fallback_rate == 0.5
    assert report.result_use_rate == 1 / 3
    assert report.query_interpreter_latency_p50_ms == 10
    assert report.query_interpreter_latency_p95_ms == 100
    assert report.total_cue_count == 8
    assert report.quality_flag_counts == {
        "fallback_used": 2,
        "llm_interpretation_failed": 1,
    }


def test_cue_eval_event_does_not_require_raw_query_or_memory_content() -> None:
    field_names = set(cue_eval.CueEvalEvent.__dataclass_fields__)

    assert "query" not in field_names
    assert "content" not in field_names
    assert "memory_content" not in field_names


def test_memory_cue_retrieval_provider_returns_smoke_metrics() -> None:
    from evals import memory_cue_retrieval_provider

    response = memory_cue_retrieval_provider.call_api(
        "run memory cue retrieval smoke",
        {"vars": {"fixture": "retrieval-smoke"}},
        {},
    )
    payload = json.loads(response["output"])

    assert payload["passed"] is True
    assert payload["thresholds"]["record_query_cues_noise_at_8_max"] == 0.35
    assert payload["thresholds"]["record_query_cues_mrr_lift_min"] >= 0.2
    assert set(payload["metrics"]) >= {
        "baseline_content",
        "record_query_cues",
    }
    baseline_mrr = payload["metrics"]["baseline_content"]["mrr"]
    cue_metrics = payload["metrics"]["record_query_cues"]
    assert baseline_mrr > 0
    assert cue_metrics["mrr"] > baseline_mrr
    assert cue_metrics["mrr_lift"] >= 0.2
    assert cue_metrics["noise_at_8"] <= 0.35
