from pathlib import Path
from datetime import UTC, datetime

import pytest

from bourbon.config import MemoryConfig
import bourbon.memory.manager as memory_manager_module
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecordDraft,
    MemoryScope,
    MemorySource,
    MemoryStatus,
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


def test_promote_updates_global_user_md_and_store_status(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv.",
            source=MemorySource.USER,
            confidence=1.0,
            name="uv preference",
            description="Prefer uv for Python tooling",
        ),
        actor=actor,
    )

    updated = manager.promote(record.id, actor=actor, note="stable preference")

    assert updated.status == MemoryStatus.PROMOTED
    persisted = manager._store.read_record(record.id)
    assert persisted is not None
    assert persisted.status == MemoryStatus.PROMOTED

    user_md = tmp_path / ".bourbon" / "USER.md"
    assert user_md.exists()
    user_md_text = user_md.read_text(encoding="utf-8")
    assert f'<!-- bourbon-memory:start id="{record.id}" -->' in user_md_text
    assert "- status: promoted" in user_md_text
    assert "- note: stable preference" in user_md_text


def test_promote_uses_fresh_promotion_timestamp_for_managed_block(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv.",
            source=MemorySource.USER,
            confidence=1.0,
            name="uv preference",
            description="Prefer uv for Python tooling",
        ),
        actor=actor,
    )
    stale_record = manager._store.update_status(record.id, MemoryStatus.STALE)
    promotion_time = datetime(2026, 4, 22, 10, 30, tzinfo=UTC)

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return promotion_time if tz is None else promotion_time.astimezone(tz)

    monkeypatch.setattr(memory_manager_module, "datetime", FakeDateTime)

    manager.promote(record.id, actor=actor, note="stable preference")

    user_md = tmp_path / ".bourbon" / "USER.md"
    user_md_text = user_md.read_text(encoding="utf-8")
    assert f"- promoted_at: {promotion_time.isoformat()}" in user_md_text
    assert f"- promoted_at: {stale_record.updated_at.isoformat()}" not in user_md_text


def test_archive_marks_promoted_blocks_stale(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.FEEDBACK,
            scope=MemoryScope.USER,
            content="Keep responses concise.",
            source=MemorySource.USER,
            confidence=1.0,
            name="concise preference",
            description="Prefer concise responses",
        ),
        actor=actor,
    )
    manager.promote(record.id, actor=actor, note="stable preference")

    updated = manager.archive(
        record.id,
        MemoryStatus.STALE,
        actor=actor,
        reason="temporary exception",
    )

    assert updated.status == MemoryStatus.STALE
    user_md = tmp_path / ".bourbon" / "USER.md"
    user_md_text = user_md.read_text(encoding="utf-8")
    assert "- status: stale" in user_md_text
    assert "- status: promoted" not in user_md_text


def test_archive_rejects_missing_user_md_for_promoted_record(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv.",
            source=MemorySource.USER,
            confidence=1.0,
        ),
        actor=actor,
    )
    manager.promote(record.id, actor=actor, note="stable preference")
    user_md = tmp_path / ".bourbon" / "USER.md"
    user_md.unlink()

    with pytest.raises(RuntimeError, match="Managed USER.md projection missing"):
        manager.archive(record.id, MemoryStatus.STALE, actor=actor)

    persisted = manager._store.read_record(record.id)
    assert persisted is not None
    assert persisted.status == MemoryStatus.PROMOTED


def test_archive_rejects_missing_managed_block_for_promoted_record(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv.",
            source=MemorySource.USER,
            confidence=1.0,
        ),
        actor=actor,
    )
    manager.promote(record.id, actor=actor, note="stable preference")
    user_md = tmp_path / ".bourbon" / "USER.md"
    user_md.write_text("## Bourbon Managed Preferences\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=f"Managed USER.md block missing for {record.id}"):
        manager.archive(record.id, MemoryStatus.STALE, actor=actor)

    persisted = manager._store.read_record(record.id)
    assert persisted is not None
    assert persisted.status == MemoryStatus.PROMOTED


def test_archive_rejects_promoted_block_missing_status_line(
    manager: MemoryManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv.",
            source=MemorySource.USER,
            confidence=1.0,
        ),
        actor=actor,
    )
    manager.promote(record.id, actor=actor, note="stable preference")
    user_md = tmp_path / ".bourbon" / "USER.md"
    malformed = user_md.read_text(encoding="utf-8").replace("- status: promoted\n", "")
    user_md.write_text(malformed, encoding="utf-8")

    with pytest.raises(RuntimeError, match=f"Managed USER.md block missing status for {record.id}"):
        manager.archive(record.id, MemoryStatus.STALE, actor=actor)

    persisted = manager._store.read_record(record.id)
    assert persisted is not None
    assert persisted.status == MemoryStatus.PROMOTED


def test_archive_rejects_unsupported_status(manager: MemoryManager) -> None:
    actor = MemoryActor(kind="user")
    record = manager.write(
        MemoryRecordDraft(
            kind=MemoryKind.USER,
            scope=MemoryScope.USER,
            content="Always use uv.",
            source=MemorySource.USER,
            confidence=1.0,
        ),
        actor=actor,
    )

    with pytest.raises(ValueError, match="Cannot archive record as active"):
        manager.archive(record.id, MemoryStatus.ACTIVE, actor=actor)


def test_archive_rejects_unknown_memory_id(manager: MemoryManager) -> None:
    with pytest.raises(KeyError, match="Unknown memory id: mem_missing"):
        manager.archive("mem_missing", MemoryStatus.STALE, actor=MemoryActor(kind="user"))


@pytest.mark.parametrize(
    ("draft", "starting_status", "error_message"),
    [
        (
            MemoryRecordDraft(
                kind=MemoryKind.USER,
                scope=MemoryScope.USER,
                content="Rejected preference.",
                source=MemorySource.USER,
                confidence=1.0,
            ),
            MemoryStatus.REJECTED,
            "Cannot promote record with status rejected",
        ),
        (
            MemoryRecordDraft(
                kind=MemoryKind.PROJECT,
                scope=MemoryScope.USER,
                content="Project memory.",
                source=MemorySource.USER,
                confidence=1.0,
            ),
            MemoryStatus.ACTIVE,
            "Cannot promote memory kind project",
        ),
        (
            MemoryRecordDraft(
                kind=MemoryKind.FEEDBACK,
                scope=MemoryScope.PROJECT,
                content="Project-scoped feedback.",
                source=MemorySource.USER,
                confidence=1.0,
            ),
            MemoryStatus.ACTIVE,
            "Only user-scope records can be promoted",
        ),
    ],
)
def test_promote_rejects_invalid_status_kind_and_scope_cases(
    manager: MemoryManager,
    draft: MemoryRecordDraft,
    starting_status: MemoryStatus,
    error_message: str,
) -> None:
    actor = MemoryActor(kind="user")
    record = manager.write(draft, actor=actor)
    if starting_status != MemoryStatus.ACTIVE:
        manager._store.update_status(record.id, starting_status)

    with pytest.raises((PermissionError, ValueError), match=error_message):
        manager.promote(record.id, actor=actor)
