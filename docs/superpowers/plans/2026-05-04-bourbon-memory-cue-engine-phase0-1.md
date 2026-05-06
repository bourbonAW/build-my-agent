# Bourbon Memory Cue Engine Phase 0/1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 0/1 foundation for Bourbon memory cue metadata: typed cue models, durable frontmatter compatibility, runtime evidence extraction, record-side cue generation, and a deterministic eval harness.

**Architecture:** Add a focused `bourbon.memory.cues` package for cue-specific models, runtime context, record generation, and eval helpers. Keep `MemoryManager` and `MemoryStore` as the integration boundaries: records gain optional `cue_metadata`, store persists it as nested YAML, and manager optionally calls `CueEngine.generate_for_record()` on writes. Query-side interpretation, ranking changes, embedding, and background workers remain out of scope for this plan.

**Tech Stack:** Python dataclasses, `StrEnum`, YAML frontmatter, pytest, existing file-first memory store, existing `uv run pytest` test command.

---

## Implementation Status

**Phase:** Phase 0/1

**Status:** Completed with type-check caveat

**Started:** 2026-05-05

**Completed:** 2026-05-05

**Verification:** Pytest and ruff passed; cue subpackage mypy passed. Broad mypy over `src/bourbon/memory src/bourbon/tools/__init__.py src/bourbon/agent.py` failed on existing `config.py`/`agent.py` type debt and missing `toml` stubs.

**Task Progress:**

- [x] Task 1: Add Cue Model Types
- [x] Task 2: Persist Cue Metadata In MemoryStore
- [x] Task 3: Add Cue Runtime Context Adapter
- [x] Task 4: Implement Deterministic Record-Side CueEngine
- [x] Task 5: Add Memory Cue Configuration
- [x] Task 6: Integrate CueEngine Into MemoryManager Writes
- [x] Task 7: Add Deterministic Cue Eval Harness
- [x] Task 8: Final Verification And Spec Alignment

**Completion Notes:**

- 2026-05-05: Phase 0/1 execution started with subagent-driven implementation.
- 2026-05-05: Phase 0/1 implementation completed. Final focused verification: `uv run pytest tests/test_memory_cue_models.py tests/test_memory_cue_runtime.py tests/test_memory_cue_engine.py tests/test_memory_cue_eval.py -q` -> 22 passed; memory regression suite -> 102 passed; focused ruff -> passed; `uv run mypy src/bourbon/memory/cues` -> passed.
- 2026-05-05: Broad mypy command from this plan still fails with existing project type debt in `config.py` and `agent.py`; not treated as Phase 0/1 blocker because focused cue mypy, pytest, and ruff pass.

---

## Scope

This plan implements:

- Phase 0 cue model tests and deterministic eval helper.
- Phase 1 record-side `MemoryCueMetadata`.
- Runtime-first cue generation without depending on live LLM calls.
- Store read/write compatibility with old memory files.
- Manager integration behind config flags.

This plan does not implement:

- Query-side `QueryCue` execution in `memory_search`.
- Search/ranking changes beyond durable cue text becoming grep-searchable in frontmatter.
- Real model invocation for cue generation.
- Deferred worker queue.
- Promptfoo YAML evals.

The deliberate constraint is important: first prove cue representation and persistence are stable before adding query-side latency and ranking complexity.

## File Map

- Create: `src/bourbon/memory/cues/__init__.py`
- Create: `src/bourbon/memory/cues/models.py`
- Create: `src/bourbon/memory/cues/runtime.py`
- Create: `src/bourbon/memory/cues/engine.py`
- Create: `src/bourbon/memory/cues/eval.py`
- Modify: `src/bourbon/memory/models.py`
- Modify: `src/bourbon/memory/store.py`
- Modify: `src/bourbon/memory/manager.py`
- Modify: `src/bourbon/config.py`
- Modify: `src/bourbon/tools/__init__.py`
- Test: `tests/test_memory_cue_models.py`
- Test: `tests/test_memory_cue_runtime.py`
- Test: `tests/test_memory_cue_engine.py`
- Test: `tests/test_memory_cue_eval.py`
- Test: `tests/test_memory_store.py`
- Test: `tests/test_memory_manager.py`
- Test: `tests/test_memory_config.py`
- Test: `tests/test_memory_agent_integration.py`

---

## Task 1: Add Cue Model Types

**Files:**

- Create: `src/bourbon/memory/cues/__init__.py`
- Create: `src/bourbon/memory/cues/models.py`
- Modify: `src/bourbon/memory/models.py`
- Test: `tests/test_memory_cue_models.py`
- Test: `tests/test_memory_models.py`

- [ ] **Step 1: Write failing cue model tests**

Create `tests/test_memory_cue_models.py`:

```python
"""Tests for bourbon.memory.cues.models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    DomainConcept,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)


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
```

- [ ] **Step 2: Run failing cue model tests**

Run:

```bash
uv run pytest tests/test_memory_cue_models.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'bourbon.memory.cues'`.

- [ ] **Step 3: Implement cue model package**

Create `src/bourbon/memory/cues/__init__.py`:

```python
"""Memory cue representation layer."""

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    DomainConcept,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)

__all__ = [
    "CueGenerationStatus",
    "CueKind",
    "CueQualityFlag",
    "CueSource",
    "DomainConcept",
    "MemoryConcept",
    "MemoryCueMetadata",
    "RetrievalCue",
]
```

Create `src/bourbon/memory/cues/models.py`:

