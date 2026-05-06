"""Tests for minimal MemoryManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from bourbon.audit.events import EventType
from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import MemoryActor, MemoryRecordDraft


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def audit() -> FakeAudit:
    return FakeAudit()


@pytest.fixture
def manager(tmp_path: Path, audit: FakeAudit) -> MemoryManager:
    return MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )


def test_write_persists_record_and_emits_required_audit(
    manager: MemoryManager,
    audit: FakeAudit,
) -> None:
    record = manager.write(
        MemoryRecordDraft(target="project", content='Use `dark mode` for UI settings.'),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    assert record.target == "project"
    assert record.cues == ("dark mode",)
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.event_type == EventType.MEMORY_WRITE
    assert event.extra["actor_kind"] == "agent"
    assert event.extra["session_id"] == "ses_1"
    assert event.extra["target"] == "project"
    assert event.extra["memory_id"] == record.id


def test_write_fails_without_audit(tmp_path: Path) -> None:
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=None,
    )

    with pytest.raises(RuntimeError, match="memory writes require audit"):
        manager.write(
            MemoryRecordDraft(target="project", content="Missing audit must fail."),
            actor=MemoryActor(kind="agent"),
        )


def test_search_uses_expanded_terms_and_target_filter(manager: MemoryManager) -> None:
    manager.write(
        MemoryRecordDraft(target="project", content='Use `dark mode` for UI settings.'),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    results = manager.search("dark mode", target="project")

    assert [result.target for result in results] == ["project"]
    assert manager.get_last_expanded_terms() == ("dark mode",)


def test_delete_removes_record_and_rejects_subagents(manager: MemoryManager) -> None:
    record = manager.write(
        MemoryRecordDraft(target="project", content="Remove this memory."),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    with pytest.raises(PermissionError, match="Subagents cannot delete memory"):
        manager.delete(record.id, actor=MemoryActor(kind="subagent", run_id="run_1"))

    manager.delete(record.id, actor=MemoryActor(kind="agent", session_id="ses_1"))

    assert manager.search("Remove this memory") == []


def test_get_status_returns_system_info(manager: MemoryManager) -> None:
    manager.write(
        MemoryRecordDraft(target="project", content="Status preview content."),
        actor=MemoryActor(kind="agent", session_id="ses_1"),
    )

    info = manager.get_status(actor=MemoryActor(kind="subagent", run_id="run_1"))

    assert info.readable_targets == ("user", "project")
    assert info.writable_targets == ("project",)
    assert info.memory_file_count == 1
    assert info.recent_writes[0].preview == "Status preview content."
