"""Deterministic eval helpers for memory cue representation."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    MemoryCueMetadata,
    QueryCue,
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


class RetrievalVariant(StrEnum):
    BASELINE_CONTENT = "baseline_content"
    RECORD_CUES = "record_cues"
    QUERY_CUES = "query_cues"
    RECORD_QUERY_CUES = "record_query_cues"
    ABLATION_CONCEPTS = "ablation_concepts"
    ABLATION_FILES = "ablation_files"
    ABLATION_LLM_CUES = "ablation_llm_cues"
    ABLATION_RUNTIME_CUES = "ablation_runtime_cues"


class _RetrievalCueLike(Protocol):
    text: str
    confidence: float


class _MemoryCueMetadataLike(Protocol):
    retrieval_cues: Sequence[_RetrievalCueLike]


@dataclass(frozen=True)
class RetrievalMemoryRecord:
    memory_id: str
    name: str
    description: str
    content: str
    cue_metadata: MemoryCueMetadata | None = None


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    expected_memory_ids: list[str]
    query_cue: QueryCue | None = None
    k: int = 8


@dataclass(frozen=True)
class CueEvalCase:
    query: str
    expected_memory_ids: list[str]
    ranked_memory_ids: list[str]
    k: int = 8


@dataclass(frozen=True)
class CueEvalResult:
    recall_at_k: float
    mrr: float
    noise_at_k: float


@dataclass(frozen=True)
class RetrievalVariantMetrics:
    variant: RetrievalVariant
    recall_at_k: float
    mrr: float
    noise_at_k: float
    recall_lift: float
    mrr_lift: float


@dataclass(frozen=True)
class DensityCurvePoint:
    density: int
    active_record_count: int
    baseline_content: RetrievalVariantMetrics
    record_query_cues: RetrievalVariantMetrics
    recall_delta: float
    mrr_delta: float
    noise_delta: float


@dataclass(frozen=True)
class CueCoverageCase:
    query: str
    expected_memory_id: str
    ranked_memory_ids: list[str]
    k: int = 3


@dataclass(frozen=True)
class CueCoverageResult:
    cue_coverage: float
    covered_queries: int
    total_queries: int
    missed_queries: list[str]


@dataclass(frozen=True)
class GenerationQualityReport:
    total_records: int
    generation_status_counts: dict[str, int]
    quality_flag_counts: dict[str, int]
    average_retrieval_cues_per_record: float
    average_concepts_per_record: float
    average_files_per_record: float
    records_with_file_evidence: int
    records_with_quality_flags: int
    failed_memory_ids: list[str]


@dataclass(frozen=True)
class CueEvalEvent:
    event_type: Literal[
        "record_cue_generated",
        "query_cue_interpreted",
        "memory_search_with_cues",
        "memory_result_used",
    ]
    schema_version: str
    generator_version: str | None
    interpreter_version: str | None
    query_hash: str | None
    concept_count: int
    cue_count: int
    memory_ids_returned: list[str]
    memory_ids_used: list[str]
    latency_ms: int
    fallback_used: bool
    quality_flags: list[CueQualityFlag]


@dataclass(frozen=True)
class FieldCueMetricsReport:
    total_events: int
    event_type_counts: dict[str, int]
    cue_utilization_rate: float
    result_use_rate: float
    fallback_rate: float
    query_interpreter_latency_p50_ms: float
    query_interpreter_latency_p95_ms: float
    total_cue_count: int
    average_cue_count: float
    total_concept_count: int
    average_concept_count: float
    quality_flag_counts: dict[str, int]
    generator_version_counts: dict[str, int]
    interpreter_version_counts: dict[str, int]
    record_cue_regeneration_rate: float
    concept_drift_rate: float


_ALL_EVENT_TYPES = (
    "record_cue_generated",
    "query_cue_interpreted",
    "memory_search_with_cues",
    "memory_result_used",
)


def _tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(text)}


def _field_tokens(fields: Sequence[str]) -> set[str]:
    tokens: set[str] = set()
    for field in fields:
        tokens.update(_tokens(field))
    return tokens


def _uses_record_cues(variant: RetrievalVariant) -> bool:
    return variant in {
        RetrievalVariant.RECORD_CUES,
        RetrievalVariant.RECORD_QUERY_CUES,
        RetrievalVariant.ABLATION_CONCEPTS,
        RetrievalVariant.ABLATION_FILES,
        RetrievalVariant.ABLATION_LLM_CUES,
        RetrievalVariant.ABLATION_RUNTIME_CUES,
    }


def _uses_query_cues(variant: RetrievalVariant) -> bool:
    return variant in {
        RetrievalVariant.QUERY_CUES,
        RetrievalVariant.RECORD_QUERY_CUES,
        RetrievalVariant.ABLATION_CONCEPTS,
        RetrievalVariant.ABLATION_FILES,
        RetrievalVariant.ABLATION_LLM_CUES,
        RetrievalVariant.ABLATION_RUNTIME_CUES,
    }


def _include_cue(
    *,
    kind: CueKind,
    source: CueSource,
    variant: RetrievalVariant,
) -> bool:
    if variant == RetrievalVariant.ABLATION_FILES and kind == CueKind.FILE_OR_SYMBOL:
        return False
    if variant == RetrievalVariant.ABLATION_LLM_CUES and source == CueSource.LLM:
        return False
    return not (
        variant == RetrievalVariant.ABLATION_RUNTIME_CUES
        and source == CueSource.RUNTIME
    )


def _metadata_fields(
    metadata: MemoryCueMetadata | None,
    *,
    variant: RetrievalVariant,
) -> list[str]:
    if metadata is None or not _uses_record_cues(variant):
        return []

    fields: list[str] = []
    if variant != RetrievalVariant.ABLATION_CONCEPTS:
        fields.extend(str(concept) for concept in metadata.concepts)
        fields.extend(concept.key for concept in metadata.domain_concepts)
    if variant != RetrievalVariant.ABLATION_FILES:
        fields.extend(metadata.files)
        fields.extend(metadata.symbols)

    for cue in metadata.retrieval_cues:
        if _include_cue(kind=cue.kind, source=cue.source, variant=variant):
            fields.append(cue.text)

    return fields


def _query_cue_fields(
    query_cue: QueryCue | None,
    *,
    variant: RetrievalVariant,
) -> list[str]:
    if query_cue is None or not _uses_query_cues(variant):
        return []

    fields: list[str] = []
    if variant != RetrievalVariant.ABLATION_CONCEPTS:
        fields.extend(str(concept) for concept in query_cue.concepts)
        fields.extend(concept.key for concept in query_cue.domain_concepts)
    if variant != RetrievalVariant.ABLATION_FILES:
        fields.extend(query_cue.file_hints)
        fields.extend(query_cue.symbol_hints)

    for cue in query_cue.cue_phrases:
        if _include_cue(kind=cue.kind, source=cue.source, variant=variant):
            fields.append(cue.text)

    return fields


def _query_fields(case: RetrievalEvalCase, *, variant: RetrievalVariant) -> list[str]:
    return [case.query, *_query_cue_fields(case.query_cue, variant=variant)]


def _record_fields(record: RetrievalMemoryRecord, *, variant: RetrievalVariant) -> list[str]:
    return [
        record.name,
        record.description,
        record.content,
        *_metadata_fields(record.cue_metadata, variant=variant),
    ]


def rank_retrieval_records(
    records: Sequence[RetrievalMemoryRecord],
    case: RetrievalEvalCase,
    *,
    variant: RetrievalVariant,
    limit: int | None = None,
) -> list[str]:
    query_tokens = _field_tokens(_query_fields(case, variant=variant))
    scored: list[tuple[int, str]] = []

    for record in records:
        record_tokens = _field_tokens(_record_fields(record, variant=variant))
        score = len(query_tokens & record_tokens)
        if score > 0:
            scored.append((score, record.memory_id))

    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = [memory_id for score, memory_id in scored]
    if limit is None:
        return ranked
    return ranked[:limit]


def _relative_lift(value: float, baseline: float) -> float:
    if baseline == 0.0:
        return 0.0 if value == 0.0 else 1.0
    return (value - baseline) / baseline


def _evaluate_variant(
    records: Sequence[RetrievalMemoryRecord],
    cases: Sequence[RetrievalEvalCase],
    *,
    variant: RetrievalVariant,
    k: int | None,
) -> CueEvalResult:
    ranked_cases = [
        CueEvalCase(
            query=case.query,
            expected_memory_ids=case.expected_memory_ids,
            ranked_memory_ids=rank_retrieval_records(
                records,
                case,
                variant=variant,
            ),
            k=k if k is not None else case.k,
        )
        for case in cases
    ]
    return evaluate_ranked_results(ranked_cases)


def evaluate_retrieval_variants(
    records: Sequence[RetrievalMemoryRecord],
    cases: Sequence[RetrievalEvalCase],
    *,
    variants: Sequence[RetrievalVariant] | None = None,
    k: int | None = 8,
) -> dict[RetrievalVariant, RetrievalVariantMetrics]:
    selected_variants = list(variants) if variants is not None else list(RetrievalVariant)
    baseline_result = _evaluate_variant(
        records,
        cases,
        variant=RetrievalVariant.BASELINE_CONTENT,
        k=k,
    )

    results: dict[RetrievalVariant, RetrievalVariantMetrics] = {}
    for variant in selected_variants:
        eval_result = (
            baseline_result
            if variant == RetrievalVariant.BASELINE_CONTENT
            else _evaluate_variant(records, cases, variant=variant, k=k)
        )
        results[variant] = RetrievalVariantMetrics(
            variant=variant,
            recall_at_k=eval_result.recall_at_k,
            mrr=eval_result.mrr,
            noise_at_k=eval_result.noise_at_k,
            recall_lift=_relative_lift(
                eval_result.recall_at_k,
                baseline_result.recall_at_k,
            ),
            mrr_lift=_relative_lift(eval_result.mrr, baseline_result.mrr),
        )
    return results


def evaluate_density_curve(
    records: Sequence[RetrievalMemoryRecord],
    cases: Sequence[RetrievalEvalCase],
    *,
    densities: Sequence[int],
    decoy_records: Sequence[RetrievalMemoryRecord] | None = None,
    k: int | None = 8,
) -> list[DensityCurvePoint]:
    all_records = [*records, *(decoy_records or [])]
    points: list[DensityCurvePoint] = []

    for density in densities:
        active_records = all_records[: max(density, 0)]
        metrics = evaluate_retrieval_variants(
            active_records,
            cases,
            variants=[
                RetrievalVariant.BASELINE_CONTENT,
                RetrievalVariant.RECORD_QUERY_CUES,
            ],
            k=k,
        )
        baseline = metrics[RetrievalVariant.BASELINE_CONTENT]
        cue_based = metrics[RetrievalVariant.RECORD_QUERY_CUES]
        points.append(
            DensityCurvePoint(
                density=density,
                active_record_count=len(active_records),
                baseline_content=baseline,
                record_query_cues=cue_based,
                recall_delta=cue_based.recall_at_k - baseline.recall_at_k,
                mrr_delta=cue_based.mrr - baseline.mrr,
                noise_delta=cue_based.noise_at_k - baseline.noise_at_k,
            )
        )

    return points


def rank_records_by_cues(
    query: str,
    records: Mapping[str, _MemoryCueMetadataLike],
    *,
    limit: int = 8,
) -> list[str]:
    query_tokens = _tokens(query)
    scored: list[tuple[float, str]] = []

    for memory_id, metadata in records.items():
        score = 0.0
        for cue in metadata.retrieval_cues:
            overlap = query_tokens & _tokens(cue.text)
            score += len(overlap) * cue.confidence
        scored.append((score, memory_id))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [memory_id for score, memory_id in scored[:limit] if score > 0]


def evaluate_ranked_results(cases: list[CueEvalCase]) -> CueEvalResult:
    if not cases:
        return CueEvalResult(recall_at_k=0.0, mrr=0.0, noise_at_k=0.0)

    recall_total = 0.0
    reciprocal_total = 0.0
    noise_total = 0.0

    for case in cases:
        expected = set(case.expected_memory_ids)
        top_k = case.ranked_memory_ids[: case.k]
        hits = expected.intersection(top_k)
        hit_positions = [
            index
            for index, memory_id in enumerate(top_k, start=1)
            if memory_id in expected
        ]
        if expected:
            recall_total += len(hits) / len(expected)
        elif not top_k:
            recall_total += 1.0
        if hit_positions:
            reciprocal_total += 1.0 / hit_positions[0]
        if top_k:
            noise_total += (
                len([memory_id for memory_id in top_k if memory_id not in expected])
                / len(top_k)
            )
        else:
            noise_total += 1.0

    count = len(cases)
    return CueEvalResult(
        recall_at_k=recall_total / count,
        mrr=reciprocal_total / count,
        noise_at_k=noise_total / count,
    )


def evaluate_cue_coverage(cases: list[CueCoverageCase]) -> CueCoverageResult:
    if not cases:
        return CueCoverageResult(
            cue_coverage=0.0,
            covered_queries=0,
            total_queries=0,
            missed_queries=[],
        )

    covered_queries = 0
    missed_queries: list[str] = []
    for case in cases:
        top_k = case.ranked_memory_ids[: case.k]
        if case.expected_memory_id in top_k:
            covered_queries += 1
        else:
            missed_queries.append(case.query)

    return CueCoverageResult(
        cue_coverage=covered_queries / len(cases),
        covered_queries=covered_queries,
        total_queries=len(cases),
        missed_queries=missed_queries,
    )


def build_generation_quality_report(
    records: Mapping[str, MemoryCueMetadata],
) -> GenerationQualityReport:
    total_records = len(records)
    status_counts = {str(status): 0 for status in CueGenerationStatus}
    quality_flag_counts: Counter[str] = Counter()
    retrieval_cue_total = 0
    concept_total = 0
    file_total = 0
    records_with_file_evidence = 0
    records_with_quality_flags = 0
    failed_memory_ids: list[str] = []

    for memory_id in sorted(records):
        metadata = records[memory_id]
        status = str(metadata.generation_status)
        status_counts[status] = status_counts.get(status, 0) + 1
        retrieval_cue_total += len(metadata.retrieval_cues)
        concept_total += len(metadata.concepts)
        file_total += len(metadata.files)
        if metadata.files:
            records_with_file_evidence += 1
        if metadata.quality_flags:
            records_with_quality_flags += 1
        if status == str(CueGenerationStatus.FAILED):
            failed_memory_ids.append(memory_id)
        quality_flag_counts.update(str(flag) for flag in metadata.quality_flags)

    if total_records == 0:
        average_retrieval_cues = 0.0
        average_concepts = 0.0
        average_files = 0.0
    else:
        average_retrieval_cues = retrieval_cue_total / total_records
        average_concepts = concept_total / total_records
        average_files = file_total / total_records

    return GenerationQualityReport(
        total_records=total_records,
        generation_status_counts=status_counts,
        quality_flag_counts={
            flag: quality_flag_counts[flag]
            for flag in sorted(quality_flag_counts)
        },
        average_retrieval_cues_per_record=average_retrieval_cues,
        average_concepts_per_record=average_concepts,
        average_files_per_record=average_files,
        records_with_file_evidence=records_with_file_evidence,
        records_with_quality_flags=records_with_quality_flags,
        failed_memory_ids=failed_memory_ids,
    )


def _nearest_rank_percentile(values: Sequence[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return float(ordered[rank - 1])


def build_field_metrics_report(events: Sequence[CueEvalEvent]) -> FieldCueMetricsReport:
    event_type_counts: Counter[str] = Counter(event.event_type for event in events)
    quality_flag_counts: Counter[str] = Counter()
    generator_version_counts: Counter[str] = Counter()
    interpreter_version_counts: Counter[str] = Counter()
    total_cue_count = 0
    total_concept_count = 0

    for event in events:
        total_cue_count += event.cue_count
        total_concept_count += event.concept_count
        quality_flag_counts.update(str(flag) for flag in event.quality_flags)
        if event.generator_version is not None:
            generator_version_counts.update([event.generator_version])
        if event.interpreter_version is not None:
            interpreter_version_counts.update([event.interpreter_version])

    query_events = [
        event for event in events if event.event_type == "query_cue_interpreted"
    ]
    search_events = [
        event for event in events if event.event_type == "memory_search_with_cues"
    ]
    generated_events = [
        event for event in events if event.event_type == "record_cue_generated"
    ]

    fallback_events = query_events if query_events else list(events)
    fallback_rate = (
        sum(1 for event in fallback_events if event.fallback_used) / len(fallback_events)
        if fallback_events
        else 0.0
    )
    cue_utilization_rate = (
        sum(1 for event in search_events if event.cue_count > 0) / len(search_events)
        if search_events
        else 0.0
    )

    returned_ids = {
        memory_id
        for event in search_events
        for memory_id in event.memory_ids_returned
    }
    used_ids = {
        memory_id
        for event in events
        for memory_id in event.memory_ids_used
    }
    result_use_rate = (
        len(returned_ids & used_ids) / len(returned_ids)
        if returned_ids
        else 0.0
    )

    query_latencies = [event.latency_ms for event in query_events]
    generated_ids = [
        memory_id
        for event in generated_events
        for memory_id in event.memory_ids_returned
    ]
    record_cue_regeneration_rate = (
        (len(generated_ids) - len(set(generated_ids))) / len(generated_ids)
        if generated_ids
        else 0.0
    )
    concept_drift_rate = (
        quality_flag_counts[str(CueQualityFlag.CONCEPT_MISMATCH)] / len(events)
        if events
        else 0.0
    )

    total_events = len(events)
    return FieldCueMetricsReport(
        total_events=total_events,
        event_type_counts={
            event_type: event_type_counts[event_type]
            for event_type in _ALL_EVENT_TYPES
        },
        cue_utilization_rate=cue_utilization_rate,
        result_use_rate=result_use_rate,
        fallback_rate=fallback_rate,
        query_interpreter_latency_p50_ms=_nearest_rank_percentile(
            query_latencies,
            50.0,
        ),
        query_interpreter_latency_p95_ms=_nearest_rank_percentile(
            query_latencies,
            95.0,
        ),
        total_cue_count=total_cue_count,
        average_cue_count=total_cue_count / total_events if total_events else 0.0,
        total_concept_count=total_concept_count,
        average_concept_count=(
            total_concept_count / total_events if total_events else 0.0
        ),
        quality_flag_counts={
            flag: quality_flag_counts[flag]
            for flag in sorted(quality_flag_counts)
        },
        generator_version_counts={
            version: generator_version_counts[version]
            for version in sorted(generator_version_counts)
        },
        interpreter_version_counts={
            version: interpreter_version_counts[version]
            for version in sorted(interpreter_version_counts)
        },
        record_cue_regeneration_rate=record_cue_regeneration_rate,
        concept_drift_rate=concept_drift_rate,
    )
