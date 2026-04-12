"""Tests for todo management."""

import pytest

from bourbon.todos import TodoItem, TodoManager


class TestTodoItem:
    """Test TodoItem dataclass."""

    def test_create_todo(self):
        """Test creating a todo item."""
        todo = TodoItem(content="Test task", active_form="cli")
        assert todo.content == "Test task"
        assert todo.status == "pending"
        assert todo.active_form == "cli"

    def test_todo_to_dict(self):
        """Test converting todo to dictionary."""
        todo = TodoItem(content="Test", status="in_progress", active_form="repl")
        data = todo.to_dict()
        assert data == {
            "content": "Test",
            "status": "in_progress",
            "activeForm": "repl",
        }


class TestTodoManager:
    """Test TodoManager."""

    def test_empty_todos(self):
        """Test manager with no todos."""
        manager = TodoManager()
        assert manager.items == []
        assert not manager.has_open_items()
        assert manager.render() == "No todos."

    def test_update_single_todo(self):
        """Test updating with single todo."""
        manager = TodoManager()
        result = manager.update([{"content": "Task 1", "status": "pending", "activeForm": "cli"}])
        assert len(manager.items) == 1
        assert manager.items[0].content == "Task 1"
        assert "Task 1" in result

    def test_update_multiple_todos(self):
        """Test updating with multiple todos."""
        manager = TodoManager()
        manager.update(
            [
                {"content": "Task 1", "status": "completed", "activeForm": "cli"},
                {"content": "Task 2", "status": "in_progress", "activeForm": "repl"},
                {"content": "Task 3", "status": "pending", "activeForm": "cli"},
            ]
        )
        assert len(manager.items) == 3
        render = manager.render()
        assert "[x] Task 1" in render
        assert "[>] Task 2 <- repl" in render
        assert "[ ] Task 3" in render
        assert "(1/3 completed)" in render

    def test_only_one_in_progress(self):
        """Test that only one todo can be in_progress."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="Only one in_progress allowed"):
            manager.update(
                [
                    {"content": "Task 1", "status": "in_progress", "activeForm": "a"},
                    {"content": "Task 2", "status": "in_progress", "activeForm": "b"},
                ]
            )

    def test_max_todos_limit(self):
        """Test maximum todo limit."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="Max 20 todos"):
            manager.update(
                [
                    {"content": f"Task {i}", "status": "pending", "activeForm": "cli"}
                    for i in range(21)
                ]
            )

    def test_content_required(self):
        """Test that content is required."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="content required"):
            manager.update([{"content": "", "status": "pending", "activeForm": "cli"}])

    def test_active_form_only_required_for_in_progress(self):
        """Test that activeForm is only required for in_progress todos."""
        manager = TodoManager()
        manager.update(
            [
                {"content": "Task 1", "status": "pending"},
                {"content": "Task 2", "status": "completed"},
            ]
        )

        assert [item.content for item in manager.items] == ["Task 1", "Task 2"]
        assert [item.status for item in manager.items] == ["pending", "completed"]

    def test_in_progress_item_still_requires_active_form(self):
        """Test that in_progress todos still require activeForm."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="activeForm required for in_progress"):
            manager.update([{"content": "Task", "status": "in_progress"}])

    def test_all_completed_items_clear_the_list(self):
        """Test that a completed-only update clears the list."""
        manager = TodoManager()
        result = manager.update([{"content": "Task", "status": "completed"}])

        assert manager.items == []
        assert result == "No todos."

    def test_invalid_status(self):
        """Test invalid status validation."""
        manager = TodoManager()
        with pytest.raises(ValueError, match="invalid status"):
            manager.update([{"content": "Task", "status": "invalid", "activeForm": "cli"}])

    def test_has_open_items(self):
        """Test checking for open items."""
        manager = TodoManager()
        assert not manager.has_open_items()

        manager.update(
            [
                {"content": "Task 1", "status": "completed", "activeForm": "cli"},
            ]
        )
        assert not manager.has_open_items()

        manager.update(
            [
                {"content": "Task 1", "status": "completed", "activeForm": "cli"},
                {"content": "Task 2", "status": "pending", "activeForm": "cli"},
            ]
        )
        assert manager.has_open_items()