```python
"""Structured cue metadata models for Bourbon memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal


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
    def from_frontmatter(cls, raw: dict[str, Any]) -> "DomainConcept":
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
        if self.confidence < 0.0 or self.confidence > 1.0:
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
    def from_frontmatter(cls, raw: dict[str, Any]) -> "RetrievalCue":
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
    def from_frontmatter(cls, raw: dict[str, Any]) -> "MemoryCueMetadata":
        generated_at = raw.get("generated_at")
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at)
        return cls(
            schema_version=str(raw["schema_version"]),
            generator_version=str(raw["generator_version"]),
            concepts=[MemoryConcept(item) for item in raw.get("concepts", [])],
            domain_concepts=[
                DomainConcept.from_frontmatter(item)
                for item in raw.get("domain_concepts", [])
            ],
            retrieval_cues=[
                RetrievalCue.from_frontmatter(item)
                for item in raw.get("retrieval_cues", [])
            ],
            files=[str(item) for item in raw.get("files", [])],
            symbols=[str(item) for item in raw.get("symbols", [])],
            generation_status=CueGenerationStatus(raw["generation_status"]),
            generated_at=generated_at,
            quality_flags=[CueQualityFlag(item) for item in raw.get("quality_flags", [])],
        )
```

- [ ] **Step 4: Add optional cue metadata to memory record model**

Modify `src/bourbon/memory/models.py`.

Add this import under existing memory imports:

```python
from bourbon.memory.cues.models import MemoryCueMetadata
```

Add `cue_metadata` to `MemoryRecord` after `source_ref`:

```python
@dataclass
class MemoryRecord:
    """A persisted memory record with full metadata."""

    id: str
    name: str
    description: str
    kind: MemoryKind
    scope: MemoryScope
    confidence: float
    source: MemorySource
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    created_by: str
    content: str
    source_ref: SourceRef | None = None
    cue_metadata: MemoryCueMetadata | None = None
```

Append this test to `tests/test_memory_models.py`:

```python
def test_memory_record_accepts_optional_cue_metadata() -> None:
    from bourbon.memory.cues.models import (
        CueGenerationStatus,
        CueKind,
        CueSource,
        MemoryConcept,
        MemoryCueMetadata,
        RetrievalCue,
    )

    metadata = MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text="pytest preference",
                kind=CueKind.USER_PHRASE,
                source=CueSource.USER,
                confidence=1.0,
            )
        ],
        files=[],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
    )
    record = MemoryRecord(
        id="mem_abc12345",
        name="test",
        description="test",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemStatus.ACTIVE,
        created_at=datetime(2026, 4, 20, tzinfo=UTC),
        updated_at=datetime(2026, 4, 20, tzinfo=UTC),
        created_by="user",
        content="Use pytest.",
        source_ref=SourceRef(kind="manual"),
        cue_metadata=metadata,
    )

    assert record.cue_metadata is metadata
```

- [ ] **Step 5: Run model tests**

Run:

```bash
uv run pytest tests/test_memory_cue_models.py tests/test_memory_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/cues/__init__.py src/bourbon/memory/cues/models.py src/bourbon/memory/models.py tests/test_memory_cue_models.py tests/test_memory_models.py
git commit -m "feat(memory): add cue metadata models"
```

---

## Task 2: Persist Cue Metadata In MemoryStore

**Files:**

- Modify: `src/bourbon/memory/store.py`
- Test: `tests/test_memory_store.py`

- [ ] **Step 1: Add failing store tests**

Append to `tests/test_memory_store.py`:

```python
def test_store_persists_cue_metadata_frontmatter(tmp_path: Path) -> None:
    from bourbon.memory.cues.models import (
        CueGenerationStatus,
        CueKind,
        CueSource,
        MemoryConcept,
        MemoryCueMetadata,
        RetrievalCue,
    )

    store = MemoryStore(memory_dir=tmp_path)
    metadata = MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.ARCHITECTURE_DECISION],
        retrieval_cues=[
            RetrievalCue(
                text="why cue metadata",
                kind=CueKind.DECISION_QUESTION,
                source=CueSource.LLM,
                confidence=0.8,
            ),
            RetrievalCue(
                text="src/bourbon/memory/store.py",
                kind=CueKind.FILE_OR_SYMBOL,
                source=CueSource.RUNTIME,
                confidence=1.0,
            ),
        ],
        files=["src/bourbon/memory/store.py"],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
    )
    record = _make_record(
        id="mem_cue00001",
        name="Cue metadata",
        content="Store cue metadata in frontmatter.",
    )
    record.cue_metadata = metadata

    store.write_record(record)
    raw_text = (tmp_path / _record_to_filename(record)).read_text(encoding="utf-8")
    loaded = store.read_record(record.id)

    assert "cue_metadata:" in raw_text
    assert "why cue metadata" in raw_text
    assert loaded is not None
    assert loaded.cue_metadata == metadata


def test_store_reads_old_record_without_cue_metadata(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_old00001", name="Old record")

    store.write_record(record)
    loaded = store.read_record(record.id)

    assert loaded is not None
    assert loaded.cue_metadata is None


def test_store_ignores_malformed_cue_metadata_without_losing_record(tmp_path: Path) -> None:
    store = MemoryStore(memory_dir=tmp_path)
    record = _make_record(id="mem_badcue1", name="Bad cue")
    store.write_record(record)
    path = tmp_path / _record_to_filename(record)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "created_by: user\n",
        "created_by: user\ncue_metadata:\n  schema_version: cue.v1\n  retrieval_cues: not-a-list\n",
    )
    path.write_text(text, encoding="utf-8")

    loaded = store.read_record(record.id)

    assert loaded is not None
    assert loaded.id == "mem_badcue1"
    assert loaded.cue_metadata is None


def test_store_ignores_malformed_yaml_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "project_bad_mem_bad00001.md"
    path.write_text("---\nid: [unterminated\n---\n\nBody remains readable.\n", encoding="utf-8")
    store = MemoryStore(memory_dir=tmp_path)

    assert store.list_records() == []
```

