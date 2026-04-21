import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from bourbon.memory.prompt import memory_anchors_section
from bourbon.prompt.types import PromptContext


@pytest.fixture
def e2e_setup(tmp_path: Path) -> tuple[MemoryManager, Path]:
    workdir = tmp_path / "project"
    workdir.mkdir()

    config = MemoryConfig(storage_dir=str(tmp_path / "store"))
    manager = MemoryManager(
        config=config,
        project_key="e2e-test-12345678",
        workdir=workdir,
        audit=None,
    )
    return manager, workdir


def test_write_search_roundtrip(e2e_setup: tuple[MemoryManager, Path]) -> None:
    manager, _workdir = e2e_setup
    actor = MemoryActor(kind="user")

    draft = MemoryRecordDraft(
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        content="Never mock the database in integration tests.",
        source=MemorySource.USER,
        confidence=1.0,
        name="No DB mocks",
        description="Integration tests must hit real DB",
    )
    record = manager.write(draft, actor=actor)
    assert record.id.startswith("mem_")

    results = manager.search("mock database")
    assert len(results) >= 1
    assert any(
        "mock" in result.snippet.lower() or "database" in result.snippet.lower()
        for result in results
    )

    status = manager.get_status(actor=actor)
    assert status.memory_file_count == 1
    assert not status.index_at_capacity


def test_prompt_section_renders_index(e2e_setup: tuple[MemoryManager, Path]) -> None:
    manager, workdir = e2e_setup
    actor = MemoryActor(kind="user")

    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Use SQLite WAL mode.",
        source=MemorySource.USER,
        confidence=1.0,
        name="WAL mode",
        description="Always use WAL mode for SQLite",
    )
    manager.write(draft, actor=actor)

    ctx = PromptContext(workdir=workdir, memory_manager=manager)
    result = asyncio.run(memory_anchors_section(ctx))
    assert "WAL mode" in result


def test_rejected_memory_not_in_default_search(e2e_setup: tuple[MemoryManager, Path]) -> None:
    manager, _workdir = e2e_setup
    actor = MemoryActor(kind="user")

    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Old wrong advice.",
        source=MemorySource.USER,
        confidence=1.0,
        name="Wrong advice",
        description="This was wrong",
    )
    record = manager.write(draft, actor=actor)
    rejected_record = replace(record, status=MemoryStatus.REJECTED)
    manager._store.write_record(rejected_record)

    results = manager.search("Old wrong advice")
    assert len(results) == 0
