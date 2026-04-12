"""File-backed JSON persistence for workflow tasks."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .list_id import normalize_task_list_id
from .locking import FileLock
from .types import TaskRecord


class TaskStore:
    """Persist task records using one directory per task list."""

    HIGH_WATERMARK_FILE = ".highwatermark"
    LOCK_FILE = ".lock"

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def _list_dir(self, task_list_id: str) -> Path:
        return self.base_dir / normalize_task_list_id(task_list_id)

    def _task_path(self, task_list_id: str, task_id: str) -> Path:
        return self._list_dir(task_list_id) / f"{task_id}.json"

    def _highwatermark_path(self, task_list_id: str) -> Path:
        return self._list_dir(task_list_id) / self.HIGH_WATERMARK_FILE

    def _lock_path(self, task_list_id: str) -> Path:
        return self._list_dir(task_list_id) / self.LOCK_FILE

    def _ensure_list_dir(self, task_list_id: str) -> Path:
        list_dir = self._list_dir(task_list_id)
        list_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path(task_list_id).touch(exist_ok=True)
        return list_dir

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)

    def _allocate_task_id(self, task_list_id: str) -> str:
        highwatermark_path = self._highwatermark_path(task_list_id)
        current_value = 0
        if highwatermark_path.exists():
            raw_value = highwatermark_path.read_text().strip()
            if raw_value:
                current_value = int(raw_value)

        next_value = current_value + 1
        highwatermark_path.write_text(str(next_value))
        return str(next_value)

    def create(self, task_list_id: str, record: TaskRecord) -> str:
        self._ensure_list_dir(task_list_id)
        with FileLock(self._lock_path(task_list_id)):
            task_id = self._allocate_task_id(task_list_id)
            stored_record = TaskRecord(
                id=task_id,
                subject=record.subject,
                description=record.description,
                status=record.status,
                active_form=record.active_form,
                owner=record.owner,
                blocks=list(record.blocks),
                blocked_by=list(record.blocked_by),
                metadata=dict(record.metadata),
            )
            self._write_json_atomic(
                self._task_path(task_list_id, task_id), stored_record.to_dict()
            )
            return task_id

    def load_task(self, task_list_id: str, task_id: str) -> TaskRecord | None:
        path = self._task_path(task_list_id, task_id)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as handle:
                return TaskRecord.from_dict(json.load(handle))
        except FileNotFoundError:
            return None

    def list_tasks(self, task_list_id: str) -> list[TaskRecord]:
        list_dir = self._list_dir(task_list_id)
        if not list_dir.exists():
            return []

        tasks = []
        for path in list_dir.glob("*.json"):
            try:
                with path.open(encoding="utf-8") as handle:
                    tasks.append(TaskRecord.from_dict(json.load(handle)))
            except FileNotFoundError:
                continue
        return sorted(tasks, key=lambda record: int(record.id))

    def update_task(self, task_list_id: str, record: TaskRecord) -> TaskRecord:
        self._ensure_list_dir(task_list_id)
        with FileLock(self._lock_path(task_list_id)):
            path = self._task_path(task_list_id, record.id)
            if not path.exists():
                raise FileNotFoundError(f"Task not found: {task_list_id}/{record.id}")
            if record.status == "deleted":
                path.unlink()
                return record
            self._write_json_atomic(path, record.to_dict())
            return record

    def delete_task(self, task_list_id: str, task_id: str) -> None:
        self._ensure_list_dir(task_list_id)
        with FileLock(self._lock_path(task_list_id)):
            path = self._task_path(task_list_id, task_id)
            if path.exists():
                path.unlink()
