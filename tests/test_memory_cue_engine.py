"""Tests for record-side memory cue generation."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.cues.engine import CueEngine
from bourbon.memory.cues.eval import rank_records_by_cues
from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueQualityFlag,
    CueSource,
    MemoryConcept,
)
from bourbon.memory.cues.runtime import CueRuntimeContext
from bourbon.memory.models import (
    MemoryKind,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    SourceRef,
)


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


def test_generate_for_records_batches_drafts_and_runtime_contexts() -> None:
    engine = CueEngine()
    records = engine.generate_for_records(
        [
            _draft("Always run focused tests first.", kind=MemoryKind.FEEDBACK),
            _draft("We decided cue metadata is deterministic."),
        ],
        runtime_contexts=[
            CueRuntimeContext(workdir=Path("/repo"), current_files=["tests/test_memory.py"]),
            CueRuntimeContext(workdir=Path("/repo"), current_files=["src/bourbon/memory.py"]),
        ],
    )

    assert len(records) == 2
    assert records[0].files == ["tests/test_memory.py"]
    assert records[1].files == ["src/bourbon/memory.py"]


def test_generate_for_record_keeps_source_ref_file_cue_when_many_files_exist() -> None:
    engine = CueEngine()
    runtime = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=[f"src/file_{index}.py" for index in range(12)],
        touched_files=[],
        modified_files=[],
        symbols=[],
        source_ref=SourceRef(kind="file", file_path="z_authoritative.py"),
    )

    metadata = engine.generate_for_record(
        _draft("We decided source_ref must remain authoritative."),
        runtime_context=runtime,
    )

    assert "z_authoritative.py" in metadata.files
    assert any(
        cue.kind == CueKind.FILE_OR_SYMBOL and cue.text == "z_authoritative.py"
        for cue in metadata.retrieval_cues
    )


def test_generate_for_record_ignores_whitespace_only_runtime_and_draft_fields() -> None:
    engine = CueEngine()
    runtime = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["   "],
        touched_files=["\t"],
        modified_files=[],
        symbols=[],
        source_ref=SourceRef(kind="file", file_path="  "),
    )
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Use deterministic cue generation.",
        source=MemorySource.USER,
        name="  ",
        description="\t",
    )

    metadata = engine.generate_for_record(draft, runtime_context=runtime)

    assert metadata.files == []
    assert metadata.retrieval_cues[0].text == "Use deterministic cue generation."


def test_generate_for_record_keeps_content_cue_when_many_runtime_files_exist() -> None:
    engine = CueEngine()
    runtime = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=[f"src/file_{index}.py" for index in range(12)],
        touched_files=[],
        modified_files=[],
        symbols=[],
        source_ref=SourceRef(kind="file", file_path="z_authoritative.py"),
    )

    metadata = engine.generate_for_record(
        _draft("Source ref decision must remain searchable."),
        runtime_context=runtime,
    )

    assert rank_records_by_cues("source ref decision", {"mem": metadata}) == ["mem"]
