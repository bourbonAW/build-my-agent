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
)
from bourbon.memory.store import _record_to_filename


@pytest.fixture
def manager(tmp_path: Path) -> MemoryManager:
    config = MemoryConfig(storage_dir=str(tmp_path))
    return MemoryManager(
        config=config,
        project_key="test-project-abc12345",
        workdir=tmp_path / "workdir",
        audit=None,
    )


def test_write_creates_file(manager: MemoryManager, tmp_path: Path) -> None:
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Always use WAL mode.",
        source=MemorySource.USER,
        confidence=1.0,
        name="WAL rule",
        description="Use WAL for SQLite",
    )

    record = manager.write(draft, actor=actor)

    assert record.id.startswith("mem_")
    assert record.created_by == "user"
    assert record.status == "active"

    mem_dir = tmp_path / "test-project-abc12345" / "memory"
    assert (mem_dir / _record_to_filename(record)).exists()


def test_write_updates_index(manager: MemoryManager, tmp_path: Path) -> None:
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        content="Never mock the database.",
        source=MemorySource.USER,
        confidence=1.0,
        name="No DB mocks",
        description="Integration tests must use real DB",
    )

    manager.write(draft, actor=actor)

    index_path = tmp_path / "test-project-abc12345" / "memory" / "MEMORY.md"
    assert index_path.exists()
    assert "No DB mocks" in index_path.read_text()


def test_search_finds_written_record(manager: MemoryManager) -> None:
    actor = MemoryActor(kind="user")
    draft = MemoryRecordDraft(
        kind=MemoryKind.PROJECT,
        scope=MemoryScope.PROJECT,
        content="Use pytest for all tests.",
        source=MemorySource.USER,
        confidence=1.0,
        name="Pytest preference",
        description="Use pytest not unittest",
    )

    manager.write(draft, actor=actor)

    results = manager.search("pytest", scope="project")
    assert len(results) >= 1
    assert "pytest" in results[0].snippet.lower() or "pytest" in results[0].name.lower()


def test_write_denied_for_subagent_user_kind(manager: MemoryManager) -> None:
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    draft = MemoryRecordDraft(
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        content="Should be denied.",
        source=MemorySource.SUBAGENT,
        confidence=0.5,
    )

    with pytest.raises(PermissionError):
        manager.write(draft, actor=actor)


def test_get_status(manager: MemoryManager) -> None:
    status = manager.get_status(actor=MemoryActor(kind="user"))
    assert "project" in status.readable_scopes
    assert status.index_at_capacity is False
    assert status.memory_file_count == 0


def test_flush_before_compact(manager: MemoryManager) -> None:
    messages = [
        {
            "role": "user",
            "content": "Remember to always run linting before commits.",
            "uuid": "msg_abc",
        },
    ]

    records = manager.flush_before_compact(messages, session_id="ses_test")
    assert len(records) >= 1
    assert records[0].source == "compaction"
    assert records[0].confidence < 1.0
