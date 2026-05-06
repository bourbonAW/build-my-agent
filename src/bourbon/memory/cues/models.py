"""Structured cue metadata models for Bourbon memory."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Self

if TYPE_CHECKING:
    from bourbon.memory.models import MemoryKind, MemoryScope


class MemoryConcept(StrEnum):
    USER_PREFERENCE = "user_preference"
    BEHAVIOR_RULE = "behavior_rule"
    PROJECT_CONTEXT = "project_context"
    ARCHITECTURE_DECISION = "architecture_decision"
    IMPLEMENTATION_PATTERN = "implementation_pattern"
    WORKFLOW = "workflow"
    RISK_OR_LESSON = "risk_or_lesson"
    TRADE_OFF = "trade_off"
    HOW_IT_WORKS = "how_it_works"
    EXTERNAL_REFERENCE = "external_reference"


class CueKind(StrEnum):
    USER_PHRASE = "user_phrase"
    TASK_PHRASE = "task_phrase"
    PROBLEM_PHRASE = "problem_phrase"
    FILE_OR_SYMBOL = "file_or_symbol"
    DECISION_QUESTION = "decision_question"
    SYNONYM = "synonym"


class CueSource(StrEnum):
    LLM = "llm"
    RUNTIME = "runtime"
    USER = "user"
    BACKFILL = "backfill"


class CueGenerationStatus(StrEnum):
    GENERATED = "generated"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_RUN = "not_run"


class RecallNeed(StrEnum):
    NONE = "none"
    WEAK = "weak"
    STRONG = "strong"


class TimeHint(StrEnum):
    NONE = "none"
    RECENT = "recent"
    LAST_SESSION = "last_session"
    OLDER = "older"
    EXPLICIT_RANGE = "explicit_range"


class CueQualityFlag(StrEnum):
    LLM_GENERATION_FAILED = "llm_generation_failed"
    LLM_INTERPRETATION_FAILED = "llm_interpretation_failed"
    PARTIAL_OUTPUT = "partial_output"
    LOW_CUE_COVERAGE = "low_cue_coverage"
    NO_DECISION_QUESTION_CUE = "no_decision_question_cue"
    MISSING_RUNTIME_FILE_CUE = "missing_runtime_file_cue"
    OVERBROAD_CUE = "overbroad_cue"
    CONCEPT_MISMATCH = "concept_mismatch"
    INVALID_FILE_HINT = "invalid_file_hint"
    MALFORMED_CUE_METADATA = "malformed_cue_metadata"
    FALLBACK_USED = "fallback_used"


@dataclass(frozen=True)
class DomainConcept:
    namespace: str
    value: str
    source: Literal["skill", "project", "user"]
    schema_version: str

    def __post_init__(self) -> None:
        if self.source not in {"skill", "project", "user"}:
            raise ValueError("domain concept source must be skill, project, or user")
        if self.source in {"skill", "project"} and not self.namespace.strip():
            raise ValueError("namespace is required for skill/project domain concepts")
        if not self.value.strip():
            raise ValueError("value is required for domain concepts")
        if not self.schema_version.startswith("cue.v"):
            raise ValueError("schema_version must start with cue.v")

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.value}" if self.namespace else self.value

    def to_frontmatter(self) -> dict[str, str]:
        return {
            "namespace": self.namespace,
            "value": self.value,
            "source": self.source,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_frontmatter(cls, raw: dict[str, Any]) -> Self:
        if not isinstance(raw, dict):
            raise ValueError("domain concept frontmatter must be a mapping")
        return cls(
            namespace=str(raw.get("namespace", "")),
            value=str(raw["value"]),
            source=raw["source"],
            schema_version=str(raw["schema_version"]),
        )


@dataclass(frozen=True)
class RetrievalCue:
    text: str
    kind: CueKind
    source: CueSource
    confidence: float

    def __post_init__(self) -> None:
        normalized = self.text.strip()
        if not normalized:
            raise ValueError("retrieval cue text must be non-empty")
        if len(normalized) > 80:
            raise ValueError("retrieval cue text must be <= 80 characters")
        if not math.isfinite(self.confidence) or self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError("retrieval cue confidence must be between 0.0 and 1.0")
        object.__setattr__(self, "text", normalized)

    def to_frontmatter(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "kind": str(self.kind),
            "source": str(self.source),
            "confidence": self.confidence,
        }

    @classmethod
    def from_frontmatter(cls, raw: dict[str, Any]) -> Self:
        if not isinstance(raw, dict):
            raise ValueError("retrieval cue frontmatter must be a mapping")
        return cls(
            text=str(raw["text"]),
            kind=CueKind(raw["kind"]),
            source=CueSource(raw["source"]),
            confidence=float(raw["confidence"]),
        )


@dataclass(frozen=True)
class MemoryCueMetadata:
    schema_version: str
    generator_version: str
    concepts: list[MemoryConcept]
    retrieval_cues: list[RetrievalCue]
    files: list[str]
    symbols: list[str]
    generation_status: CueGenerationStatus
    domain_concepts: list[DomainConcept] = field(default_factory=list)
    generated_at: datetime | None = None
    quality_flags: list[CueQualityFlag] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.schema_version.startswith("cue.v"):
            raise ValueError("schema_version must start with cue.v")
        if not self.generator_version:
            raise ValueError("generator_version is required")
        if not 1 <= len(self.concepts) <= 3:
            raise ValueError("concepts must contain 1-3 MemoryConcept values")
        if len(self.domain_concepts) > 5:
            raise ValueError("domain_concepts must contain at most 5 values")
        if not self.retrieval_cues:
            raise ValueError("retrieval_cues must be non-empty")
        if len(self.retrieval_cues) > 8:
            raise ValueError("retrieval_cues must contain at most 8 values")

    def to_frontmatter(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "generation_status": str(self.generation_status),
            "concepts": [str(item) for item in self.concepts],
            "domain_concepts": [item.to_frontmatter() for item in self.domain_concepts],
            "retrieval_cues": [item.to_frontmatter() for item in self.retrieval_cues],
            "files": list(self.files),
            "symbols": list(self.symbols),
            "quality_flags": [str(item) for item in self.quality_flags],
        }
        if self.generated_at is not None:
            raw["generated_at"] = self.generated_at.isoformat()
        return raw

    @classmethod
    def from_frontmatter(cls, raw: dict[str, Any]) -> Self:
        if not isinstance(raw, dict):
            raise ValueError("cue metadata frontmatter must be a mapping")
        concepts = raw.get("concepts", [])
        domain_concepts = raw.get("domain_concepts", [])
        retrieval_cues = raw.get("retrieval_cues", [])
        files = raw.get("files", [])
        symbols = raw.get("symbols", [])
        quality_flags = raw.get("quality_flags", [])
        for field_name, value in (
            ("concepts", concepts),
            ("domain_concepts", domain_concepts),
            ("retrieval_cues", retrieval_cues),
            ("files", files),
            ("symbols", symbols),
            ("quality_flags", quality_flags),
        ):
            if not isinstance(value, list):
                raise ValueError(f"{field_name} must be a list")
        generated_at = raw.get("generated_at")
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at)
        return cls(
            schema_version=str(raw["schema_version"]),
            generator_version=str(raw["generator_version"]),
            concepts=[MemoryConcept(item) for item in concepts],
            domain_concepts=[
                DomainConcept.from_frontmatter(item)
                for item in domain_concepts
            ],
            retrieval_cues=[
                RetrievalCue.from_frontmatter(item)
                for item in retrieval_cues
            ],
            files=[str(item) for item in files],
            symbols=[str(item) for item in symbols],
            generation_status=CueGenerationStatus(raw["generation_status"]),
            generated_at=generated_at,
            quality_flags=[CueQualityFlag(item) for item in quality_flags],
        )


def _dedupe_normalized_strings(items: list[Any], field_name: str) -> list[str]:
    if not isinstance(items, list):
        raise ValueError(f"{field_name} must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"{field_name} must be a datetime or ISO datetime string")


def _normalize_time_range(raw: Any, time_hint: TimeHint) -> tuple[datetime, datetime] | None:
    if raw is None:
        if time_hint == TimeHint.EXPLICIT_RANGE:
            raise ValueError("time_range is required for explicit_range time_hint")
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError("time_range must contain exactly two datetimes")
    start = _parse_datetime(raw[0], "time_range start")
    end = _parse_datetime(raw[1], "time_range end")
    if start > end:
        raise ValueError("time_range start must be before or equal to end")
    return (start, end)


def _coerce_memory_kind(value: Any) -> Any:
    from bourbon.memory.models import MemoryKind

    return MemoryKind(value)


def _coerce_memory_scope(value: Any) -> Any:
    from bourbon.memory.models import MemoryScope

    return MemoryScope(value)


@dataclass(frozen=True)
class QueryCue:
    schema_version: str
    interpreter_version: str
    recall_need: RecallNeed
    concepts: list[MemoryConcept]
    cue_phrases: list[RetrievalCue]
    file_hints: list[str]
    symbol_hints: list[str]
    kind_hints: list[MemoryKind]
    scope_hint: MemoryScope | None
    uncertainty: float
    domain_concepts: list[DomainConcept] = field(default_factory=list)
    time_hint: TimeHint = TimeHint.NONE
    time_range: tuple[datetime, datetime] | None = None
    generated_at: datetime | None = None
    fallback_used: bool = False
    quality_flags: list[CueQualityFlag] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.schema_version.startswith("cue.v"):
            raise ValueError("schema_version must start with cue.v")
        if not self.interpreter_version:
            raise ValueError("interpreter_version is required")
        if not isinstance(self.concepts, list):
            raise ValueError("concepts must be a list")
        if len(self.concepts) > 3:
            raise ValueError("concepts must contain at most 3 MemoryConcept values")
        if not isinstance(self.domain_concepts, list):
            raise ValueError("domain_concepts must be a list")
        if len(self.domain_concepts) > 5:
            raise ValueError("domain_concepts must contain at most 5 values")
        if not isinstance(self.cue_phrases, list):
            raise ValueError("cue_phrases must be a list")
        if len(self.cue_phrases) > 8:
            raise ValueError("cue_phrases must contain at most 8 values")
        if not isinstance(self.kind_hints, list):
            raise ValueError("kind_hints must be a list")
        if not isinstance(self.quality_flags, list):
            raise ValueError("quality_flags must be a list")
        if (
            not math.isfinite(self.uncertainty)
            or self.uncertainty < 0.0
            or self.uncertainty > 1.0
        ):
            raise ValueError("uncertainty must be between 0.0 and 1.0")

        recall_need = RecallNeed(self.recall_need)
        concepts = [MemoryConcept(item) for item in self.concepts]
        domain_concepts = [
            item if isinstance(item, DomainConcept) else DomainConcept.from_frontmatter(item)
            for item in self.domain_concepts
        ]
        cue_phrases = [
            item if isinstance(item, RetrievalCue) else RetrievalCue.from_frontmatter(item)
            for item in self.cue_phrases
        ]
        kind_hints = self._normalize_kind_hints(self.kind_hints)
        scope_hint = None if self.scope_hint is None else _coerce_memory_scope(self.scope_hint)
        time_hint = TimeHint(self.time_hint)
        time_range = _normalize_time_range(self.time_range, time_hint)
        generated_at = (
            None
            if self.generated_at is None
            else _parse_datetime(self.generated_at, "generated_at")
        )
        quality_flags = [CueQualityFlag(item) for item in self.quality_flags]
        if (
            not self.fallback_used
            and (
                CueQualityFlag.FALLBACK_USED in quality_flags
                or CueQualityFlag.LLM_INTERPRETATION_FAILED in quality_flags
            )
        ):
            raise ValueError("fallback_used must be true when fallback quality flags are present")

        object.__setattr__(self, "recall_need", recall_need)
        object.__setattr__(self, "concepts", concepts)
        object.__setattr__(self, "domain_concepts", domain_concepts)
        object.__setattr__(self, "cue_phrases", cue_phrases)
        object.__setattr__(
            self,
            "file_hints",
            _dedupe_normalized_strings(self.file_hints, "file_hints"),
        )
        object.__setattr__(
            self,
            "symbol_hints",
            _dedupe_normalized_strings(self.symbol_hints, "symbol_hints"),
        )
        object.__setattr__(self, "kind_hints", kind_hints)
        object.__setattr__(self, "scope_hint", scope_hint)
        object.__setattr__(self, "time_hint", time_hint)
        object.__setattr__(self, "time_range", time_range)
        object.__setattr__(self, "generated_at", generated_at)
        object.__setattr__(self, "quality_flags", quality_flags)

    @staticmethod
    def _normalize_kind_hints(items: list[Any]) -> list[Any]:
        normalized: list[Any] = []
        seen: set[str] = set()
        for item in items:
            kind = _coerce_memory_kind(item)
            value = str(kind)
            if value in seen:
                continue
            normalized.append(kind)
            seen.add(value)
        return normalized

    def to_frontmatter(self) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "schema_version": self.schema_version,
            "interpreter_version": self.interpreter_version,
            "recall_need": str(self.recall_need),
            "concepts": [str(item) for item in self.concepts],
            "domain_concepts": [item.to_frontmatter() for item in self.domain_concepts],
            "cue_phrases": [item.to_frontmatter() for item in self.cue_phrases],
            "file_hints": list(self.file_hints),
            "symbol_hints": list(self.symbol_hints),
            "kind_hints": [str(item) for item in self.kind_hints],
            "scope_hint": None if self.scope_hint is None else str(self.scope_hint),
            "uncertainty": self.uncertainty,
            "time_hint": str(self.time_hint),
            "fallback_used": self.fallback_used,
            "quality_flags": [str(item) for item in self.quality_flags],
        }
        if self.time_range is not None:
            raw["time_range"] = [
                self.time_range[0].isoformat(),
                self.time_range[1].isoformat(),
            ]
        if self.generated_at is not None:
            raw["generated_at"] = self.generated_at.isoformat()
        return raw

    @classmethod
    def from_frontmatter(cls, raw: dict[str, Any]) -> Self:
        if not isinstance(raw, dict):
            raise ValueError("query cue frontmatter must be a mapping")
        concepts = raw.get("concepts", [])
        domain_concepts = raw.get("domain_concepts", [])
        cue_phrases = raw.get("cue_phrases", [])
        file_hints = raw.get("file_hints", [])
        symbol_hints = raw.get("symbol_hints", [])
        kind_hints = raw.get("kind_hints", [])
        quality_flags = raw.get("quality_flags", [])
        for field_name, value in (
            ("concepts", concepts),
            ("domain_concepts", domain_concepts),
            ("cue_phrases", cue_phrases),
            ("file_hints", file_hints),
            ("symbol_hints", symbol_hints),
            ("kind_hints", kind_hints),
            ("quality_flags", quality_flags),
        ):
            if not isinstance(value, list):
                raise ValueError(f"{field_name} must be a list")
        return cls(
            schema_version=str(raw["schema_version"]),
            interpreter_version=str(raw["interpreter_version"]),
            recall_need=RecallNeed(raw["recall_need"]),
            concepts=[MemoryConcept(item) for item in concepts],
            domain_concepts=[
                DomainConcept.from_frontmatter(item)
                for item in domain_concepts
            ],
            cue_phrases=[
                RetrievalCue.from_frontmatter(item)
                for item in cue_phrases
            ],
            file_hints=[str(item) for item in file_hints],
            symbol_hints=[str(item) for item in symbol_hints],
            kind_hints=[_coerce_memory_kind(item) for item in kind_hints],
            scope_hint=(
                None
                if raw.get("scope_hint") is None
                else _coerce_memory_scope(raw["scope_hint"])
            ),
            uncertainty=float(raw["uncertainty"]),
            time_hint=TimeHint(raw.get("time_hint", TimeHint.NONE)),
            time_range=raw.get("time_range"),
            generated_at=raw.get("generated_at"),
            fallback_used=bool(raw.get("fallback_used", False)),
            quality_flags=[CueQualityFlag(item) for item in quality_flags],
        )
