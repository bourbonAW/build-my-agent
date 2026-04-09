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


class TestVariableSubstitution:
    """Test $ARGUMENTS and ${CLAUDE_SKILL_DIR} substitution in render_for_activation."""

    def test_arguments_substitution(self, tmp_path):
        """$ARGUMENTS should be replaced with the args value."""
        skill = Skill(
            name="test-skill",
            description="Test",
            location=tmp_path / "SKILL.md",
            body="Run this command: $ARGUMENTS",
        )
        content = skill.render_for_activation(args="--verbose --dry-run")
        assert "--verbose --dry-run" in content
        assert "$ARGUMENTS" not in content

    def test_arguments_empty_default(self, tmp_path):
        """$ARGUMENTS with no args should be replaced with empty string."""
        skill = Skill(
            name="test-skill",
            description="Test",
            location=tmp_path / "SKILL.md",
            body="Args: [$ARGUMENTS]",
        )
        content = skill.render_for_activation()
        assert "Args: []" in content

    def test_skill_dir_substitution(self, tmp_path):
        """${CLAUDE_SKILL_DIR} should be replaced with skill base directory."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill = Skill(
            name="test-skill",
            description="Test",
            location=skill_dir / "SKILL.md",
            body="Script at: ${CLAUDE_SKILL_DIR}/scripts/run.sh",
        )
        content = skill.render_for_activation()
        assert f"{skill_dir}/scripts/run.sh" in content
        assert "${CLAUDE_SKILL_DIR}" not in content

    def test_both_substitutions_together(self, tmp_path):
        """Both variables should be substituted in the same content."""
        skill_dir = tmp_path / "combo-skill"
        skill_dir.mkdir()
        skill = Skill(
            name="combo-skill",
            description="Test",
            location=skill_dir / "SKILL.md",
            body="Run ${CLAUDE_SKILL_DIR}/run.sh $ARGUMENTS",
        )
        content = skill.render_for_activation(args="--flag")
        assert f"{skill_dir}/run.sh --flag" in content

    def test_no_variables_passthrough(self, tmp_path):
        """Content without variables should be unchanged."""
        skill = Skill(
            name="test-skill",
            description="Test",
            location=tmp_path / "SKILL.md",
            body="No variables here.",
        )
        content = skill.render_for_activation()
        assert "No variables here." in content

    def test_manager_activate_passes_args(self, tmp_path):
        """SkillManager.activate() should forward args to render_for_activation()."""
        manager = SkillManager(workdir=tmp_path)
        skill = Skill(
            name="test-skill",
            description="Test",
            location=tmp_path / "SKILL.md",
            body="Input: $ARGUMENTS",
        )
        manager._skills = {"test-skill": skill}

        content = manager.activate("test-skill", args="hello world")
        assert "Input: hello world" in content
        assert "$ARGUMENTS" not in content


class TestAllowedToolsInjection:
    """Test that allowed-tools from skill frontmatter are injected via on_tools_discovered."""

    def test_allowed_tools_injected_on_activation(self, tmp_path):
        """Activating a skill with allowed-tools should call on_tools_discovered."""
        from bourbon.tools import ToolContext
        from bourbon.tools.skill_tool import skill_handler

        manager = SkillManager(workdir=tmp_path)
        skill = Skill(
            name="web-skill",
            description="Web skill",
            location=tmp_path / "SKILL.md",
            body="# Web",
            allowed_tools=["WebSearch", "WebFetch"],
        )
        manager._skills = {"web-skill": skill}

        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=tmp_path,
            skill_manager=manager,
            on_tools_discovered=discovered.update,
        )

        skill_handler("web-skill", ctx=ctx)

        assert "WebSearch" in discovered
        assert "WebFetch" in discovered

    def test_no_allowed_tools_no_callback(self, tmp_path):
        """Skill without allowed-tools should not call on_tools_discovered."""
        from bourbon.tools import ToolContext
        from bourbon.tools.skill_tool import skill_handler

        manager = SkillManager(workdir=tmp_path)
        skill = Skill(
            name="plain-skill",
            description="Plain skill",
            location=tmp_path / "SKILL.md",
            body="# Plain",
        )
        manager._skills = {"plain-skill": skill}

        call_count = 0

        def tracker(tools: set[str]):
            nonlocal call_count
            call_count += 1

        ctx = ToolContext(
            workdir=tmp_path,
            skill_manager=manager,
            on_tools_discovered=tracker,
        )

        skill_handler("plain-skill", ctx=ctx)
        assert call_count == 0

    def test_allowed_tools_not_injected_when_callback_is_none(self, tmp_path):
        """Should not crash when on_tools_discovered is None."""
        from bourbon.tools import ToolContext
        from bourbon.tools.skill_tool import skill_handler

        manager = SkillManager(workdir=tmp_path)
        skill = Skill(
            name="tools-skill",
            description="Tools skill",
            location=tmp_path / "SKILL.md",
            body="# Tools",
            allowed_tools=["Bash"],
        )
        manager._skills = {"tools-skill": skill}

        ctx = ToolContext(
            workdir=tmp_path,
            skill_manager=manager,
            on_tools_discovered=None,
        )

        # Should not raise
        content = skill_handler("tools-skill", ctx=ctx)
        assert "<skill_content" in content

    def test_args_forwarded_through_handler(self, tmp_path):
        """skill_handler should forward args to manager.activate()."""
        from bourbon.tools import ToolContext
        from bourbon.tools.skill_tool import skill_handler

        manager = SkillManager(workdir=tmp_path)
        skill = Skill(
            name="arg-skill",
            description="Arg skill",
            location=tmp_path / "SKILL.md",
            body="Execute: $ARGUMENTS",
        )
        manager._skills = {"arg-skill": skill}

        ctx = ToolContext(
            workdir=tmp_path,
            skill_manager=manager,
        )

        content = skill_handler("arg-skill", args="my-arg-value", ctx=ctx)
        assert "Execute: my-arg-value" in content
        assert "$ARGUMENTS" not in content
