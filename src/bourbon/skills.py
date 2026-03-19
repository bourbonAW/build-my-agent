"""Skill loading system for Bourbon.

Skills are specialized knowledge loaded on demand from ~/.bourbon/skills/.
Each skill is a Markdown file with YAML frontmatter.
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """A loaded skill."""

    name: str
    description: str
    body: str
    meta: dict

    def render(self) -> str:
        """Render skill for LLM context."""
        return f"<skill name=\"{self.name}\">\n{self.body}\n</skill>"


class SkillLoader:
    """Loads skills from the skills directory."""

    def __init__(self, skills_dir: Path | None = None):
        """Initialize skill loader.

        Args:
            skills_dir: Directory containing skills (default: ~/.bourbon/skills)
        """
        if skills_dir is None:
            skills_dir = Path.home() / ".bourbon" / "skills"
        self.skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all skills from the skills directory."""
        if not self.skills_dir.exists():
            return

        for skill_file in sorted(self.skills_dir.rglob("SKILL.md")):
            try:
                skill = self._parse_skill(skill_file)
                self._skills[skill.name] = skill
            except Exception:
                # Skip malformed skills
                continue

    def _parse_skill(self, skill_file: Path) -> Skill:
        """Parse a skill file.

        Format:
            ---
            name: skill-name
            description: Brief description
            tags: [tag1, tag2]
            ---

            # Skill Content

            Markdown content...
        """
        text = skill_file.read_text()

        # Parse YAML frontmatter
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)

        meta = {}
        body = text

        if match:
            frontmatter = match.group(1)
            body = match.group(2).strip()

            for line in frontmatter.strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()

        # Use directory name or frontmatter name
        name = meta.get("name", skill_file.parent.name)
        description = meta.get("description", "-")

        return Skill(
            name=name,
            description=description,
            body=body,
            meta=meta,
        )

    def list_skills(self) -> list[Skill]:
        """List all available skills."""
        return list(self._skills.values())

    def descriptions(self) -> str:
        """Get skill descriptions for system prompt."""
        if not self._skills:
            return "(no skills loaded)"

        lines = []
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            lines.append(f"  - {skill.name}: {skill.description}")
        return "\n".join(lines)

    def load(self, name: str) -> str:
        """Load a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill content wrapped in XML tags, or error message
        """
        skill = self._skills.get(name)
        if not skill:
            available = ", ".join(sorted(self._skills.keys()))
            return f"Error: Unknown skill '{name}'. Available: {available or '(none)'}"

        return skill.render()

    def get_names(self) -> list[str]:
        """Get list of skill names."""
        return list(self._skills.keys())
