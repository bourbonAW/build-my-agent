import pytest
from datetime import UTC, datetime

from bourbon.memory.models import (
    MemoryActor,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from bourbon.memory.policy import check_promote_permission, check_write_permission


def test_explore_subagent_cannot_write_user_kind() -> None:
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    assert check_write_permission(actor, kind=MemoryKind.USER, scope=MemoryScope.USER) is False


def test_user_can_write_all() -> None:
    actor = MemoryActor(kind="user")
    assert (
        check_write_permission(actor, kind=MemoryKind.FEEDBACK, scope=MemoryScope.PROJECT)
        is True
    )


def test_explore_subagent_cannot_write_feedback_kind() -> None:
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    assert (
        check_write_permission(actor, kind=MemoryKind.FEEDBACK, scope=MemoryScope.PROJECT)
        is False
    )


def test_coder_subagent_limited() -> None:
    actor = MemoryActor(kind="subagent", run_id="run_2", agent_type="coder")
    assert (
        check_write_permission(actor, kind=MemoryKind.PROJECT, scope=MemoryScope.SESSION)
        is True
    )
    assert (
        check_write_permission(actor, kind=MemoryKind.REFERENCE, scope=MemoryScope.SESSION)
        is True
    )
    assert check_write_permission(actor, kind=MemoryKind.USER, scope=MemoryScope.USER) is False


def test_check_promote_permission_denies_subagents() -> None:
    actor = MemoryActor(kind="subagent", run_id="run_1", agent_type="explore")
    now = datetime.now(UTC)
    record = MemoryRecord(
        id="mem_1234",
        name="Preference",
        description="desc",
        kind=MemoryKind.USER,
        scope=MemoryScope.USER,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemoryStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        created_by="user",
        content="Always do X.",
    )

    with pytest.raises(PermissionError, match="Subagents cannot promote"):
        check_promote_permission(actor, record)


def test_check_promote_permission_rejects_non_user_scope_records() -> None:
    actor = MemoryActor(kind="user")
    now = datetime.now(UTC)
    record = MemoryRecord(
        id="mem_1234",
        name="Preference",
        description="desc",
        kind=MemoryKind.FEEDBACK,
        scope=MemoryScope.PROJECT,
        confidence=1.0,
        source=MemorySource.USER,
        status=MemoryStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        created_by="user",
        content="Always do X.",
    )

    with pytest.raises(PermissionError, match="Only user-scope records can be promoted"):
        check_promote_permission(actor, record)