- [ ] **Step 2: Run failing store tests**

Run:

```bash
uv run pytest tests/test_memory_store.py::test_store_persists_cue_metadata_frontmatter tests/test_memory_store.py::test_store_reads_old_record_without_cue_metadata tests/test_memory_store.py::test_store_ignores_malformed_cue_metadata_without_losing_record tests/test_memory_store.py::test_store_ignores_malformed_yaml_frontmatter -q
```

Expected: FAIL because `cue_metadata` is not serialized/deserialized and malformed YAML is not caught.

- [ ] **Step 3: Implement cue metadata store serialization**

Modify imports in `src/bourbon/memory/store.py`:

```python
from bourbon.memory.cues.models import MemoryCueMetadata
```

In `_record_to_frontmatter()`, before `return fm`, add:

```python
    if record.cue_metadata:
        fm["cue_metadata"] = record.cue_metadata.to_frontmatter()
```

Add this helper above `_frontmatter_to_record()`:

```python
def _parse_optional_cue_metadata(fm: dict[str, Any]) -> MemoryCueMetadata | None:
    """Parse optional cue metadata without making record parsing fragile."""
    raw = fm.get("cue_metadata")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return MemoryCueMetadata.from_frontmatter(raw)
    except (KeyError, TypeError, ValueError):
        return None
```

In `_frontmatter_to_record()`, pass cue metadata into `MemoryRecord`:

```python
        content=body.strip(),
        source_ref=source_ref,
        cue_metadata=_parse_optional_cue_metadata(fm),
```

- [ ] **Step 4: Make `_parse_file()` tolerant of malformed YAML**

Replace `MemoryStore._parse_file()` with:

```python
    def _parse_file(self, path: Path) -> tuple[dict[str, Any], str]:
        """Parse a memory file into (frontmatter_dict, body_str)."""
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}, parts[2]
        if not isinstance(fm, dict):
            return {}, parts[2]
        body = parts[2]
        return fm, body
```

- [ ] **Step 5: Run store tests**

Run:

```bash
uv run pytest tests/test_memory_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/store.py tests/test_memory_store.py
git commit -m "feat(memory): persist cue metadata in store"
```

---

## Task 3: Add Cue Runtime Context Adapter

**Files:**

- Create: `src/bourbon/memory/cues/runtime.py`
- Modify: `src/bourbon/memory/cues/__init__.py`
- Modify: `src/bourbon/tools/__init__.py`
- Test: `tests/test_memory_cue_runtime.py`

- [ ] **Step 1: Write failing runtime adapter tests**

Create `tests/test_memory_cue_runtime.py`:

```python
"""Tests for cue runtime context extraction."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.cues.runtime import (
    CueRuntimeContext,
    build_runtime_context_from_messages,
    extract_paths_from_tool_input,
)
from bourbon.memory.models import SourceRef


def test_extract_paths_from_tool_input_handles_common_tool_shapes() -> None:
    assert extract_paths_from_tool_input({"file_path": "src/bourbon/memory/store.py"}) == [
        "src/bourbon/memory/store.py"
    ]
    assert extract_paths_from_tool_input({"path": "src/bourbon"}) == ["src/bourbon"]
    assert extract_paths_from_tool_input({"pattern": "src/**/*.py"}) == []


def test_build_runtime_context_from_recent_tool_uses() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Read",
                    "input": {"file_path": "src/bourbon/memory/store.py"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "edit_file",
                    "input": {"file_path": "src/bourbon/memory/manager.py"},
                },
            ],
        }
    ]

    ctx = build_runtime_context_from_messages(
        messages,
        workdir=Path("/repo"),
        source_ref=SourceRef(kind="file", file_path="src/bourbon/memory/models.py"),
        session_id="ses_1",
        task_subject="memory cue engine",
    )

    assert ctx.current_files == [
        "src/bourbon/memory/manager.py",
        "src/bourbon/memory/store.py",
    ]
    assert ctx.modified_files == ["src/bourbon/memory/manager.py"]
    assert ctx.touched_files == [
        "src/bourbon/memory/manager.py",
        "src/bourbon/memory/store.py",
    ]
    assert ctx.source_ref is not None
    assert ctx.source_ref.file_path == "src/bourbon/memory/models.py"
    assert ctx.task_subject == "memory cue engine"


def test_runtime_context_fingerprint_changes_when_current_files_change() -> None:
    base = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/a.py"],
        touched_files=["src/a.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_1",
    )
    changed = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/b.py"],
        touched_files=["src/b.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_1",
    )

    assert base.fingerprint() != changed.fingerprint()


def test_runtime_context_fingerprint_excludes_session_id() -> None:
    first = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/a.py"],
        touched_files=["src/a.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_1",
    )
    second = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/a.py"],
        touched_files=["src/a.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_2",
    )

    assert first.fingerprint() == second.fingerprint()
```

- [ ] **Step 2: Run failing runtime tests**

Run:

```bash
uv run pytest tests/test_memory_cue_runtime.py -q
```

Expected: FAIL because `bourbon.memory.cues.runtime` does not exist.

- [ ] **Step 3: Implement runtime context extraction**

Create `src/bourbon/memory/cues/runtime.py`:

