"""Tool registrations for persistent workflow task management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bourbon.config import Config
from bourbon.tasks.service import TaskService
from bourbon.tasks.store import TaskStore
from bourbon.tools import RiskLevel, ToolContext, register_tool

_UNSET = object()


def _resolve_task_list_id(ctx: ToolContext, task_list_id: str | None) -> str:
    if task_list_id:
        return task_list_id

    agent = ctx.agent
    if agent is not None:
        override = getattr(agent, "task_list_id_override", None)
        if override:
            return str(override)

        session = getattr(agent, "session", None)
        session_id = getattr(session, "session_id", None)
        if session_id is not None:
            return str(session_id)

        config = getattr(agent, "config", None)
        tasks_config = getattr(config, "tasks", None)
        default_list_id = getattr(tasks_config, "default_list_id", None)
        if default_list_id:
            return str(default_list_id)

    return "default"


def _task_service(ctx: ToolContext) -> TaskService:
    config = Config()
    if ctx.agent is not None and getattr(ctx.agent, "config", None) is not None:
        config = ctx.agent.config
    storage_dir = Path(config.tasks.storage_dir).expanduser()
    return TaskService(TaskStore(storage_dir))


def _json_output(payload: dict[str, Any] | list[dict[str, Any]] | None) -> str:
    return json.dumps(payload)


@register_tool(
    name="TaskCreate",
    description="Create a persistent workflow task in the current task list.",
    input_schema={
        "type": "object",
        "properties": {
            "taskListId": {"type": "string"},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "activeForm": {"type": ["string", "null"]},
            "metadata": {"type": "object"},
        },
        "required": ["subject", "description"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def task_create_handler(
    subject: str,
    description: str,
    *,
    ctx: ToolContext,
    taskListId: str | None = None,
    activeForm: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    service = _task_service(ctx)
    task_list_id = _resolve_task_list_id(ctx, taskListId)
    record = service.create_task(task_list_id, subject, description, activeForm, metadata)
    ctx.execution_markers.add("task")
    return _json_output(record.to_dict())


@register_tool(
    name="TaskUpdate",
    description="Update a persistent workflow task.",
    input_schema={
        "type": "object",
        "properties": {
            "taskListId": {"type": "string"},
            "taskId": {"type": "string"},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "activeForm": {"type": ["string", "null"]},
            "owner": {"type": ["string", "null"]},
            "metadata": {"type": "object"},
            "addBlocks": {"type": "array", "items": {"type": "string"}},
            "addBlockedBy": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["taskId"],
    },
    risk_level=RiskLevel.MEDIUM,
    required_capabilities=["file_write"],
)
def task_update_handler(
    taskId: str,
    *,
    ctx: ToolContext,
    taskListId: str | None = None,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    activeForm: str | None | object = _UNSET,
    owner: str | None | object = _UNSET,
    metadata: dict[str, Any] | None | object = _UNSET,
    addBlocks: list[str] | None = None,
    addBlockedBy: list[str] | None = None,
) -> str:
    service = _task_service(ctx)
    task_list_id = _resolve_task_list_id(ctx, taskListId)
    kwargs: dict[str, Any] = {
        "subject": subject,
        "description": description,
        "status": status,
        "add_blocks": addBlocks,
        "add_blocked_by": addBlockedBy,
    }
    if activeForm is not _UNSET:
        kwargs["active_form"] = activeForm
    if owner is not _UNSET:
        kwargs["owner"] = owner
    if metadata is not _UNSET:
        kwargs["metadata"] = metadata
    record = service.update_task(task_list_id, taskId, **kwargs)
    ctx.execution_markers.add("task")
    return _json_output(record.to_dict())


@register_tool(
    name="TaskList",
    description="List persistent workflow tasks in the current task list.",
    input_schema={
        "type": "object",
        "properties": {
            "taskListId": {"type": "string"},
        },
    },
    required_capabilities=["file_read"],
    is_read_only=True,
)
def task_list_handler(*, ctx: ToolContext, taskListId: str | None = None) -> str:
    service = _task_service(ctx)
    task_list_id = _resolve_task_list_id(ctx, taskListId)
    records = service.list_tasks(task_list_id)
    return _json_output([record.to_dict() for record in records])


@register_tool(
    name="TaskGet",
    description="Get one persistent workflow task by id.",
    input_schema={
        "type": "object",
        "properties": {
            "taskListId": {"type": "string"},
            "taskId": {"type": "string"},
        },
        "required": ["taskId"],
    },
    required_capabilities=["file_read"],
    is_read_only=True,
)
def task_get_handler(taskId: str, *, ctx: ToolContext, taskListId: str | None = None) -> str:
    service = _task_service(ctx)
    task_list_id = _resolve_task_list_id(ctx, taskListId)
    record = service.get_task(task_list_id, taskId)
    return _json_output(None if record is None else record.to_dict())
