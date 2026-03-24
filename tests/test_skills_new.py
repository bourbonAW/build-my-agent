"""Test new Agent Skills compatible skill system."""

from pathlib import Path

import pytest

from bourbon.skills import Skill, SkillManager, SkillScanner, SkillValidationError


class TestSkillValidation:
    """Test skill name validation per Agent Skills spec."""

    def test_valid_name_simple(self):
        """Simple lowercase name should be valid."""
        skill = Skill(name="python-refactoring", description="Test", location=Path("/test"))
        assert skill.name == "python-refactoring"

    def test_valid_name_with_numbers(self):
        """Name with numbers should be valid."""
        skill = Skill(name="python3-utils", description="Test", location=Path("/test"))
        assert skill.name == "python3-utils"

    def test_invalid_name_uppercase(self):
        """Uppercase in name should fail."""
        with pytest.raises(SkillValidationError):
            Skill(name="Python-Refactoring", description="Test", location=Path("/test"))

    def test_invalid_name_starting_with_hyphen(self):
        """Name starting with hyphen should fail."""
        with pytest.raises(SkillValidationError):
            Skill(name="-python", description="Test", location=Path("/test"))

    def test_invalid_name_ending_with_hyphen(self):
        """Name ending with hyphen should fail."""
        with pytest.raises(SkillValidationError):
            Skill(name="python-", description="Test", location=Path("/test"))

    def test_invalid_name_consecutive_hyphens(self):
        """Name with consecutive hyphens should fail."""
        with pytest.raises(SkillValidationError):
            Skill(name="python--refactoring", description="Test", location=Path("/test"))

    def test_invalid_name_too_long(self):
        """Name over 64 characters should fail."""
        with pytest.raises(SkillValidationError):
            Skill(name="a" * 65, description="Test", location=Path("/test"))

    def test_invalid_name_empty(self):
        """Empty name should fail."""
        with pytest.raises(SkillValidationError):
            Skill(name="", description="Test", location=Path("/test"))


class TestSkillRendering:
    """Test skill rendering for disclosure."""

    @pytest.fixture
    def sample_skill(self):
        return Skill(
            name="python-refactoring",
            description="Python refactoring patterns and best practices",
            location=Path("/home/user/.agents/skills/python-refactoring/SKILL.md"),
            body="# Python Refactoring\n\n## Extract Function\n\nWhen you see...",
            compatibility="Requires Python 3.8+",
        )

    def test_catalog_entry_format(self, sample_skill):
        """Catalog entry should follow Agent Skills format."""
        entry = sample_skill.render_catalog_entry()
        assert "<skill>" in entry
        assert "<name>python-refactoring</name>" in entry
        assert "<description>" in entry
        assert "<location>" in entry
        assert "<compatibility>" in entry

    def test_activation_rendering(self, sample_skill):
        """Activation rendering should include skill content."""
        content = sample_skill.render_for_activation()
        assert '<skill_content name="python-refactoring">' in content
        assert "# Python Refactoring" in content
        assert "Skill directory:" in content


class TestSkillScanner:
    """Test skill discovery scanning."""

    def test_scan_finds_skills(self, tmp_path):
        """Scanner should find skills in directory."""
        # Create test skill structure
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: A test skill for testing
---

# Test Skill

This is a test skill.
""")

        scanner = SkillScanner(workdir=tmp_path)
        scanner.DEFAULT_SCOPES = [str(tmp_path / ".agents/skills")]

        # Create the skills directory structure
        agents_skills = tmp_path / ".agents/skills"
        agents_skills.mkdir(parents=True)

        # Copy skill to the location
        import shutil

        shutil.copytree(skill_dir, agents_skills / "test-skill")

        skills = scanner.scan()

        assert "test-skill" in skills
        assert skills["test-skill"].description == "A test skill for testing"

    def test_scan_skips_hidden_directories(self, tmp_path):
        """Scanner should skip hidden directories."""
        scanner = SkillScanner(workdir=tmp_path)

        # Create hidden directory with SKILL.md
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "SKILL.md").write_text("---\nname: hidden\n---\n")

        # Manually check that _discover_skill_dirs skips hidden
        skills = list(scanner._discover_skill_dirs(tmp_path))
        assert len(skills) == 0


class TestSkillManager:
    """Test SkillManager lifecycle."""

    def test_get_catalog_empty(self, tmp_path):
        """Empty catalog when no skills."""
        manager = SkillManager(workdir=tmp_path)
        # Override to empty
        manager._skills = {}
        assert manager.get_catalog() == ""

    def test_activate_unknown_skill(self, tmp_path):
        """Activating unknown skill should raise error."""
        manager = SkillManager(workdir=tmp_path)
        manager._skills = {}  # Empty

        with pytest.raises(SkillValidationError) as exc:
            manager.activate("nonexistent")

        assert "Unknown skill" in str(exc.value)

    def test_activate_tracks_activation(self, tmp_path):
        """Activation should be tracked."""
        manager = SkillManager(workdir=tmp_path)

        # Create a mock skill
        skill = Skill(
            name="test-skill",
            description="Test",
            location=tmp_path / "SKILL.md",
            body="# Test",
        )
        manager._skills = {"test-skill": skill}

        assert not manager.is_activated("test-skill")
        manager.activate("test-skill")
        assert manager.is_activated("test-skill")

    def test_deduplication_via_tool(self, tmp_path):
        """Second activation via tool should be deduplicated."""
        from bourbon.tools.skill_tool import get_skill_manager, skill_tool

        # Create skill manager with test skill
        manager = get_skill_manager(tmp_path)
        skill = Skill(
            name="test-skill",
            description="Test",
            location=tmp_path / "SKILL.md",
            body="# Test",
        )
        manager._skills = {"test-skill": skill}

        # First activation
        content1 = skill_tool("test-skill")
        assert "<skill_content" in content1

        # Second activation should indicate already loaded
        content2 = skill_tool("test-skill")
        assert "<skill_already_loaded" in content2
        assert "already active" in content2.lower()


class TestSkillResources:
    """Test skill resource directories."""

    @pytest.fixture
    def skill_with_resources(self, tmp_path):
        """Create a skill with scripts, references, and assets."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()

        # Create SKILL.md
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\n# Test"
        )

        # Create scripts
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.py").write_text("# helper")

        # Create references
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide")

        # Create assets
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "template.json").write_text("{}")

        return Skill(
            name="test-skill",
            description="Test",
            location=skill_dir / "SKILL.md",
        )

    def test_list_resources(self, skill_with_resources):
        """Should list all resource files."""
        resources = skill_with_resources.list_resources()

        assert "scripts/helper.py" in resources.get("scripts", [])
        assert "references/guide.md" in resources.get("references", [])
        assert "assets/template.json" in resources.get("assets", [])

    def test_get_resource_path(self, skill_with_resources):
        """Should resolve resource paths."""
        path = skill_with_resources.get_resource_path("scripts/helper.py")
        assert path is not None
        assert path.exists()
        assert path.name == "helper.py"

    def test_get_nonexistent_resource(self, skill_with_resources):
        """Should return None for non-existent resources."""
        path = skill_with_resources.get_resource_path("scripts/nonexistent.py")
        assert path is None
