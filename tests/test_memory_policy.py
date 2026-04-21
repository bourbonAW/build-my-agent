from bourbon.memory.models import MemoryActor, MemoryKind, MemoryScope
from bourbon.memory.policy import check_write_permission


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