```python
"""Runtime evidence extraction for memory cue generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bourbon.memory.models import SourceRef

READ_TOOLS = {
    "read",
    "Read",
    "rg_search",
    "grep",
    "glob",
    "ast_grep_search",
    "csv_analyze",
    "json_query",
    "pdf_to_text",
    "docx_to_markdown",
}
WRITE_TOOLS = {"write", "write_file", "edit", "edit_file", "str_replace", "StrReplace"}
SEARCH_TOOLS = {"rg_search", "grep", "glob", "ast_grep_search"}


@dataclass(frozen=True)
class CueRuntimeContext:
    workdir: Path
    current_files: list[str] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    source_ref: SourceRef | None = None
    recent_tool_names: list[str] = field(default_factory=list)
    task_subject: str | None = None
    session_id: str | None = None

    def fingerprint(self) -> str:
        source_ref_file = self.source_ref.file_path if self.source_ref else ""
        payload = {
            "current_files": sorted(self.current_files),
            "touched_files": sorted(self.touched_files),
            "modified_files": sorted(self.modified_files),
            "symbols": sorted(self.symbols),
            "recent_tool_names": self.recent_tool_names[-5:],
            "task_subject": self.task_subject or "",
            "source_ref_file": source_ref_file or "",
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def extract_paths_from_tool_input(tool_input: dict[str, Any]) -> list[str]:
    """Extract explicit file/path inputs without treating glob patterns as files."""
    candidates: list[str] = []
    for key in ("file_path", "filepath", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and "*" not in value and "?" not in value:
            candidates.append(value)
    for key in ("files", "file_paths"):
        value = tool_input.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if "*" not in str(item))
    return _dedupe(candidates)


def _iter_tool_uses(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_uses: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_uses.append(block)
    return tool_uses


def build_runtime_context_from_messages(
    messages: list[dict[str, Any]],
    *,
    workdir: Path,
    source_ref: SourceRef | None = None,
    session_id: str | None = None,
    task_subject: str | None = None,
) -> CueRuntimeContext:
    """Build runtime cue context from recent LLM-format message dictionaries."""
    tool_uses = _iter_tool_uses(messages)[-20:]
    touched: list[str] = []
    modified: list[str] = []
    read_or_edit: list[str] = []
    recent_tool_names: list[str] = []

    for tool in tool_uses:
        name = str(tool.get("name", ""))
        recent_tool_names.append(name)
        tool_input = tool.get("input", {})
        if not isinstance(tool_input, dict):
            continue
        paths = extract_paths_from_tool_input(tool_input)
        if name in READ_TOOLS or name in WRITE_TOOLS or name in SEARCH_TOOLS:
            touched.extend(paths)
        if name in READ_TOOLS or name in WRITE_TOOLS:
            read_or_edit.extend(paths)
        if name in WRITE_TOOLS:
            modified.extend(paths)

    current_files = _dedupe(list(reversed(read_or_edit)))[:3]
    current_files = sorted(current_files)
    return CueRuntimeContext(
        workdir=workdir,
        current_files=current_files,
        touched_files=sorted(_dedupe(touched)),
        modified_files=sorted(_dedupe(modified)),
        symbols=[],
        source_ref=source_ref,
        recent_tool_names=recent_tool_names[-10:],
        task_subject=task_subject,
        session_id=session_id,
    )
```

- [ ] **Step 4: Export runtime context and add tool context hook**

Modify `src/bourbon/memory/cues/__init__.py`:

```python
from bourbon.memory.cues.runtime import (
    CueRuntimeContext,
    build_runtime_context_from_messages,
)
```

Add to `__all__`:

```python
    "CueRuntimeContext",
    "build_runtime_context_from_messages",
```

Modify `src/bourbon/tools/__init__.py` `ToolContext` by adding this field:

```python
    cue_runtime_context_factory: Callable[[], Any] | None = None
```

Do not use the hook yet. This keeps the integration point available without coupling tools to session internals.

- [ ] **Step 5: Run runtime tests**

Run:

```bash
uv run pytest tests/test_memory_cue_runtime.py tests/test_tools_registry.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/cues/__init__.py src/bourbon/memory/cues/runtime.py src/bourbon/tools/__init__.py tests/test_memory_cue_runtime.py
git commit -m "feat(memory): add cue runtime context"
```

---

## Task 4: Implement Deterministic Record-Side CueEngine

**Files:**

- Create: `src/bourbon/memory/cues/engine.py`
- Modify: `src/bourbon/memory/cues/__init__.py`
- Test: `tests/test_memory_cue_engine.py`

- [ ] **Step 1: Write failing CueEngine tests**

Create `tests/test_memory_cue_engine.py`:

```python
"""Tests for record-side memory cue generation."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.cues.engine import CueEngine
from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    MemoryConcept,
)
from bourbon.memory.cues.runtime import CueRuntimeContext
from bourbon.memory.models import MemoryKind, MemoryRecordDraft, MemoryScope, MemorySource, SourceRef


def _draft(content: str, *, kind: MemoryKind = MemoryKind.PROJECT) -> MemoryRecordDraft:
    return MemoryRecordDraft(
        kind=kind,
        scope=MemoryScope.PROJECT,
        content=content,
        source=MemorySource.USER,
        name="test",
        description="test",
    )


def test_generate_for_record_preserves_runtime_file_evidence() -> None:
    engine = CueEngine()
    runtime = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/bourbon/memory/store.py"],
        touched_files=["src/bourbon/memory/store.py"],
        modified_files=[],
        symbols=[],
        source_ref=SourceRef(kind="file", file_path="src/bourbon/memory/models.py"),
        recent_tool_names=["Read"],
        task_subject="memory cue engine",
        session_id="ses_1",
    )

    metadata = engine.generate_for_record(
        _draft("We decided cue metadata belongs in frontmatter."),
        runtime_context=runtime,
    )

    assert metadata.generation_status == CueGenerationStatus.GENERATED
    assert metadata.files == [
        "src/bourbon/memory/models.py",
        "src/bourbon/memory/store.py",
    ]
    assert any(
        cue.kind == CueKind.FILE_OR_SYMBOL
        and cue.source == CueSource.RUNTIME
        and cue.text == "src/bourbon/memory/models.py"
        for cue in metadata.retrieval_cues
    )


def test_generate_for_record_derives_core_concepts_from_memory_kind_and_content() -> None:
    engine = CueEngine()
    metadata = engine.generate_for_record(
        _draft("Never mock the database in integration tests.", kind=MemoryKind.FEEDBACK),
        runtime_context=CueRuntimeContext(workdir=Path("/repo")),
    )

    assert MemoryConcept.BEHAVIOR_RULE in metadata.concepts
    assert any(cue.kind == CueKind.USER_PHRASE for cue in metadata.retrieval_cues)


def test_generate_for_record_returns_failed_metadata_for_empty_content() -> None:
    engine = CueEngine()
    metadata = engine.generate_for_record(
        _draft(""),
        runtime_context=CueRuntimeContext(workdir=Path("/repo")),
    )

    assert metadata.generation_status == CueGenerationStatus.FAILED
    assert CueQualityFlag.LLM_GENERATION_FAILED in metadata.quality_flags
    assert metadata.retrieval_cues[0].text == "Untitled memory"
```

