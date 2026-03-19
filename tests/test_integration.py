"""Integration tests for Bourbon."""

import tempfile
from pathlib import Path

import pytest

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.skills import SkillManager
from bourbon.todos import TodoManager


class TestIntegration:
    """Integration tests."""

    def test_skill_loading(self):
        """Test skill loading from directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test skill structure
            agents_skills = Path(tmpdir) / ".agents/skills"
            agents_skills.mkdir(parents=True)
            
            skill_dir = agents_skills / "test-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: A test skill
---

# Test Skill

This is a test.
""")

            manager = SkillManager(workdir=Path(tmpdir))
            assert "test-skill" in manager.available_skills

            content = manager.activate("test-skill")
            assert "<skill_content" in content
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
