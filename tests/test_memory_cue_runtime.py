"""Tests for cue runtime context extraction."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.cues.runtime import (
    CueRuntimeContext,
    build_runtime_context_from_messages,
    extract_paths_from_tool_input,
)
from bourbon.memory.models import SourceRef
from bourbon.tools import ToolContext


def test_extract_paths_from_tool_input_handles_common_tool_shapes() -> None:
    assert extract_paths_from_tool_input({"file_path": "src/bourbon/memory/store.py"}) == [
        "src/bourbon/memory/store.py"
    ]
    assert extract_paths_from_tool_input({"path": "src/bourbon"}) == ["src/bourbon"]
    assert extract_paths_from_tool_input({"pattern": "src/**/*.py"}) == []


def test_build_runtime_context_from_recent_tool_uses() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Read",
                    "input": {"file_path": "src/bourbon/memory/store.py"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "Edit",
                    "input": {"file_path": "src/bourbon/memory/manager.py"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_3",
                    "name": "Grep",
                    "input": {"path": "src/bourbon/memory"},
                },
            ],
        }
    ]

    ctx = build_runtime_context_from_messages(
        messages,
        workdir=Path("/repo"),
        source_ref=SourceRef(kind="file", file_path="src/bourbon/memory/models.py"),
        session_id="ses_1",
        task_subject="memory cue engine",
    )

    assert ctx.current_files == [
        "src/bourbon/memory/manager.py",
        "src/bourbon/memory/store.py",
    ]
    assert ctx.modified_files == ["src/bourbon/memory/manager.py"]
    assert ctx.touched_files == [
        "src/bourbon/memory",
        "src/bourbon/memory/manager.py",
        "src/bourbon/memory/store.py",
    ]
    assert ctx.source_ref is not None
    assert ctx.source_ref.file_path == "src/bourbon/memory/models.py"
    assert ctx.task_subject == "memory cue engine"


def test_runtime_context_fingerprint_changes_when_current_files_change() -> None:
    base = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/a.py"],
        touched_files=["src/a.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_1",
    )
    changed = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/b.py"],
        touched_files=["src/b.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_1",
    )

    assert base.fingerprint() != changed.fingerprint()


def test_runtime_context_fingerprint_excludes_session_id() -> None:
    first = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/a.py"],
        touched_files=["src/a.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_1",
    )
    second = CueRuntimeContext(
        workdir=Path("/repo"),
        current_files=["src/a.py"],
        touched_files=["src/a.py"],
        modified_files=[],
        symbols=[],
        source_ref=None,
        recent_tool_names=["Read"],
        task_subject="task",
        session_id="ses_2",
    )

    assert first.fingerprint() == second.fingerprint()


def test_tool_context_accepts_cue_runtime_context_factory() -> None:
    runtime_context = CueRuntimeContext(workdir=Path("/repo"))
    ctx = ToolContext(
        workdir=Path("/repo"),
        cue_runtime_context_factory=lambda: runtime_context,
    )

    assert ctx.cue_runtime_context_factory is not None
    assert ctx.cue_runtime_context_factory() is runtime_context