- [ ] **Step 2: Run failing engine tests**

Run:

```bash
uv run pytest tests/test_memory_cue_engine.py -q
```

Expected: FAIL because `bourbon.memory.cues.engine` does not exist.

- [ ] **Step 3: Implement `CueEngine`**

Create `src/bourbon/memory/cues/engine.py`:

```python
"""Record-side cue generation."""

from __future__ import annotations

from datetime import UTC, datetime

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)
from bourbon.memory.cues.runtime import CueRuntimeContext
from bourbon.memory.models import MemoryKind, MemoryRecordDraft

GENERATOR_VERSION = "record-cue-v1"
SCHEMA_VERSION = "cue.v1"


class CueEngine:
    """Generate record-side memory cues from runtime evidence and conservative heuristics."""

    def generate_for_record(
        self,
        draft: MemoryRecordDraft,
        *,
        runtime_context: CueRuntimeContext,
    ) -> MemoryCueMetadata:
        content = draft.content.strip()
        if not content:
            return MemoryCueMetadata(
                schema_version=SCHEMA_VERSION,
                generator_version=GENERATOR_VERSION,
                concepts=[MemoryConcept.PROJECT_CONTEXT],
                retrieval_cues=[
                    RetrievalCue(
                        text=draft.name or "Untitled memory",
                        kind=CueKind.USER_PHRASE,
                        source=CueSource.USER,
                        confidence=1.0,
                    )
                ],
                files=[],
                symbols=[],
                generation_status=CueGenerationStatus.FAILED,
                generated_at=datetime.now(UTC),
                quality_flags=[CueQualityFlag.LLM_GENERATION_FAILED],
            )

        files = self._runtime_files(runtime_context)
        cues = self._runtime_file_cues(files)
        cues.extend(self._content_cues(draft))
        cues = self._dedupe_cues(cues)[:8]
        concepts = self._concepts_for_draft(draft)

        return MemoryCueMetadata(
            schema_version=SCHEMA_VERSION,
            generator_version=GENERATOR_VERSION,
            concepts=concepts,
            retrieval_cues=cues,
            files=files,
            symbols=sorted(set(runtime_context.symbols)),
            generation_status=CueGenerationStatus.GENERATED,
            generated_at=datetime.now(UTC),
            quality_flags=[],
        )

    def generate_for_records(
        self,
        drafts: list[MemoryRecordDraft],
        *,
        runtime_contexts: list[CueRuntimeContext],
    ) -> list[MemoryCueMetadata]:
        if len(drafts) != len(runtime_contexts):
            raise ValueError("drafts and runtime_contexts must have the same length")
        return [
            self.generate_for_record(draft, runtime_context=runtime_context)
            for draft, runtime_context in zip(drafts, runtime_contexts, strict=True)
        ]

    def _runtime_files(self, runtime_context: CueRuntimeContext) -> list[str]:
        files: list[str] = []
        if runtime_context.source_ref and runtime_context.source_ref.file_path:
            files.append(runtime_context.source_ref.file_path)
        files.extend(runtime_context.current_files)
        files.extend(runtime_context.touched_files)
        files.extend(runtime_context.modified_files)
        return sorted(set(item for item in files if item))

    def _runtime_file_cues(self, files: list[str]) -> list[RetrievalCue]:
        return [
            RetrievalCue(
                text=file_path[-80:],
                kind=CueKind.FILE_OR_SYMBOL,
                source=CueSource.RUNTIME,
                confidence=1.0,
            )
            for file_path in files
        ]

    def _content_cues(self, draft: MemoryRecordDraft) -> list[RetrievalCue]:
        cues: list[RetrievalCue] = []
        if draft.name:
            cues.append(
                RetrievalCue(
                    text=draft.name[:80],
                    kind=CueKind.USER_PHRASE,
                    source=CueSource.USER,
                    confidence=1.0,
                )
            )
        if draft.description and draft.description != draft.name:
            cues.append(
                RetrievalCue(
                    text=draft.description[:80],
                    kind=CueKind.TASK_PHRASE,
                    source=CueSource.USER,
                    confidence=0.9,
                )
            )
        first_line = draft.content.strip().splitlines()[0].strip()
        if first_line:
            cues.append(
                RetrievalCue(
                    text=first_line[:80],
                    kind=CueKind.USER_PHRASE,
                    source=CueSource.USER,
                    confidence=0.85,
                )
            )
        return cues

    def _concepts_for_draft(self, draft: MemoryRecordDraft) -> list[MemoryConcept]:
        content_lower = draft.content.lower()
        if draft.kind == MemoryKind.USER:
            return [MemoryConcept.USER_PREFERENCE]
        if draft.kind == MemoryKind.FEEDBACK:
            if any(token in content_lower for token in ("never", "always", "must", "prefer")):
                return [MemoryConcept.BEHAVIOR_RULE]
            return [MemoryConcept.RISK_OR_LESSON]
        if any(token in content_lower for token in ("decided", "decision", "tradeoff", "trade-off")):
            return [MemoryConcept.ARCHITECTURE_DECISION]
        if any(token in content_lower for token in ("workflow", "steps", "run", "test")):
            return [MemoryConcept.WORKFLOW]
        return [MemoryConcept.PROJECT_CONTEXT]

    def _dedupe_cues(self, cues: list[RetrievalCue]) -> list[RetrievalCue]:
        seen: set[tuple[str, CueKind]] = set()
        result: list[RetrievalCue] = []
        for cue in cues:
            key = (cue.text.lower(), cue.kind)
            if key in seen:
                continue
            seen.add(key)
            result.append(cue)
        return result
```

