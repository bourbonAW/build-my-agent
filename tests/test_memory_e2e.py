"""End-to-end tests for minimal memory."""

from __future__ import annotations

from bourbon.config import MemoryConfig
from bourbon.memory.manager import MemoryManager
from bourbon.memory.models import MemoryActor, MemoryRecordDraft


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


def test_memory_write_search_delete_e2e(tmp_path) -> None:
    manager = MemoryManager(
        config=MemoryConfig(storage_dir=str(tmp_path)),
        project_key="proj",
        workdir=tmp_path,
        audit=FakeAudit(),  # type: ignore[arg-type]
    )
    actor = MemoryActor(kind="agent", session_id="ses_1")

    record = manager.write(
        MemoryRecordDraft(target="project", content='Use `dark mode` for UI components.'),
        actor=actor,
    )

    assert manager.search("dark mode", target="project")[0].id == record.id

    manager.delete(record.id, actor=actor)

    assert manager.search("dark mode", target="project") == []
