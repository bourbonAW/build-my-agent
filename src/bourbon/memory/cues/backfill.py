"""Batch backfill support for persisted memory cue metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bourbon.memory.cues.engine import CueEngine
from bourbon.memory.cues.models import CueGenerationStatus
from bourbon.memory.cues.runtime import CueRuntimeContext

if TYPE_CHECKING:
    from bourbon.memory.models import MemoryRecord, MemoryRecordDraft
    from bourbon.memory.store import MemoryStore

    type RuntimeContextFactory = Callable[[MemoryRecord], CueRuntimeContext]
else:
    type RuntimeContextFactory = Callable[[object], CueRuntimeContext]


@dataclass(frozen=True)
class BackfillStats:
    """Counters for one memory cue backfill run."""

    scanned: int = 0
    backfilled: int = 0
    skipped: int = 0
    failed: int = 0


def backfill_memory_cues(
    store: MemoryStore,
    engine: CueEngine,
    *,
    runtime_context_factory: RuntimeContextFactory | None = None,
    dry_run: bool = False,
    force: bool = False,
    limit: int | None = None,
) -> BackfillStats:
    """Generate missing cue metadata for persisted memory records.

    ``backfilled`` counts records that received generated metadata, or would receive
    it during ``dry_run``. Records with existing cue metadata are skipped unless
    ``force`` is true. ``limit`` caps generated candidates after those skips.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    records = store.list_records()
    skipped = sum(1 for record in records if record.cue_metadata is not None and not force)
    candidates = _select_candidates(records, force=force, limit=limit)

    if not candidates:
        return BackfillStats(scanned=len(records), skipped=skipped)

    batch_records: list[MemoryRecord] = []
    drafts: list[MemoryRecordDraft] = []
    runtime_contexts: list[CueRuntimeContext] = []
    failed = 0
    for record in candidates:
        try:
            runtime_context = _runtime_context_for_record(
                record,
                store=store,
                runtime_context_factory=runtime_context_factory,
            )
        except Exception:
            failed += 1
            continue
        batch_records.append(record)
        drafts.append(_draft_from_record(record))
        runtime_contexts.append(runtime_context)

    if not batch_records:
        return BackfillStats(scanned=len(records), skipped=skipped, failed=failed)

    try:
        cue_metadata = engine.generate_for_records(
            drafts,
            runtime_contexts=runtime_contexts,
        )
    except Exception:
        return BackfillStats(
            scanned=len(records),
            skipped=skipped,
            failed=failed + len(batch_records),
        )

    if len(cue_metadata) != len(batch_records):
        return BackfillStats(
            scanned=len(records),
            skipped=skipped,
            failed=failed + len(batch_records),
        )

    backfilled = 0
    for record, metadata in zip(batch_records, cue_metadata, strict=True):
        if metadata.generation_status == CueGenerationStatus.FAILED:
            failed += 1
            continue
        if dry_run:
            backfilled += 1
            continue
        try:
            store.update_cue_metadata(record.id, metadata)
        except Exception:
            failed += 1
            continue
        backfilled += 1

    return BackfillStats(
        scanned=len(records),
        backfilled=backfilled,
        skipped=skipped,
        failed=failed,
    )


def _select_candidates(
    records: list[MemoryRecord],
    *,
    force: bool,
    limit: int | None,
) -> list[MemoryRecord]:
    candidates: list[MemoryRecord] = []
    for record in records:
        if record.cue_metadata is not None and not force:
            continue
        if limit is not None and len(candidates) >= limit:
            continue
        candidates.append(record)
    return candidates


def _draft_from_record(record: MemoryRecord) -> MemoryRecordDraft:
    from bourbon.memory.models import MemoryRecordDraft

    return MemoryRecordDraft(
        kind=record.kind,
        scope=record.scope,
        content=record.content,
        source=record.source,
        confidence=record.confidence,
        name=record.name,
        description=record.description,
        source_ref=record.source_ref,
    )


def _runtime_context_for_record(
    record: MemoryRecord,
    *,
    store: MemoryStore,
    runtime_context_factory: RuntimeContextFactory | None,
) -> CueRuntimeContext:
    if runtime_context_factory is not None:
        return runtime_context_factory(record)
    return CueRuntimeContext(
        workdir=store.memory_dir,
        current_files=[],
        touched_files=[],
        modified_files=[],
        symbols=[],
        source_ref=record.source_ref,
        recent_tool_names=[],
        task_subject=record.name or record.description,
        session_id=record.source_ref.session_id if record.source_ref else None,
    )
