import json
from pathlib import Path

from bourbon.tools import ToolContext, _ensure_imports, get_registry


def test_memory_tools_registered() -> None:
    _ensure_imports()
    registry = get_registry()
    names = [tool.name for tool in registry.list_tools()]
    assert "memory_search" in names
    assert "memory_write" in names
    assert "memory_delete" in names
    assert "memory_status" in names
    assert "memory_promote" not in names
    assert "memory_archive" not in names


def test_memory_write_tool_schema() -> None:
    _ensure_imports()
    tool = get_registry().get_tool("MemoryWrite")
    assert tool is not None
    schema = tool.input_schema
    assert schema["required"] == ["target", "content"]
    assert schema["properties"]["target"]["enum"] == ["user", "project"]
    assert "kind" not in schema["properties"]
    assert "scope" not in schema["properties"]
    assert "source" not in schema["properties"]


def test_memory_search_tool_schema() -> None:
    _ensure_imports()
    tool = get_registry().get_tool("MemorySearch")
    assert tool is not None
    schema = tool.input_schema
    assert schema["required"] == ["query"]
    assert schema["properties"]["target"]["enum"] == ["user", "project"]
    assert schema["properties"]["debug_terms"]["type"] == "boolean"
    assert "status" not in schema["properties"]
    assert "kind" not in schema["properties"]
    assert "scope" not in schema["properties"]


def test_memory_search_passes_target_filter_and_debug_terms() -> None:
    from bourbon.tools.memory import memory_search

    class _FakeMemoryManager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search(self, query: str, **kwargs: object) -> list[object]:
            self.calls.append({"query": query, **kwargs})
            return []

        def get_last_expanded_terms(self) -> tuple[str, ...]:
            return ("dark mode",)

    manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

    result = json.loads(memory_search(query="dark mode", target="project", debug_terms=True, ctx=ctx))

    assert result == {"results": [], "expanded_terms": ["dark mode"]}
    assert manager.calls == [{"query": "dark mode", "target": "project", "limit": None}]


def test_memory_write_uses_target_and_content() -> None:
    from bourbon.memory.models import MemoryRecord
    from bourbon.tools.memory import memory_write
    from datetime import UTC, datetime

    class _FakeMemoryManager:
        def write(self, draft: object, *, actor: object) -> MemoryRecord:
            self.draft = draft
            self.actor = actor
            return MemoryRecord(
                id="mem_abc12345",
                target="project",
                content="Prefer append-only memory records.",
                created_at=datetime(2026, 5, 6, tzinfo=UTC),
            )

    manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

    result = json.loads(
        memory_write(
            target="project",
            content="Prefer append-only memory records.",
            ctx=ctx,
        )
    )

    assert result == {
        "id": "mem_abc12345",
        "target": "project",
        "status": "written",
        "file": "mem_abc12345.md",
    }
    assert manager.draft.target == "project"
    assert manager.draft.content == "Prefer append-only memory records."


def test_memory_delete_calls_manager() -> None:
    from bourbon.tools.memory import memory_delete

    class _FakeMemoryManager:
        def delete(self, memory_id: str, *, actor: object) -> None:
            self.memory_id = memory_id
            self.actor = actor

    manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

    result = json.loads(memory_delete(memory_id="mem_abc12345", ctx=ctx))

    assert result == {"id": "mem_abc12345", "status": "deleted"}
    assert manager.memory_id == "mem_abc12345"


def test_memory_status_uses_targets_and_recent_previews() -> None:
    from datetime import UTC, datetime
    from bourbon.memory.models import MemorySystemInfo, RecentWriteSummary
    from bourbon.tools.memory import memory_status

    class _FakeMemoryManager:
        def get_status(self, *, actor: object) -> MemorySystemInfo:
            return MemorySystemInfo(
                readable_targets=("user", "project"),
                writable_targets=("project",),
                recent_writes=(
                    RecentWriteSummary(
                        id="mem_abc12345",
                        target="project",
                        preview="Prefer append-only memory records.",
                        created_at=datetime(2026, 5, 6, tzinfo=UTC),
                    ),
                ),
                index_at_capacity=False,
                memory_file_count=1,
            )

    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=_FakeMemoryManager())

    result = json.loads(memory_status(ctx=ctx))

    assert result["readable_targets"] == ["user", "project"]
    assert result["writable_targets"] == ["project"]
    assert result["recent_writes"][0]["preview"] == "Prefer append-only memory records."


def test_memory_tools_return_error_when_disabled() -> None:
    from bourbon.tools.memory import memory_delete, memory_search, memory_status, memory_write

    ctx = ToolContext(workdir=Path("/tmp"))

    assert "error" in json.loads(memory_search(query="test", ctx=ctx))
    assert "error" in json.loads(memory_write(target="project", content="test", ctx=ctx))
    assert "error" in json.loads(memory_delete(memory_id="mem_abc12345", ctx=ctx))
    assert "error" in json.loads(memory_status(ctx=ctx))
