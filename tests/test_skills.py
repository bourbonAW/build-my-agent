"""Tests for skill loading system."""

import tempfile
from pathlib import Path

import pytest

from bourbon.skills import Skill, SkillLoader


class TestSkill:
    """Test Skill dataclass."""

    def test_render(self):
        """Test skill rendering for LLM."""
        skill = Skill(
            name="python-refactor",
            description="Refactoring patterns",
            body="# Refactoring\n\nBest practices...",
            meta={},
        )
        rendered = skill.render()
        assert "<skill name=\"python-refactor\">" in rendered
        assert "# Refactoring" in rendered
        assert "</skill>" in rendered


class TestSkillLoader:
    """Test SkillLoader."""

    def test_empty_skills(self):
        """Test loader with no skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = SkillLoader(Path(tmpdir))
            assert loader.list_skills() == []
            assert loader.descriptions() == "(no skills loaded)"

    def test_load_skill_from_frontmatter(self):
        """Test parsing skill with YAML frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "python-best-practices"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("""---
name: python-style
description: Python style guidelines
tags: [python, style]
---

# Python Style Guide

Use PEP 8.
""")

            loader = SkillLoader(Path(tmpdir))
            assert "python-style" in loader.get_names()

            skill_content = loader.load("python-style")
            assert "<skill name=\"python-style\">" in skill_content
            assert "PEP 8" in skill_content

    def test_load_skill_from_directory_name(self):
        """Test using directory name when no frontmatter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("# My Skill\n\nContent here.")

            loader = SkillLoader(Path(tmpdir))
            assert "my-skill" in loader.get_names()

    def test_unknown_skill(self):
        """Test loading unknown skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = SkillLoader(Path(tmpdir))
            result = loader.load("unknown")
            assert "Error" in result
            assert "Unknown skill" in result

    def test_list_skills(self):
        """Test listing all skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple skills
            for name in ["skill-a", "skill-b"]:
                skill_dir = Path(tmpdir) / name
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"# {name}")

            loader = SkillLoader(Path(tmpdir))
            skills = loader.list_skills()
            assert len(skills) == 2

    def test_descriptions(self):
        """Test getting skill descriptions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "refactor"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: refactor
description: Code refactoring patterns
---

# Refactoring
""")

            loader = SkillLoader(Path(tmpdir))
            desc = loader.descriptions()
            assert "refactor: Code refactoring patterns" in desc
