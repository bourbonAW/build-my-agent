"""Promptfoo provider for deterministic memory cue retrieval smoke evals."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bourbon.memory.cues.eval import (  # noqa: E402
    RetrievalEvalCase,
    RetrievalMemoryRecord,
    RetrievalVariant,
    RetrievalVariantMetrics,
    evaluate_retrieval_variants,
)
from bourbon.memory.cues.models import (  # noqa: E402
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

DEFAULT_FIXTURE = "memory_cues/retrieval-smoke.json"

type MetricPayload = dict[str, float | str]
type MetricsPayload = dict[str, MetricPayload]
type ThresholdPayload = dict[str, float]
type CheckPayload = dict[str, bool]


def _get_vars(options: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if options is None:
        return {}
    vars_value = options.get("vars")
    if isinstance(vars_value, Mapping):
        return cast(Mapping[str, Any], vars_value)
    config_value = options.get("config")
    if isinstance(config_value, Mapping):
        config_vars = config_value.get("vars")
        if isinstance(config_vars, Mapping):
            return cast(Mapping[str, Any], config_vars)
    return {}


def _fixture_candidates(fixture: str) -> list[Path]:
    fixture_path = Path(fixture)
    if fixture_path.is_absolute():
        return [fixture_path]

    fixtures_dir = Path(__file__).parent / "fixtures"
    with_suffix = fixture_path if fixture_path.suffix else fixture_path.with_suffix(".json")
    candidates = [fixtures_dir / with_suffix]

    if len(fixture_path.parts) == 1:
        memory_cue_path = Path("memory_cues") / with_suffix.name
        candidates.append(fixtures_dir / memory_cue_path)

    return candidates


def _load_fixture(fixture: str) -> dict[str, Any]:
    for candidate in _fixture_candidates(fixture):
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"fixture must contain a JSON object: {candidate}")
            return {str(key): value for key, value in raw.items()}
    paths = ", ".join(str(path) for path in _fixture_candidates(fixture))
    raise FileNotFoundError(f"memory cue retrieval fixture not found: {paths}")


def _required_str(raw: Mapping[str, Any], field_name: str) -> str:
    value = raw[field_name]
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _string_list(raw: Mapping[str, Any], field_name: str) -> list[str]:
    value = raw.get(field_name, [])
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(item) for item in value]


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _mapping_list(raw: Mapping[str, Any], field_name: str) -> list[Mapping[str, Any]]:
    value = raw.get(field_name, [])
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [_mapping(item, field_name) for item in value]


def _memory_concepts(raw: Mapping[str, Any], field_name: str) -> list[MemoryConcept]:
    return [MemoryConcept(item) for item in _string_list(raw, field_name)]


def _quality_flags(raw: Mapping[str, Any]) -> list[CueQualityFlag]:
    return [CueQualityFlag(item) for item in _string_list(raw, "quality_flags")]


def _retrieval_cue(raw: Mapping[str, Any]) -> RetrievalCue:
    return RetrievalCue(
        text=_required_str(raw, "text"),
        kind=CueKind(str(raw.get("kind", CueKind.USER_PHRASE))),
        source=CueSource(str(raw.get("source", CueSource.USER))),
        confidence=float(raw.get("confidence", 1.0)),
    )


def _memory_cue_metadata(raw: Mapping[str, Any]) -> MemoryCueMetadata:
    return MemoryCueMetadata(
        schema_version=str(raw.get("schema_version", "cue.v1")),
        generator_version=str(raw.get("generator_version", "record-cue-smoke-v1")),
        concepts=_memory_concepts(raw, "concepts"),
        retrieval_cues=[_retrieval_cue(item) for item in _mapping_list(raw, "retrieval_cues")],
        files=_string_list(raw, "files"),
        symbols=_string_list(raw, "symbols"),
        generation_status=CueGenerationStatus(
            str(raw.get("generation_status", CueGenerationStatus.GENERATED))
        ),
        quality_flags=_quality_flags(raw),
    )


def _query_cue(raw: Mapping[str, Any]) -> QueryCue:
    return QueryCue(
        schema_version=str(raw.get("schema_version", "cue.v1")),
        interpreter_version=str(raw.get("interpreter_version", "query-cue-smoke-v1")),
        recall_need=RecallNeed(str(raw.get("recall_need", RecallNeed.STRONG))),
        concepts=_memory_concepts(raw, "concepts"),
        cue_phrases=[_retrieval_cue(item) for item in _mapping_list(raw, "cue_phrases")],
        file_hints=_string_list(raw, "file_hints"),
        symbol_hints=_string_list(raw, "symbol_hints"),
        kind_hints=[],
        scope_hint=None,
        uncertainty=float(raw.get("uncertainty", 0.0)),
        fallback_used=bool(raw.get("fallback_used", False)),
        quality_flags=_quality_flags(raw),
    )


def _records(fixture: Mapping[str, Any]) -> list[RetrievalMemoryRecord]:
    records: list[RetrievalMemoryRecord] = []
    for raw_record in _mapping_list(fixture, "records"):
        metadata_value = raw_record.get("cue_metadata")
        cue_metadata = (
            None
            if metadata_value is None
            else _memory_cue_metadata(_mapping(metadata_value, "cue_metadata"))
        )
        records.append(
            RetrievalMemoryRecord(
                memory_id=_required_str(raw_record, "memory_id"),
                name=str(raw_record.get("name", "")),
                description=str(raw_record.get("description", "")),
                content=str(raw_record.get("content", "")),
                cue_metadata=cue_metadata,
            )
        )
    return records


def _cases(fixture: Mapping[str, Any]) -> list[RetrievalEvalCase]:
    cases: list[RetrievalEvalCase] = []
    for raw_case in _mapping_list(fixture, "cases"):
        query_cue_value = raw_case.get("query_cue")
        query_cue = (
            None
            if query_cue_value is None
            else _query_cue(_mapping(query_cue_value, "query_cue"))
        )
        cases.append(
            RetrievalEvalCase(
                query=_required_str(raw_case, "query"),
                expected_memory_ids=_string_list(raw_case, "expected_memory_ids"),
                query_cue=query_cue,
                k=int(raw_case.get("k", 8)),
            )
        )
    return cases


def _thresholds(fixture: Mapping[str, Any]) -> ThresholdPayload:
    raw_thresholds = _mapping(fixture.get("thresholds", {}), "thresholds")
    return {str(key): float(value) for key, value in raw_thresholds.items()}


def _metric_to_dict(
    metric_at_8: RetrievalVariantMetrics,
    metric_at_3: RetrievalVariantMetrics,
) -> MetricPayload:
    return {
        "variant": str(metric_at_8.variant),
        "recall_at_k": metric_at_8.recall_at_k,
        "recall_at_8": metric_at_8.recall_at_k,
        "recall_at_3": metric_at_3.recall_at_k,
        "mrr": metric_at_8.mrr,
        "mrr_at_8": metric_at_8.mrr,
        "mrr_at_3": metric_at_3.mrr,
        "noise_at_k": metric_at_8.noise_at_k,
        "noise_at_8": metric_at_8.noise_at_k,
        "noise_at_3": metric_at_3.noise_at_k,
        "recall_lift": metric_at_8.recall_lift,
        "mrr_lift": metric_at_8.mrr_lift,
    }


def _metrics(
    records: list[RetrievalMemoryRecord],
    cases: list[RetrievalEvalCase],
) -> MetricsPayload:
    metrics_at_8 = evaluate_retrieval_variants(records, cases, k=8)
    metrics_at_3 = evaluate_retrieval_variants(records, cases, k=3)
    return {
        str(variant): _metric_to_dict(metrics_at_8[variant], metrics_at_3[variant])
        for variant in RetrievalVariant
    }


def _metric_float(metrics: MetricsPayload, variant: str, field_name: str) -> float:
    value = metrics[variant][field_name]
    if not isinstance(value, int | float):
        raise ValueError(f"{variant}.{field_name} must be numeric")
    return float(value)


def _evaluate_thresholds(
    metrics: MetricsPayload,
    thresholds: ThresholdPayload,
) -> tuple[CheckPayload, bool]:
    checks = {
        "record_query_cues_recall_at_8_min": _metric_float(
            metrics,
            "record_query_cues",
            "recall_at_8",
        )
        >= thresholds.get("record_query_cues_recall_at_8_min", 0.0),
        "record_query_cues_recall_at_3_min": _metric_float(
            metrics,
            "record_query_cues",
            "recall_at_3",
        )
        >= thresholds.get("record_query_cues_recall_at_3_min", 0.0),
        "record_query_cues_mrr_min": _metric_float(metrics, "record_query_cues", "mrr")
        >= thresholds.get("record_query_cues_mrr_min", 0.0),
        "record_query_cues_noise_at_8_max": _metric_float(
            metrics,
            "record_query_cues",
            "noise_at_8",
        )
        <= thresholds.get("record_query_cues_noise_at_8_max", 1.0),
        "record_query_cues_mrr_lift_min": _metric_float(
            metrics,
            "record_query_cues",
            "mrr_lift",
        )
        >= thresholds.get("record_query_cues_mrr_lift_min", 0.0),
    }
    return checks, all(checks.values())


def call_api(
    prompt: str,
    options: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Run deterministic retrieval smoke metrics for promptfoo."""
    del prompt, context

    vars_ = _get_vars(options)
    fixture_name = str(vars_.get("fixture") or DEFAULT_FIXTURE)
    fixture = _load_fixture(fixture_name)
    records = _records(fixture)
    cases = _cases(fixture)
    thresholds = _thresholds(fixture)
    metrics = _metrics(records, cases)
    checks, passed = _evaluate_thresholds(metrics, thresholds)

    return {
        "output": json.dumps(
            {
                "fixture": fixture_name,
                "record_count": len(records),
                "case_count": len(cases),
                "metrics": metrics,
                "thresholds": thresholds,
                "checks": checks,
                "passed": passed,
            },
            sort_keys=True,
        )
    }
