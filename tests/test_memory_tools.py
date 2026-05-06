import json
from pathlib import Path

from bourbon.tools import ToolContext, _ensure_imports, get_registry


def test_memory_tools_registered() -> None:
    _ensure_imports()
    registry = get_registry()
    # Primary names (tool.name) must be snake_case to match plan spec and LLM tool definitions
    tool_primary_names = [tool.name for tool in registry.list_tools()]
    assert "memory_promote" in tool_primary_names
    assert "memory_archive" in tool_primary_names
    assert "memory_search" in tool_primary_names
    assert "memory_write" in tool_primary_names
    assert "memory_status" in tool_primary_names
    # PascalCase aliases still resolve for backward compatibility
    assert registry.get_tool("MemoryPromote") is not None
    assert registry.get_tool("MemoryArchive") is not None
    assert registry.get_tool("MemorySearch") is not None
    assert registry.get_tool("MemoryWrite") is not None
    assert registry.get_tool("MemoryStatus") is not None


def test_memory_promote_tool_schema_and_metadata() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemoryPromote")
    assert tool is not None
    assert tool.risk_level.name == "MEDIUM"
    assert [cap.value for cap in tool.required_capabilities or []] == ["file_write"]
    schema = tool.input_schema
    assert schema["required"] == ["memory_id"]
    assert "note" in schema["properties"]
    assert "stable across multiple turns" in tool.description
    assert "before freeform USER.md content" in tool.description
    assert "exits the MEMORY.md index" in tool.description
    assert "kind in {'user', 'feedback'}" in tool.description


def test_memory_archive_tool_schema_and_metadata() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemoryArchive")
    assert tool is not None
    assert tool.risk_level.name == "MEDIUM"
    assert [cap.value for cap in tool.required_capabilities or []] == ["file_write"]
    schema = tool.input_schema
    assert schema["required"] == ["memory_id", "status"]
    assert schema["properties"]["status"]["enum"] == ["rejected", "stale"]
    assert "rejected" in tool.description
    assert "stale" in tool.description
    assert "removed from prompt injection" in tool.description


def test_memory_write_tool_schema() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemoryWrite")
    assert tool is not None
    schema = tool.input_schema
    assert "content" in schema["properties"]
    assert "kind" in schema["properties"]


def test_memory_search_tool_schema() -> None:
    _ensure_imports()
    registry = get_registry()
    tool = registry.get_tool("MemorySearch")
    assert tool is not None
    schema = tool.input_schema
    assert "query" in schema["properties"]
    assert "status" in schema["properties"]
    assert schema["properties"]["debug_cue"]["type"] == "boolean"
    assert schema["properties"]["debug_cue"]["default"] is False


def test_memory_search_passes_status_filter_to_manager() -> None:
    from bourbon.tools.memory import memory_search

    class _FakeMemoryManager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def search(self, query: str, **kwargs: object) -> list[object]:
            self.calls.append({"query": query, **kwargs})
            return []

    fake_manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=fake_manager)

    memory_search(query="test", ctx=ctx, status=["promoted"])

    assert fake_manager.calls == [
        {
            "query": "test",
            "scope": None,
            "kind": None,
            "status": ["promoted"],
            "limit": None,
        }
    ]


def test_memory_search_omits_query_cue_by_default() -> None:
    from bourbon.tools.memory import memory_search

    class _FakeQueryCue:
        def to_frontmatter(self) -> dict[str, object]:
            return {"recall_need": "weak"}

    class _FakeMemoryManager:
        def search(self, query: str, **kwargs: object) -> list[object]:
            return []

        def get_last_query_cue(self) -> _FakeQueryCue:
            return _FakeQueryCue()

    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=_FakeMemoryManager())

    result = json.loads(memory_search(query="test", ctx=ctx))

    assert result == {"results": []}


def test_memory_search_includes_query_cue_when_debug_requested() -> None:
    from bourbon.memory.cues.models import (
        CueKind,
        CueQualityFlag,
        CueSource,
        MemoryConcept,
        QueryCue,
        RecallNeed,
        RetrievalCue,
    )
    from bourbon.memory.models import MemoryKind, MemoryScope
    from bourbon.tools.memory import memory_search

    class _FakeMemoryManager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.query_cue = QueryCue(
                schema_version="cue.v1",
                interpreter_version="query-cue-test",
                recall_need=RecallNeed.WEAK,
                concepts=[MemoryConcept.WORKFLOW],
                cue_phrases=[
                    RetrievalCue(
                        text="sqlite wal",
                        kind=CueKind.USER_PHRASE,
                        source=CueSource.USER,
                        confidence=1.0,
                    )
                ],
                file_hints=["src/db.py"],
                symbol_hints=["MemoryManager"],
                kind_hints=[MemoryKind.PROJECT],
                scope_hint=MemoryScope.PROJECT,
                uncertainty=0.2,
                fallback_used=True,
                quality_flags=[CueQualityFlag.FALLBACK_USED],
            )

        def search(self, query: str, **kwargs: object) -> list[object]:
            self.calls.append({"query": query, **kwargs})
            return []

        def get_last_query_cue(self) -> QueryCue:
            return self.query_cue

    fake_manager = _FakeMemoryManager()
    ctx = ToolContext(workdir=Path("/tmp"), memory_manager=fake_manager)

    result = json.loads(memory_search(query="test", ctx=ctx, debug_cue=True))

    assert result == {
        "results": [],
        "query_cue": {
            "recall_need": "weak",
            "concepts": ["workflow"],
            "cue_phrases": [
                {
                    "text": "sqlite wal",
                    "kind": "user_phrase",
                    "confidence": 1.0,
                }
            ],
            "file_hints": ["src/db.py"],
            "symbol_hints": ["MemoryManager"],
            "kind_hints": ["project"],
            "scope_hint": "project",
            "uncertainty": 0.2,
            "fallback_used": True,
            "quality_flags": ["fallback_used"],
        },
    }
    assert fake_manager.calls == [
        {
            "query": "test",
            "scope": None,
            "kind": None,
            "status": None,
            "limit": None,
        }
    ]


def test_memory_search_omits_query_cue_when_debug_requested_but_unavailable() -> None:
    from bourbon.tools.memory import memory_search

    class _ManagerWithoutCueGetter:
        def search(self, query: str, **kwargs: object) -> list[object]:
            return []

    class _ManagerWithNoQueryCue:
        def search(self, query: str, **kwargs: object) -> list[object]:
            return []

        def get_last_query_cue(self) -> None:
            return None

    for manager in (_ManagerWithoutCueGetter(), _ManagerWithNoQueryCue()):
        ctx = ToolContext(workdir=Path("/tmp"), memory_manager=manager)

        result = json.loads(memory_search(query="test", ctx=ctx, debug_cue=True))

        assert result == {"results": []}


def test_memory_tools_return_error_when_disabled() -> None:
    from bourbon.tools.memory import (
        memory_archive,
        memory_promote,
        memory_search,
        memory_status,
        memory_write,
    )

    ctx = ToolContext(workdir=Path("/tmp"))

    result = json.loads(memory_search(query="test", ctx=ctx))
    assert "error" in result

    result = json.loads(
        memory_write(
            content="test",
            kind="project",
            scope="project",
            source="user",
            ctx=ctx,
        )
    )
    assert "error" in result

    result = json.loads(memory_promote(memory_id="mem_test0001", ctx=ctx))
    assert "error" in result

    result = json.loads(memory_archive(memory_id="mem_test0001", status="rejected", ctx=ctx))
    assert "error" in result

    result = json.loads(memory_status(ctx=ctx))
    assert "error" in result
