"""Business logic for persistent workflow tasks."""

from __future__ import annotations

from typing import Any

from .store import TaskStore
from .types import TaskRecord

_UNSET = object()


class TaskService:
    """Apply workflow task rules on top of the file-backed store."""

    def __init__(self, store: TaskStore):
        self.store = store

    def create_task(
        self,
        task_list_id: str,
        subject: str,
        description: str,
        active_form: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        task_id = self.store.create(
            task_list_id,
            TaskRecord(
                id="",
                subject=subject,
                description=description,
                active_form=active_form,
                metadata=dict(metadata or {}),
            ),
        )
        record = self.store.load_task(task_list_id, task_id)
        if record is None:
            raise FileNotFoundError(f"Task not found after create: {task_list_id}/{task_id}")
        return record

    def update_task(
        self,
        task_list_id: str,
        task_id: str,
        *,
        subject: str | None = None,
        description: str | None = None,
        status: str | None = None,
        active_form: str | None | object = _UNSET,
        metadata: dict[str, Any] | None | object = _UNSET,
        owner: str | None | object = _UNSET,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> TaskRecord:
        record = self._require_task(task_list_id, task_id)

        if subject is not None:
            record.subject = subject
        if description is not None:
            record.description = description
        if status is not None:
            record.status = status
        if active_form is not _UNSET:
            record.active_form = active_form
        if metadata is not _UNSET:
            record.metadata = dict(metadata or {})
        if owner is not _UNSET:
            record.owner = owner

        peer_updates: dict[str, TaskRecord] = {}

        for blocked_id in add_blocks or []:
            blocked = self._require_task(task_list_id, blocked_id)
            record.blocks = self._append_unique(record.blocks, blocked_id)
            blocked.blocked_by = self._append_unique(blocked.blocked_by, task_id)
            peer_updates[blocked_id] = blocked

        for blocker_id in add_blocked_by or []:
            blocker = self._require_task(task_list_id, blocker_id)
            record.blocked_by = self._append_unique(record.blocked_by, blocker_id)
            blocker.blocks = self._append_unique(blocker.blocks, task_id)
            peer_updates[blocker_id] = blocker

        if record.status == "deleted":
            self._cleanup_peer_dependencies(task_list_id, record)
            self.store.delete_task(task_list_id, task_id)
            return record

        saved = self.store.update_task(task_list_id, record)
        for peer_id, peer in peer_updates.items():
            if peer_id == task_id or peer.status == "deleted":
                continue
            self.store.update_task(task_list_id, peer)
        return saved

    def get_task(self, task_list_id: str, task_id: str) -> TaskRecord | None:
        return self.store.load_task(task_list_id, task_id)

    def list_tasks(self, task_list_id: str) -> list[TaskRecord]:
        tasks = self.store.list_tasks(task_list_id)
        by_id = {task.id: task for task in tasks}
        filtered: list[TaskRecord] = []
        for task in tasks:
            active_blocked_by = [
                blocker_id
                for blocker_id in task.blocked_by
                if (blocker := by_id.get(blocker_id)) is not None
                and blocker.status != "completed"
            ]
            filtered.append(
                TaskRecord(
                    id=task.id,
                    subject=task.subject,
                    description=task.description,
                    status=task.status,
                    active_form=task.active_form,
                    owner=task.owner,
                    blocks=list(task.blocks),
                    blocked_by=active_blocked_by,
                    metadata=dict(task.metadata),
                )
            )
        return filtered

    def claim_task(self, task_list_id: str, task_id: str, owner: str) -> TaskRecord:
        return self.update_task(task_list_id, task_id, owner=owner)

    def _require_task(self, task_list_id: str, task_id: str) -> TaskRecord:
        record = self.store.load_task(task_list_id, task_id)
        if record is None:
            raise FileNotFoundError(f"Task not found: {task_list_id}/{task_id}")
        return record

    def _cleanup_peer_dependencies(self, task_list_id: str, record: TaskRecord) -> None:
        peer_ids = set(record.blocks) | set(record.blocked_by)
        for peer_id in peer_ids:
            peer = self.store.load_task(task_list_id, peer_id)
            if peer is None or peer.status == "deleted":
                continue
            peer.blocks = self._remove_value(peer.blocks, record.id)
            peer.blocked_by = self._remove_value(peer.blocked_by, record.id)
            self.store.update_task(task_list_id, peer)

    @staticmethod
    def _append_unique(values: list[str], value: str) -> list[str]:
        if value in values:
            return list(values)
        return [*values, value]

    @staticmethod
    def _remove_value(values: list[str], value: str) -> list[str]:
        return [item for item in values if item != value]