- [ ] **Step 4: Export `CueEngine`**

Modify `src/bourbon/memory/cues/__init__.py`:

```python
from bourbon.memory.cues.engine import CueEngine
```

Add to `__all__`:

```python
    "CueEngine",
```

- [ ] **Step 5: Run engine tests**

Run:

```bash
uv run pytest tests/test_memory_cue_engine.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/cues/__init__.py src/bourbon/memory/cues/engine.py tests/test_memory_cue_engine.py
git commit -m "feat(memory): add record cue engine"
```

---

## Task 5: Add Memory Cue Configuration

**Files:**

- Modify: `src/bourbon/config.py`
- Test: `tests/test_memory_config.py`

- [ ] **Step 1: Write failing config tests**

Append to `tests/test_memory_config.py`:

```python
def test_memory_cue_config_defaults() -> None:
    cfg = Config()

    assert cfg.memory.cue_enabled is False
    assert cfg.memory.cue_record_generation is True
    assert cfg.memory.cue_generation_timeout_ms == 1500
    assert cfg.memory.cue_record_generation_mode == "sync"
    assert cfg.memory.cue_persist_failed_metadata is True


def test_config_from_dict_memory_cues() -> None:
    cfg = Config.from_dict(
        {
            "memory": {
                "cue_enabled": True,
                "cue_record_generation": False,
                "cue_generation_timeout_ms": 750,
                "cue_record_generation_mode": "deferred",
                "cue_persist_failed_metadata": False,
            }
        }
    )

    assert cfg.memory.cue_enabled is True
    assert cfg.memory.cue_record_generation is False
    assert cfg.memory.cue_generation_timeout_ms == 750
    assert cfg.memory.cue_record_generation_mode == "deferred"
    assert cfg.memory.cue_persist_failed_metadata is False


def test_config_to_dict_memory_cues() -> None:
    cfg = Config()
    cfg.memory.cue_enabled = True
    data = cfg.to_dict()

    assert data["memory"]["cue_enabled"] is True
    assert data["memory"]["cue_record_generation"] is True
    assert data["memory"]["cue_generation_timeout_ms"] == 1500
```

- [ ] **Step 2: Run failing config tests**

Run:

```bash
uv run pytest tests/test_memory_config.py::test_memory_cue_config_defaults tests/test_memory_config.py::test_config_from_dict_memory_cues tests/test_memory_config.py::test_config_to_dict_memory_cues -q
```

Expected: FAIL because `MemoryConfig` has no cue fields.

- [ ] **Step 3: Add cue config fields**

Modify `src/bourbon/config.py` `MemoryConfig`:

```python
@dataclass
class MemoryConfig:
    """Memory system configuration."""

    enabled: bool = True
    storage_dir: str = "~/.bourbon/projects"
    auto_flush_on_compact: bool = True
    auto_extract: bool = False  # reserved for Phase 2 (automatic memory extraction)
    recall_limit: int = 8
    recall_transcript_session_limit: int = 10  # reserved for Phase 2 (transcript recall)
    memory_md_token_limit: int = 1200
    user_md_token_limit: int = 600
    core_block_token_limit: int = 1200  # reserved for Phase 2 (core memory block)
    cue_enabled: bool = False
    cue_record_generation: bool = True
    cue_generation_timeout_ms: int = 1500
    cue_record_generation_mode: str = "sync"
    cue_persist_failed_metadata: bool = True
```

Modify `Config.to_dict()` memory block by adding:

```python
                "cue_enabled": self.memory.cue_enabled,
                "cue_record_generation": self.memory.cue_record_generation,
                "cue_generation_timeout_ms": self.memory.cue_generation_timeout_ms,
                "cue_record_generation_mode": self.memory.cue_record_generation_mode,
                "cue_persist_failed_metadata": self.memory.cue_persist_failed_metadata,
```

- [ ] **Step 4: Run config tests**

Run:

```bash
uv run pytest tests/test_memory_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/config.py tests/test_memory_config.py
git commit -m "feat(memory): add cue configuration"
```

---

## Task 6: Integrate CueEngine Into MemoryManager Writes

**Files:**

- Modify: `src/bourbon/memory/manager.py`
- Modify: `src/bourbon/agent.py`
- Test: `tests/test_memory_manager.py`
- Test: `tests/test_memory_agent_integration.py`

- [ ] **Step 1: Add failing manager integration tests**

Modify imports in `tests/test_memory_manager.py`:

```python
from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    SourceRef,
)
```

Append to `tests/test_memory_manager.py`:

