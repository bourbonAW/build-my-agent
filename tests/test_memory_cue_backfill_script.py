"""Subprocess tests for the memory cue backfill CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from bourbon.memory.cues.models import (
    CueGenerationStatus,
    CueKind,
    CueSource,
    MemoryConcept,
    MemoryCueMetadata,
    RetrievalCue,
)
from bourbon.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryStatus,
    SourceRef,
)
from bourbon.memory.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backfill_memory_cues.py"


def _run_script(memory_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--memory-dir", str(memory_dir), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


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


def _metadata(text: str, *, generator_version: str = "old-generator") -> MemoryCueMetadata:
    return MemoryCueMetadata(
        schema_version="cue.v1",
        generator_version=generator_version,
        concepts=[MemoryConcept.PROJECT_CONTEXT],
        retrieval_cues=[
            RetrievalCue(
                text=text,
                kind=CueKind.USER_PHRASE,
                source=CueSource.USER,
                confidence=1.0,
            )
        ],
        files=[],
        symbols=[],
        generation_status=CueGenerationStatus.GENERATED,
        generated_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )


def test_backfill_script_prints_human_summary_and_writes_missing_cues(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path)
    record = _record("mem_cli_human1", name="Human output", content="Needs cues.")
    store.write_record(record)

    result = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "scanned=1 backfilled=1 skipped=0 failed=0"
    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata is not None


def test_backfill_script_json_output_is_stable_object_with_limit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.write_record(
        _record(
            "mem_cli_existing1",
            name="Existing cue",
            content="Already has cues.",
            cue_metadata=_metadata("existing cue"),
        )
    )
    store.write_record(_record("mem_cli_limit1", name="Limit one", content="First target."))
    store.write_record(_record("mem_cli_limit2", name="Limit two", content="Second target."))

    result = _run_script(tmp_path, "--limit", "1", "--json")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"scanned":3,"backfilled":1,"skipped":1,"failed":0}'
    assert json.loads(result.stdout) == {
        "scanned": 3,
        "backfilled": 1,
        "skipped": 1,
        "failed": 0,
    }
    assert store.read_record("mem_cli_limit1").cue_metadata is not None  # type: ignore[union-attr]
    assert store.read_record("mem_cli_limit2").cue_metadata is None  # type: ignore[union-attr]


def test_backfill_script_dry_run_counts_candidates_without_writing(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    record = _record("mem_cli_dryrun1", name="Dry run", content="Would receive cues.")
    store.write_record(record)

    result = _run_script(tmp_path, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "scanned": 1,
        "backfilled": 1,
        "skipped": 0,
        "failed": 0,
    }
    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata is None


def test_backfill_script_force_regenerates_existing_cue_metadata(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    original = _metadata("old cue")
    record = _record(
        "mem_cli_force1",
        name="Force regeneration",
        content="Regenerate these cues.",
        cue_metadata=original,
    )
    store.write_record(record)

    result = _run_script(tmp_path, "--force", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "scanned": 1,
        "backfilled": 1,
        "skipped": 0,
        "failed": 0,
    }
    loaded = store.read_record(record.id)
    assert loaded is not None
    assert loaded.cue_metadata is not None
    assert loaded.cue_metadata.generator_version == "record-cue-v1"
    assert loaded.cue_metadata != original
