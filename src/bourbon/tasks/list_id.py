"""Helpers for task list identifiers."""

from __future__ import annotations


def normalize_task_list_id(task_list_id: str) -> str:
    """Normalize and validate a task list identifier for filesystem use."""
    normalized = task_list_id.strip()
    if not normalized:
        raise ValueError("Task list id cannot be empty")
    if "/" in normalized or normalized in {".", ".."}:
        raise ValueError(f"Invalid task list id: {task_list_id}")
    return normalized
