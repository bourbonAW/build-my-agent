"""Tests for memory cue backfill service."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bourbon.memory.cues import BackfillStats, backfill_memory_cues
from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueSource,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)
from bourbon.memory.cues.runtime import CueRuntimeContext
from bourbon.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    SourceRef,
)
from bourbon.memory.store import MemoryStore


def _record(
    memory_id: str,
    *,
    name: str,
    content: str,
    cue_metadata: MemoryCueMetadata | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        name=name,
        description=f"{name} description",
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemoryStatus.ACTIVE,
        created_at=datetime(2026, 5, 5, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 5, 10, 0, tzinfo=UTC),
        created_by="user",
        content=content,
        source_ref=SourceRef(kind="file", file_path=f"docs/{memory_id}.md"),
        cue_metadata=cue_metadata,
    )


def _metadata(text: str, *, generator_version: str = "record-cue-v1") -> MemoryCueMetadata:
    return MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version=generator_version,
        concepts=[MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text=text,
                kind=CueKind.USER_PHRASE,
                source=CueSource.BACKFILL,
                confidence=1.0,
            )
        ],
        files=[],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
        generated_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )


class RecordingBatchEngine:
    def __init__(self, prefix: str = "generated") -> None:
        self.prefix = prefix
        self.calls: list[
            tuple[list[MemoryRecordDraft], list[CueRuntimeContext]]
        ] = []

    def generate_for_records(
        self,
        drafts: list[MemoryRecordDraft],
        *,
        runtime_contexts: list[CueRuntimeContext],
    ) -> list[MemoryCueMetadata]:
        self.calls.append((drafts, runtime_contexts))
        return [
            _metadata(f"{self.prefix} {draft.name}")
            for draft in drafts
        ]


class FailingBatchEngine:
    def generate_for_records(
        self,
        drafts: list[MemoryRecordDraft],
        *,
        runtime_contexts: list[CueRuntimeContext],
    ) -> list[MemoryCueMetadata]:
        return [
            MemoryCueMetadata(
                schema_version="cue.v1",
                generator_version="record-cue-v1",
                concepts=[MemoryConcept.PROJECT_CONTEXT],
                retrieval_cues=[
                    RetrievalCue(
                        text=draft.name or "Untitled memory",
                        kind=CueKind.USER_PHRASE,
                        source=CueSource.BACKFILL,
                        confidence=1.0,
                    )
                ],
                files=[],
                symbols=[],
                generation_status=CueGenerationStatus.FAILED,
            )
            for draft in drafts
        ]


def test_backfill_dry_run_generates_batch_but_does_not_write(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    record = _record("mem_backfill1", name="Backfill target", content="Need cues.")
    store.write_record(record)
    engine = RecordingBatchEngine()

    stats = backfill_memory_cues(store, engine, dry_run=True)

    assert stats == BackfillStats(scanned=1, backfilled=1, skipped=0, failed=0)
    assert len(engine.calls) == 1
    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata is None


def test_backfill_skips_records_with_existing_cue_metadata(tmp_path: Path) -> None:
    existing_metadata = _metadata("existing cue")
    store = MemoryStore(tmp_path)
    store.write_record(
        _record(
            "mem_has_cue1",
            name="Already cued",
            content="Already has metadata.",
            cue_metadata=existing_metadata,
        )
    )
    engine = RecordingBatchEngine()

    stats = backfill_memory_cues(store, engine)

    assert stats == BackfillStats(scanned=1, backfilled=0, skipped=1, failed=0)
    assert engine.calls == []
    loaded = store.read_record("mem_has_cue1")
    assert loaded is not None
    assert loaded.cue_metadata == existing_metadata


def test_backfill_force_regenerates_existing_cue_metadata(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    original = _metadata("old cue", generator_version="old-generator")
    record = _record(
        "mem_force1",
        name="Force target",
        content="Regenerate existing metadata.",
        cue_metadata=original,
    )
    store.write_record(record)
    engine = RecordingBatchEngine(prefix="replacement")

    stats = backfill_memory_cues(store, engine, force=True)

    assert stats == BackfillStats(scanned=1, backfilled=1, skipped=0, failed=0)
    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata is not None
    assert loaded.cue_metadata.retrieval_cues[0].text == "replacement Force target"
    assert loaded.cue_metadata != original


def test_backfill_limit_caps_processed_candidates_after_skips(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.write_record(
        _record(
            "mem_existing1",
            name="Existing",
            content="Existing metadata.",
            cue_metadata=_metadata("existing cue"),
        )
    )
    candidates = [
        _record("mem_limit1", name="Limit 01", content="First uncued."),
        _record("mem_limit2", name="Limit 02", content="Second uncued."),
        _record("mem_limit3", name="Limit 03", content="Third uncued."),
    ]
    for record in candidates:
        store.write_record(record)
    engine = RecordingBatchEngine()

    stats = backfill_memory_cues(store, engine, limit=2)

    assert stats == BackfillStats(scanned=4, backfilled=2, skipped=1, failed=0)
    assert len(engine.calls) == 1
    drafts, runtime_contexts = engine.calls[0]
    assert [draft.name for draft in drafts] == ["Limit 01", "Limit 02"]
    assert [context.source_ref.file_path for context in runtime_contexts if context.source_ref] == [
        "docs/mem_limit1.md",
        "docs/mem_limit2.md",
    ]
    assert store.read_record("mem_limit1").cue_metadata is not None  # type: ignore[union-attr]
    assert store.read_record("mem_limit2").cue_metadata is not None  # type: ignore[union-attr]
    assert store.read_record("mem_limit3").cue_metadata is None  # type: ignore[union-attr]


def test_backfill_uses_custom_runtime_context_factory(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    record = _record("mem_runtime1", name="Runtime target", content="Needs runtime files.")
    store.write_record(record)
    engine = RecordingBatchEngine()

    def runtime_context_factory(memory_record: MemoryRecord) -> CueRuntimeContext:
        return CueRuntimeContext(
            workdir=Path("/repo"),
            current_files=[f"src/{memory_record.id}.py"],
        )

    stats = backfill_memory_cues(
        store,
        engine,
        runtime_context_factory=runtime_context_factory,
    )

    assert stats.backfilled == 1
    _, runtime_contexts = engine.calls[0]
    assert runtime_contexts[0].workdir == Path("/repo")
    assert runtime_contexts[0].current_files == ["src/mem_runtime1.py"]


def test_backfill_counts_failed_generation_without_writing_metadata(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    record = _record("mem_failed1", name="Failed target", content="Generation fails.")
    store.write_record(record)

    stats = backfill_memory_cues(store, FailingBatchEngine())

    assert stats == BackfillStats(scanned=1, backfilled=0, skipped=0, failed=1)
    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata is None


def test_backfill_empty_store_returns_zero_stats(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)

    stats = backfill_memory_cues(store, RecordingBatchEngine())

    assert stats == BackfillStats()
