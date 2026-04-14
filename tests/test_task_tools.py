"""Tests for persistent task tool registration and dispatch."""

import json
from pathlib import Path
from types import SimpleNamespace

from bourbon.config import Config
from bourbon.tools import ToolContext, definitions, get_registry


def _make_agent(
    storage_dir: Path,
    *,
    session_id: str | None = None,
    default_list_id: str = "fallback",
):
    config = Config()
    config.tasks.storage_dir = str(storage_dir)
    config.tasks.default_list_id = default_list_id
    session = None
    if session_id is not None:
        session = SimpleNamespace(session_id=session_id)
    return SimpleNamespace(config=config, session=session)


def test_task_tools_appear_in_definitions():
    names = {tool["name"] for tool in definitions()}

    assert "TaskCreate" in names
    assert "TaskUpdate" in names
    assert "TaskList" in names
    assert "TaskGet" in names


def test_task_tools_registry_path_uses_session_id_default_list(tmp_path):
    definitions()
    agent = _make_agent(tmp_path, session_id="session-123", default_list_id="ignored-default")
    ctx = ToolContext(workdir=tmp_path, agent=agent)

    created = json.loads(
        get_registry().call(
            "TaskCreate",
            {
                "subject": "Draft service",
                "description": "Implement TaskService",
                "activeForm": "Drafting service",
                "metadata": {"priority": "high"},
            },
            ctx,
        )
    )
    listed = json.loads(get_registry().call("TaskList", {}, ctx))
    fetched = json.loads(get_registry().call("TaskGet", {"taskId": created["id"]}, ctx))
    updated = json.loads(
        get_registry().call(
            "TaskUpdate",
            {
                "taskId": created["id"],
                "status": "in_progress",
                "owner": "agent-1",
            },
            ctx,
        )
    )

    assert created["subject"] == "Draft service"
    assert created["activeForm"] == "Drafting service"
    assert created["metadata"] == {"priority": "high"}
    assert listed == [created]
    assert fetched == created
    assert updated["status"] == "in_progress"
    assert updated["owner"] == "agent-1"
    assert (tmp_path / "session-123" / f"{created['id']}.json").exists()


def test_task_update_tool_can_clear_nullable_fields_with_null(tmp_path):
    definitions()
    agent = _make_agent(tmp_path, session_id="session-456")
    ctx = ToolContext(workdir=tmp_path, agent=agent)

    created = json.loads(
        get_registry().call(
            "TaskCreate",
            {
                "subject": "Clear fields",
                "description": "Exercise null handling",
                "activeForm": "Working the task",
            },
            ctx,
        )
    )
    claimed = json.loads(
        get_registry().call(
            "TaskUpdate",
            {
                "taskId": created["id"],
                "owner": "agent-9",
            },
            ctx,
        )
    )
    cleared = json.loads(
        get_registry().call(
            "TaskUpdate",
            {
                "taskId": created["id"],
                "activeForm": None,
                "owner": None,
            },
            ctx,
        )
    )
    fetched = json.loads(get_registry().call("TaskGet", {"taskId": created["id"]}, ctx))

    assert claimed["owner"] == "agent-9"
    assert cleared["activeForm"] is None
    assert cleared["owner"] is None
    assert fetched["activeForm"] is None
    assert fetched["owner"] is None