```python
def test_write_generates_cue_metadata_when_enabled(tmp_path: Path) -> None:
    config = MemoryConfig(storage_dir=str(tmp_path), cue_enabled=True)
    manager = MemoryManager(
        config=config,
        project_key="test-project-abc12345",
        workdir=tmp_path / "workdir",
        audit=None,
    )
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.PROJECT,
            scope=MemoryScope.PROJECT,
            content="We decided cue metadata belongs in memory frontmatter.",
            source=MemorySource.USER,
            confidence=1.0,
            name="Cue metadata decision",
            description="Cue metadata belongs in frontmatter",
        ),
        actor=MemoryActor(kind="user"),
    )

    assert record.cue_metadata is not None
    assert record.cue_metadata.files == []
    persisted = manager._store.read_record(record.id)
    assert persisted is not None
    assert persisted.cue_metadata == record.cue_metadata


def test_write_skips_cue_metadata_when_disabled(manager: MemoryManager) -> None:
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.PROJECT,
            scope=MemoryScope.PROJECT,
            content="No cue metadata when disabled.",
            source=MemorySource.USER,
            confidence=1.0,
        ),
        actor=MemoryActor(kind="user"),
    )

    assert record.cue_metadata is None


def test_write_uses_source_ref_as_runtime_file_when_cues_enabled(tmp_path: Path) -> None:
    config = MemoryConfig(storage_dir=str(tmp_path), cue_enabled=True)
    manager = MemoryManager(
        config=config,
        project_key="test-project-abc12345",
        workdir=tmp_path / "workdir",
        audit=None,
    )

    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.PROJECT,
            scope=MemoryScope.PROJECT,
            content="Source referenced cue metadata.",
            source=MemorySource.USER,
            confidence=1.0,
            source_ref=SourceRef(kind="file", file_path="src/bourbon/memory/models.py"),
        ),
        actor=MemoryActor(kind="user"),
    )

    assert record.cue_metadata is not None
    assert record.cue_metadata.files == ["src/bourbon/memory/models.py"]
```

- [ ] **Step 2: Run failing manager tests**

Run:

```bash
uv run pytest tests/test_memory_manager.py::test_write_generates_cue_metadata_when_enabled tests/test_memory_manager.py::test_write_skips_cue_metadata_when_disabled tests/test_memory_manager.py::test_write_uses_source_ref_as_runtime_file_when_cues_enabled -q
```

Expected: FAIL because `MemoryManager.write()` does not generate cue metadata.

- [ ] **Step 3: Wire `CueEngine` into `MemoryManager`**

Modify imports in `src/bourbon/memory/manager.py`:

```python
from bourbon.memory.cues.engine import CueEngine
from bourbon.memory.cues.models import CueGenerationStatus
from bourbon.memory.cues.runtime import CueRuntimeContext
```

In `MemoryManager.__init__()`, after `_recent_writes`:

```python
        self._cue_engine = CueEngine() if config.cue_enabled and config.cue_record_generation else None
```

Add helper method to `MemoryManager`:

```python
    def _build_default_cue_runtime_context(self, draft: MemoryRecordDraft) -> CueRuntimeContext:
        return CueRuntimeContext(
            workdir=self.workdir,
            current_files=[],
            touched_files=[],
            modified_files=[],
            symbols=[],
            source_ref=draft.source_ref,
            recent_tool_names=[],
            task_subject=draft.name or draft.description,
            session_id=draft.source_ref.session_id if draft.source_ref else None,
        )
```

In `MemoryManager.write()`, before constructing `MemoryRecord`, add:

```python
        cue_metadata = None
        if self._cue_engine is not None:
            runtime_context = self._build_default_cue_runtime_context(draft)
            cue_metadata = self._cue_engine.generate_for_record(
                draft,
                runtime_context=runtime_context,
            )
            if (
                cue_metadata.generation_status == CueGenerationStatus.FAILED
                and not self.config.cue_persist_failed_metadata
            ):
                cue_metadata = None
```

Pass `cue_metadata=cue_metadata` when constructing `MemoryRecord`:

```python
            source_ref=draft.source_ref,
            cue_metadata=cue_metadata,
```

- [ ] **Step 4: Add Agent runtime context factory hook**

Append this test to `tests/test_memory_agent_integration.py`:

```python
def test_agent_tool_context_has_cue_runtime_context_factory(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    ctx = agent._make_tool_context()

    assert ctx.cue_runtime_context_factory is not None
    runtime_context = ctx.cue_runtime_context_factory()
    assert runtime_context.workdir == tmp_path
```

Modify `src/bourbon/agent.py` by adding this private helper near `_make_tool_context()`:

```python
    def _make_cue_runtime_context(self):
        from bourbon.memory.cues.runtime import build_runtime_context_from_messages

        return build_runtime_context_from_messages(
            self.session.chain.get_llm_messages(),
            workdir=self.workdir,
            session_id=str(self.session.session_id),
        )
```

Modify `_make_tool_context()` return:

```python
            cue_runtime_context_factory=self._make_cue_runtime_context,
```

This hook is intentionally not used by `memory_write` yet. Manager write still has a safe default context. A later task can pass tool-time context explicitly without changing the core model.

- [ ] **Step 5: Run manager and agent integration tests**

Run:

```bash
uv run pytest tests/test_memory_manager.py tests/test_memory_agent_integration.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/manager.py src/bourbon/agent.py tests/test_memory_manager.py tests/test_memory_agent_integration.py
git commit -m "feat(memory): generate cue metadata on writes"
```

---

## Task 7: Add Deterministic Cue Eval Harness

**Files:**

- Create: `src/bourbon/memory/cues/eval.py`
- Modify: `src/bourbon/memory/cues/__init__.py`
- Test: `tests/test_memory_cue_eval.py`

- [ ] **Step 1: Write failing eval tests**

Create `tests/test_memory_cue_eval.py`:

