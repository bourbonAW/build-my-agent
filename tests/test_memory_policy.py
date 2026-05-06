"""Tests for minimal memory target permissions."""

from __future__ import annotations

import pytest

from bourbon.memory.models import MemoryActor
from bourbon.memory.policy import check_delete_permission, check_write_permission


def test_user_agent_and_system_can_write_user_and_project_targets() -> None:
    for actor in (
        MemoryActor(kind="user"),
        MemoryActor(kind="agent", session_id="ses_1"),
        MemoryActor(kind="system"),
    ):
        assert check_write_permission(actor, target="user") is True
        assert check_write_permission(actor, target="project") is True


def test_subagents_can_write_project_but_not_user_target() -> None:
    actor = MemoryActor(kind="subagent", session_id="ses_1", run_id="run_1")

    assert check_write_permission(actor, target="project") is True
    assert check_write_permission(actor, target="user") is False


def test_delete_permission_rejects_subagents() -> None:
    check_delete_permission(MemoryActor(kind="agent", session_id="ses_1"))
    check_delete_permission(MemoryActor(kind="user"))
    check_delete_permission(MemoryActor(kind="system"))

    with pytest.raises(PermissionError, match="Subagents cannot delete memory"):
        check_delete_permission(MemoryActor(kind="subagent", run_id="run_1"))
