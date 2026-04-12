"""Tests for TaskService business rules."""

from bourbon.tasks.store import TaskStore
from bourbon.tasks.service import TaskService


def test_add_blocks_updates_peer_blocked_by(tmp_path):
    service = TaskService(TaskStore(tmp_path))

    blocker_id = service.create_task("default", "Blocker", "Waiting on target").id
    blocked_id = service.create_task("default", "Blocked", "Needs blocker").id

    updated = service.update_task("default", blocker_id, add_blocks=[blocked_id])
    blocked = service.get_task("default", blocked_id)

    assert updated is not None
    assert blocked is not None
    assert updated.blocks == [blocked_id]
    assert blocked.blocked_by == [blocker_id]


def test_list_tasks_hides_completed_blockers(tmp_path):
    service = TaskService(TaskStore(tmp_path))

    blocker_id = service.create_task("default", "Blocker", "Done soon").id
    blocked_id = service.create_task("default", "Blocked", "Still pending").id
    service.update_task("default", blocker_id, add_blocks=[blocked_id])
    service.update_task("default", blocker_id, status="completed")

    tasks = service.list_tasks("default")
    blocked = next(task for task in tasks if task.id == blocked_id)

    assert blocked.blocked_by == []


def test_claim_task_stores_owner(tmp_path):
    service = TaskService(TaskStore(tmp_path))

    task_id = service.create_task("default", "Own me", "Claim ownership").id

    claimed = service.claim_task("default", task_id, "agent-7")

    assert claimed.owner == "agent-7"
    assert service.get_task("default", task_id).owner == "agent-7"


def test_add_blocked_by_updates_peer_blocks(tmp_path):
    service = TaskService(TaskStore(tmp_path))

    dependent_id = service.create_task("default", "Dependent", "Blocked task").id
    blocker_id = service.create_task("default", "Blocker", "Prerequisite").id

    updated = service.update_task("default", dependent_id, add_blocked_by=[blocker_id])
    blocker = service.get_task("default", blocker_id)

    assert updated.blocked_by == [blocker_id]
    assert blocker is not None
    assert blocker.blocks == [dependent_id]


def test_deleted_status_removes_json_file(tmp_path):
    store = TaskStore(tmp_path)
    service = TaskService(store)

    task = service.create_task("default", "Transient", "Delete me")
    task_path = store._task_path("default", task.id)

    service.update_task("default", task.id, status="deleted")

    assert task_path.exists() is False
    assert service.get_task("default", task.id) is None


def test_deleted_status_cleans_reciprocal_dependency_references(tmp_path):
    service = TaskService(TaskStore(tmp_path))

    upstream_id = service.create_task("default", "Upstream", "Blocks shared task").id
    shared_id = service.create_task("default", "Shared", "Middle dependency").id
    downstream_id = service.create_task("default", "Downstream", "Blocked by shared task").id

    service.update_task("default", upstream_id, add_blocks=[shared_id])
    service.update_task("default", downstream_id, add_blocked_by=[shared_id])

    service.update_task("default", shared_id, status="deleted")

    upstream = service.get_task("default", upstream_id)
    downstream = service.get_task("default", downstream_id)

    assert upstream is not None
    assert downstream is not None
    assert upstream.blocks == []
    assert downstream.blocked_by == []
