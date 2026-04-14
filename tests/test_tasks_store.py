"""Tests for file-backed task storage."""

from pathlib import Path
from typing import Any

from bourbon.tasks import TaskRecord, TaskStore


class TestTaskStore:
    def test_create_persists_json_and_highwatermark(self, tmp_path: Path):
        store = TaskStore(tmp_path)

        created = TaskRecord(
            id="",
            subject="Draft spec",
            description="Write task persistence spec",
            status="open",
            metadata={"priority": "high"},
        )
        created_id = store.create("project-alpha", created)

        assert created_id == "1"

        task_dir = tmp_path / "project-alpha"
        assert task_dir.is_dir()
        assert (task_dir / ".lock").exists()
        assert (task_dir / ".highwatermark").read_text() == "1"

        loaded = store.load_task("project-alpha", "1")
        assert loaded.subject == "Draft spec"
        assert loaded.metadata == {"priority": "high"}

    def test_create_allocates_incrementing_string_ids(self, tmp_path: Path):
        store = TaskStore(tmp_path)

        first = store.create("default", TaskRecord(id="", subject="First", description="One"))
        second = store.create("default", TaskRecord(id="", subject="Second", description="Two"))

        assert first == "1"
        assert second == "2"

    def test_list_tasks_returns_records_sorted_by_numeric_id(self, tmp_path: Path):
        store = TaskStore(tmp_path)
        store.create(
            "default",
            TaskRecord(id="", subject="Task 1", description="One", status="open"),
        )
        store.create(
            "default",
            TaskRecord(id="", subject="Task 2", description="Two", status="done"),
        )

        tasks = store.list_tasks("default")

        assert [task.id for task in tasks] == ["1", "2"]
        assert [task.status for task in tasks] == ["open", "done"]

    def test_update_task_rewrites_task_atomically(self, tmp_path: Path):
        store = TaskStore(tmp_path)
        created_id = store.create(
            "default", TaskRecord(id="", subject="Initial", description="Draft", status="open")
        )

        updated = TaskRecord(
            id=created_id,
            subject="Updated",
            description="Published",
            status="done",
            active_form="Completed",
            owner="bourbon",
            blocks=[],
            blocked_by=[],
            metadata={"version": 2},
        )
        store.update_task("default", updated)

        loaded = store.load_task("default", created_id)
        assert loaded.to_dict() == updated.to_dict()

    def test_update_task_with_deleted_status_removes_task_file(self, tmp_path: Path):
        store = TaskStore(tmp_path)
        created_id = store.create(
            "default",
            TaskRecord(id="", subject="Delete via update", description="Transient", status="open"),
        )

        store.update_task(
            "default",
            TaskRecord(
                id=created_id,
                subject="Delete via update",
                description="Transient",
                status="deleted",
            ),
        )

        assert store.load_task("default", created_id) is None
        assert not (tmp_path / "default" / f"{created_id}.json").exists()

    def test_delete_task_removes_task_file(self, tmp_path: Path):
        store = TaskStore(tmp_path)
        created_id = store.create(
            "default",
            TaskRecord(
                id="",
                subject="Delete me",
                description="Transient",
                status="open",
            ),
        )

        store.delete_task("default", created_id)

        assert store.load_task("default", created_id) is None
        assert not (tmp_path / "default" / f"{created_id}.json").exists()

    def test_load_and_list_missing_task_list_are_empty(self, tmp_path: Path):
        store = TaskStore(tmp_path)

        assert store.load_task("missing", "1") is None
        assert store.list_tasks("missing") == []

    def test_load_task_returns_none_when_file_disappears_during_read(
        self, tmp_path: Path, monkeypatch
    ):
        store = TaskStore(tmp_path)
        task_id = store.create(
            "default", TaskRecord(id="", subject="Vanishing", description="Transient")
        )
        task_path = tmp_path / "default" / f"{task_id}.json"
        original_open = Path.open

        def patched_open(path_self: Path, *args: Any, **kwargs: Any):
            if path_self == task_path:
                task_path.unlink()
                raise FileNotFoundError(task_path)
            return original_open(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", patched_open)

        assert store.load_task("default", task_id) is None

    def test_list_tasks_skips_files_that_disappear_during_read(
        self, tmp_path: Path, monkeypatch
    ):
        store = TaskStore(tmp_path)
        kept_id = store.create(
            "default", TaskRecord(id="", subject="Keep", description="Stable")
        )
        removed_id = store.create(
            "default", TaskRecord(id="", subject="Remove", description="Transient")
        )
        removed_path = tmp_path / "default" / f"{removed_id}.json"
        original_open = Path.open

        def patched_open(path_self: Path, *args: Any, **kwargs: Any):
            if path_self == removed_path:
                removed_path.unlink()
                raise FileNotFoundError(removed_path)
            return original_open(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", patched_open)

        tasks = store.list_tasks("default")

        assert [task.id for task in tasks] == [kept_id]
