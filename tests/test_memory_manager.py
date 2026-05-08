"""Tests for minimal MemoryManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from bourbon.audit.events import EventType
from bourbon.config import MemoryConfig, MemorySemanticConfig
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


class FakeManagerProvider:
    name = "fake"
    dimensions = 3

    def __init__(self, *, model: str) -> None:
        self.model = model

    def embed_passages(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)

    def _vector(self, text: str) -> tuple[float, ...]:
        lowered = text.casefold()
        if "dark" in lowered or "界面主题" in text:
            return (1.0, 0.0, 0.0)
        return (0.0, 1.0, 0.0)


@pytest.fixture
def manager(tmp_path: Path, audit: FakeAudit) -> MemoryManager:
    return MemoryManager(
        config=MemoryConfig(
            storage_dir=str(tmp_path),
            semantic=MemorySemanticConfig(enabled=False),
        ),
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
    assert record.cues[0] == "dark mode"
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.event_type == EventType.MEMORY_WRITE
    assert event.extra["actor_kind"] == "agent"
    assert event.extra["session_id"] == "ses_1"
    assert event.extra["target"] == "project"
    assert event.extra["memory_id"] == record.id


def test_write_fails_without_audit(tmp_path: Path) -> None:
    manager = MemoryManager(
        config=MemoryConfig(
            storage_dir=str(tmp_path),
            semantic=MemorySemanticConfig(enabled=False),
        ),
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


def test_search_finds_plain_content_through_generated_cues(manager: MemoryManager) -> None:
    record = manager.write(
        MemoryRecordDraft(target="user", content="User prefers dark mode for UI components."),
        actor=MemoryActor(kind="user", session_id="ses_1"),
    )

    results = manager.search("where is dark mode preference", target="user")

    assert "dark mode" in record.cues
    assert results[0].id == record.id
    assert results[0].why_matched == "matched cue: dark mode"


def test_search_uses_semantic_retriever_when_available(
    tmp_path: Path,
    audit: FakeAudit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bourbon.memory.manager.FastEmbedProvider",
        FakeManagerProvider,
    )
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )
    record = manager.write(
        MemoryRecordDraft(target="user", content="User prefers dark mode for UI components."),
        actor=MemoryActor(kind="user", session_id="ses_1"),
    )

    results = manager.search("用户喜欢什么界面主题？", target="user")

    assert results[0].id == record.id
    assert results[0].why_matched.startswith("matched semantic:")


def test_search_rebuilds_stale_semantic_index_from_records(
    tmp_path: Path,
    audit: FakeAudit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bourbon.memory.manager.FastEmbedProvider",
        FakeManagerProvider,
    )
    old_manager = MemoryManager(
        config=MemoryConfig(
            storage_dir=str(tmp_path),
            semantic=MemorySemanticConfig(model="old-model"),
        ),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )
    record = old_manager.write(
        MemoryRecordDraft(target="user", content="User prefers dark mode for UI components."),
        actor=MemoryActor(kind="user", session_id="ses_1"),
    )
    new_manager = MemoryManager(
        config=MemoryConfig(
            storage_dir=str(tmp_path),
            semantic=MemorySemanticConfig(model="new-model"),
        ),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )

    results = new_manager.search("用户喜欢什么界面主题？", target="user")

    assert [result.id for result in results] == [record.id]
    assert results[0].why_matched.startswith("matched semantic:")


def test_search_rebuilds_corrupt_semantic_index_from_records(
    tmp_path: Path,
    audit: FakeAudit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bourbon.memory.manager.FastEmbedProvider",
        FakeManagerProvider,
    )
    bootstrap_manager = MemoryManager(
        config=MemoryConfig(
            storage_dir=str(tmp_path),
            semantic=MemorySemanticConfig(enabled=False),
        ),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )
    record = bootstrap_manager.write(
        MemoryRecordDraft(target="user", content="User prefers dark mode for UI components."),
        actor=MemoryActor(kind="user", session_id="ses_1"),
    )
    index_path = bootstrap_manager.get_memory_dir() / "search_index.sqlite"
    index_path.write_bytes(b"not a sqlite database")
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=audit,  # type: ignore[arg-type]
    )

    results = manager.search("用户喜欢什么界面主题？", target="user")

    assert [result.id for result in results] == [record.id]
    assert results[0].why_matched.startswith("matched semantic:")


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
