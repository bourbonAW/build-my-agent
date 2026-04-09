"""Skill tool for Bourbon - Agent Skills compatible."""

from pathlib import Path

from bourbon.skills import SkillManager, SkillValidationError
from bourbon.tools import RiskLevel, ToolContext, register_tool

# Global skill manager instance
_skill_manager: SkillManager | None = None


def get_skill_manager(workdir: Path | None = None) -> SkillManager:
    """Get or create global skill manager."""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager(workdir)
    return _skill_manager


def skill_tool(name: str) -> str:
    """Activate a skill by name.

    Args:
        name: Skill name

    Returns:
        Skill content with structured wrapping, or error message
    """
    manager = get_skill_manager()

    try:
        # Check if already activated (deduplication)
        if manager.is_activated(name):
            skill = manager.get_skill(name)
            if skill:
                return (
                    f"<skill_already_loaded name=\"{name}\"/>\n\nSkill '{name}' is already active."
                )

        content = manager.activate(name)
        return content

    except SkillValidationError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error activating skill '{name}': {e}"


def skill_read_resource_tool(skill_name: str, path: str) -> str:
    """Read a resource file from a skill.

    Args:
        skill_name: Skill name
        path: Relative path to resource

    Returns:
        Resource file content
    """
    manager = get_skill_manager()

    skill = manager.get_skill(skill_name)
    if not skill:
        return f"Error: Skill '{skill_name}' not found"

    resource_path = skill.get_resource_path(path)
    if not resource_path:
        resources = skill.list_resources()
        available = []
        for _category, files in resources.items():
            available.extend(files)
        return (
            f"Error: Resource '{path}' not found in skill '{skill_name}'. "
            f"Available: {available or '(none)'}"
        )

    try:
        return resource_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading resource: {e}"


@register_tool(
    name="Skill",
    aliases=["skill"],
    description="""Activate a skill to load specialized instructions and capabilities.

When to use:
- When starting a task that matches a skill's domain
- When the user mentions a specific domain or technology covered by a skill
- When you need guidance on best practices for a specific task type

The skill will provide detailed instructions, examples, and may include scripts or references.
""",
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the skill to activate (as shown in available_skills catalog)",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments passed to the skill ($ARGUMENTS substitution)",
            },
        },
        "required": ["name"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=False,
    required_capabilities=["skill"],
)
def skill_handler(name: str, args: str = "", *, ctx: ToolContext) -> str:
    """Tool handler for Skill."""
    manager = ctx.skill_manager if ctx.skill_manager is not None else get_skill_manager()

    try:
        if manager.is_activated(name):
            return f'<skill_already_loaded name="{name}"/>\n\nSkill \'{name}\' is already active.'

        content = manager.activate(name, args=args)

        # Inject skill's allowed-tools into discovered tools set
        skill = manager.get_skill(name)
        if skill and skill.allowed_tools and ctx.on_tools_discovered:
            ctx.on_tools_discovered(set(skill.allowed_tools))

        return content
    except SkillValidationError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error activating skill '{name}': {e}"


@register_tool(
    name="SkillResource",
    aliases=["skill_read_resource"],
    description="""Read a resource file from an activated skill.

Use this to load scripts, references, or assets referenced by skill instructions.
""",
    input_schema={
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill containing the resource",
            },
            "path": {
                "type": "string",
                "description": (
                    "Relative path to resource (e.g., 'scripts/extract.py', 'references/guide.md')"
                ),
            },
        },
        "required": ["skill_name", "path"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
)
def skill_resource_handler(skill_name: str, path: str, *, ctx: ToolContext) -> str:
    """Tool handler for SkillResource."""
    manager = ctx.skill_manager if ctx.skill_manager is not None else get_skill_manager()

    skill = manager.get_skill(skill_name)
    if not skill:
        return f"Error: Skill '{skill_name}' not found"

    resource_path = skill.get_resource_path(path)
    if not resource_path:
        resources = skill.list_resources()
        available = []
        for _category, files in resources.items():
            available.extend(files)
        return (
            f"Error: Resource '{path}' not found in skill '{skill_name}'. "
            f"Available: {available or '(none)'}"
        )

    try:
        return resource_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading resource: {e}"