```python
"""Tests for deterministic memory cue eval helpers."""

from __future__ import annotations

from bourbon.memory.cues.eval import (
    CueEvalCase,
    CueEvalResult,
    evaluate_ranked_results,
    rank_records_by_cues,
)
from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueSource,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)


def _metadata(*texts: str) -> MemoryCueMetadata:
    return MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version="record-cue-v1",
        concepts=[MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text=text,
                kind=CueKind.USER_PHRASE,
                source=CueSource.USER,
                confidence=1.0,
            )
            for text in texts
        ],
        files=[],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
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
```

- [ ] **Step 2: Run failing eval tests**

Run:

```bash
uv run pytest tests/test_memory_cue_eval.py -q
```

Expected: FAIL because `bourbon.memory.cues.eval` does not exist.

- [ ] **Step 3: Implement eval helpers**

Create `src/bourbon/memory/cues/eval.py`:

```python
"""Deterministic eval helpers for memory cue representation."""

from __future__ import annotations

from dataclasses import dataclass

from bourbon.memory.cues.models import MemoryCueMetadata


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


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in text.replace("/", " ").replace("-", " ").split() if token}


def rank_records_by_cues(
    query: str,
    records: dict[str, MemoryCueMetadata],
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
        hit_positions = [index for index, memory_id in enumerate(top_k, start=1) if memory_id in expected]
        if hit_positions:
            recall_total += 1.0
            reciprocal_total += 1.0 / hit_positions[0]
        if top_k:
            noise_total += len([memory_id for memory_id in top_k if memory_id not in expected]) / len(top_k)
        else:
            noise_total += 1.0

    count = len(cases)
    return CueEvalResult(
        recall_at_k=recall_total / count,
        mrr=reciprocal_total / count,
        noise_at_k=noise_total / count,
    )
```

- [ ] **Step 4: Export eval helpers**

Modify `src/bourbon/memory/cues/__init__.py`:

```python
from bourbon.memory.cues.eval import (
    CueEvalCase,
    CueEvalResult,
    evaluate_ranked_results,
    rank_records_by_cues,
)
```

Add to `__all__`:

```python
    "CueEvalCase",
    "CueEvalResult",
    "evaluate_ranked_results",
    "rank_records_by_cues",
```

- [ ] **Step 5: Run eval tests**

Run:

```bash
uv run pytest tests/test_memory_cue_eval.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/memory/cues/__init__.py src/bourbon/memory/cues/eval.py tests/test_memory_cue_eval.py
git commit -m "feat(memory): add cue eval helpers"
```

---

## Task 8: Final Verification And Spec Alignment

**Files:**

- Modify only if needed: `docs/superpowers/specs/2026-05-04-bourbon-memory-cue-engine-design.md`
- Modify only if needed: `docs/superpowers/plans/2026-05-04-bourbon-memory-cue-engine-phase0-1.md`

- [ ] **Step 1: Run focused memory cue test suite**

Run:

```bash
uv run pytest tests/test_memory_cue_models.py tests/test_memory_cue_runtime.py tests/test_memory_cue_engine.py tests/test_memory_cue_eval.py -q
```

Expected: PASS.

- [ ] **Step 2: Run existing memory regression suite**

Run:

```bash
uv run pytest tests/test_memory_models.py tests/test_memory_store.py tests/test_memory_manager.py tests/test_memory_config.py tests/test_memory_agent_integration.py tests/test_memory_tools.py tests/test_memory_e2e.py tests/test_memory_phase2.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
uv run ruff check src/bourbon/memory src/bourbon/tools/__init__.py src/bourbon/agent.py tests/test_memory_cue_models.py tests/test_memory_cue_runtime.py tests/test_memory_cue_engine.py tests/test_memory_cue_eval.py tests/test_memory_store.py tests/test_memory_manager.py tests/test_memory_config.py tests/test_memory_agent_integration.py
```

Expected: PASS.

- [ ] **Step 4: Run type check on touched source**

Run:

```bash
uv run mypy src/bourbon/memory src/bourbon/tools/__init__.py src/bourbon/agent.py
```

Expected: PASS.

- [ ] **Step 5: Check for accidental query-side scope creep**

Run:

```bash
rg -n "QueryCue|interpret_query|query_interpret|embedding|HyDE" src tests
```

Expected: No new implementation references except comments or spec documents. If code references exist, remove them unless they are in this plan's docs.

- [ ] **Step 6: Check git status**

Run:

```bash
git status --short
```

Expected: only intended files modified or committed. The spec file and plan file may remain uncommitted if the user wants to review them separately.

---

## Spec Coverage Checklist

- Cue model taxonomy: Task 1.
- `CueQualityFlag` enum: Task 1.
- `DomainConcept` extension: Task 1.
- `MemoryCueMetadata` durable frontmatter: Task 1 and Task 2.
- Old memory compatibility: Task 2.
- Malformed frontmatter/cue metadata isolation: Task 2.
- Runtime evidence priority: Task 3 and Task 4.
- `current_files` CLI adapter: Task 3.
- Runtime fingerprint excluding session id: Task 3.
- Record-side generation latency boundary: Task 5 and Task 6 enable sync-only MVP behind config; deferred worker is explicitly future work.
- `generate_for_records()` batch API: Task 4.
- Eval harness for cue representation: Task 7.
- Query-side fast path: intentionally future work, not Phase 0/1.
- Search/ranking changes: intentionally future work, not Phase 0/1.

## Execution Notes

- Default `cue_enabled=False` is intentional for this phase. It preserves current behavior until the user explicitly enables cues.
- The first `CueEngine` is deterministic. Real model-backed generation should be added only after the model/store/eval foundation is stable.
- Cue metadata in YAML frontmatter makes cue text grep-searchable immediately, but that is a side effect, not a ranking implementation.
- If any existing memory test expects exact YAML output, update only the assertion shape, not production behavior.
