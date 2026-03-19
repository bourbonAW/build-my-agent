"""Integration tests for Bourbon."""

import tempfile
from pathlib import Path

import pytest

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.skills import SkillLoader
from bourbon.todos import TodoManager


class TestIntegration:
    """Integration tests."""

    def test_skill_loading(self):
        """Test skill loading from directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test skill
            skill_dir = Path(tmpdir) / "test-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

This is a test.
""")

            loader = SkillLoader(Path(tmpdir))
            assert "test-skill" in loader.get_names()

            content = loader.load("test-skill")
            assert "<skill name=\"test-skill\">" in content
            assert "This is a test." in content

    def test_todo_workflow(self):
        """Test complete todo workflow."""
        todos = TodoManager()

        # Add todos
        todos.update([
            {"content": "Task 1", "status": "in_progress", "activeForm": "cli"},
            {"content": "Task 2", "status": "pending", "activeForm": "cli"},
        ])

        assert todos.has_open_items()

        # Complete first task
        todos.update([
            {"content": "Task 1", "status": "completed", "activeForm": "cli"},
            {"content": "Task 2", "status": "in_progress", "activeForm": "cli"},
        ])

        render = todos.render()
        assert "[x] Task 1" in render
        assert "[>] Task 2" in render

    def test_config_roundtrip(self):
        """Test config save and load."""
        from bourbon.config import ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConfigManager(home_dir=Path(tmpdir))
            manager.ensure_config_dir()

            # Create config
            config = manager.create_default_config(
                anthropic_key="test-key",
            )

            # Load it back
            loaded = manager.load_config()

            assert loaded.llm.anthropic.api_key == "test-key"
            assert loaded.llm.default_provider == "anthropic"
