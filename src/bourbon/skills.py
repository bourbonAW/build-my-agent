"""Agent Skills compatible skill system for Bourbon.

Implements the Agent Skills specification:
https://agentskills.io/specification

Key features:
- Progressive disclosure (catalog -> instructions -> resources)
- Multi-scope discovery (project, user, cross-client)
- scripts/, references/, assets/ subdirectories
- Skill context protection from compaction
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


class SkillValidationError(Exception):
    """Skill validation error."""

    pass


@dataclass
class Skill:
    """An Agent Skill.

    Follows the Agent Skills specification structure.
    """

    name: str
    description: str
    location: Path  # Path to SKILL.md
    body: str = ""
    license: str = ""
    compatibility: str = ""
    metadata: dict = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate skill after creation."""
        self._validate_name()

    def _validate_name(self) -> None:
        """Validate skill name per specification."""
        if not self.name:
            raise SkillValidationError("Skill name is required")
        if len(self.name) > 64:
            raise SkillValidationError(f"Skill name exceeds 64 characters: {self.name}")
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", self.name):
            raise SkillValidationError(
                f"Invalid skill name '{self.name}'. "
                "Must be lowercase alphanumeric with hyphens only."
            )

    @property
    def base_dir(self) -> Path:
        """Get the skill's base directory (parent of SKILL.md)."""
        return self.location.parent

    @property
    def scripts_dir(self) -> Path | None:
        """Get scripts directory if it exists."""
        scripts = self.base_dir / "scripts"
        return scripts if scripts.exists() else None

    @property
    def references_dir(self) -> Path | None:
        """Get references directory if it exists."""
        refs = self.base_dir / "references"
        return refs if refs.exists() else None

    @property
    def assets_dir(self) -> Path | None:
        """Get assets directory if it exists."""
        assets = self.base_dir / "assets"
        return assets if assets.exists() else None

    def list_resources(self) -> dict[str, list[str]]:
        """List all bundled resources."""
        resources = {}

        if self.scripts_dir:
            resources["scripts"] = [
                f"scripts/{f.name}" for f in self.scripts_dir.iterdir() if f.is_file()
            ]

        if self.references_dir:
            resources["references"] = [
                f"references/{f.name}" for f in self.references_dir.iterdir() if f.is_file()
            ]

        if self.assets_dir:
            resources["assets"] = [
                f"assets/{f.name}" for f in self.assets_dir.iterdir() if f.is_file()
            ]

        return resources

    def get_resource_path(self, relative_path: str) -> Path | None:
        """Get absolute path to a resource file.

        Args:
            relative_path: Path relative to skill base (e.g., "scripts/extract.py")

        Returns:
            Absolute path if exists, None otherwise
        """
        full_path = self.base_dir / relative_path
        if full_path.exists() and full_path.is_file():
            return full_path
        return None

    def render_catalog_entry(self) -> str:
        """Render skill entry for catalog (Tier 1 disclosure)."""
        lines = [
            "  <skill>",
            f"    <name>{self.name}</name>",
            f"    <description>{self.description}</description>",
            f"    <location>{self.location}</location>",
        ]
        if self.compatibility:
            lines.append(f"    <compatibility>{self.compatibility}</compatibility>")
        lines.append("  </skill>")
        return "\n".join(lines)

    def render_for_activation(self, args: str = "") -> str:
        """Render skill content for model activation (Tier 2 disclosure).

        Args:
            args: Optional arguments string for $ARGUMENTS substitution.

        Returns body with structured wrapping and resource listing.
        """
        lines = [
            f'<skill_content name="{self.name}">',
            self.body,
            "",
            f"Skill directory: {self.base_dir}",
            "Relative paths in this skill are relative to the skill directory.",
        ]

        # Add resource listing
        resources = self.list_resources()
        if resources:
            lines.append("")
            lines.append("<skill_resources>")
            for _category, files in resources.items():
                for f in files:
                    lines.append(f"  <file>{f}</file>")
            lines.append("</skill_resources>")

        lines.append("</skill_content>")
        content = "\n".join(lines)

        # Variable substitution
        content = content.replace("$ARGUMENTS", args)
        content = content.replace("${CLAUDE_SKILL_DIR}", str(self.base_dir))

        return content


class SkillScanner:
    """Scans directories for Agent Skills."""

    # Default scan locations following Agent Skills convention
    DEFAULT_SCOPES = [
        # Project-level (cross-client)
        "{workdir}/.agents/skills",
        "{workdir}/.bourbon/skills",
        "{workdir}/.claude/skills",  # Backward compatibility
        # User-level (cross-client)
        "~/.agents/skills",
        "~/.bourbon/skills",
        "~/.claude/skills",  # Backward compatibility
    ]

    def __init__(self, workdir: Path | None = None, additional_scopes: list[str] | None = None):
        """Initialize scanner.

        Args:
            workdir: Project working directory
            additional_scopes: Additional directory paths to scan
        """
        self.workdir = workdir or Path.cwd()
        self.additional_scopes = additional_scopes or []
        self._diagnostics: list[str] = []

    @property
    def diagnostics(self) -> list[str]:
        """Get diagnostic messages from last scan."""
        return self._diagnostics

    def _expand_path(self, path_template: str) -> Path | None:
        """Expand path template with variables."""
        path_str = path_template.format(workdir=str(self.workdir))
        path = Path(path_str).expanduser()

        if path.exists() and path.is_dir():
            return path
        return None

    def _discover_skill_dirs(self, scope_dir: Path) -> Iterator[Path]:
        """Discover skill directories within a scope.

        A skill directory contains a SKILL.md file.
        """
        if not scope_dir.exists():
            return

        try:
            for item in scope_dir.iterdir():
                if not item.is_dir():
                    continue
                if item.name.startswith("."):
                    continue
                if item.name in ("node_modules", "__pycache__", ".git"):
                    continue

                skill_md = item / "SKILL.md"
                if skill_md.exists() and skill_md.is_file():
                    yield item
        except PermissionError:
            self._diagnostics.append(f"Permission denied: {scope_dir}")

    def scan(self) -> dict[str, Skill]:
        """Scan all scopes and return discovered skills.

        Returns:
            Dict mapping skill names to Skill objects.
            Project-level skills override user-level skills.
        """
        self._diagnostics = []
        skills: dict[str, Skill] = {}

        # Collect all scopes
        all_scopes = []
        for template in self.DEFAULT_SCOPES:
            expanded = self._expand_path(template)
            if expanded:
                all_scopes.append((template, expanded))

        for scope in self.additional_scopes:
            expanded = Path(scope).expanduser()
            if expanded.exists():
                all_scopes.append((scope, expanded))

        # Scan from lowest priority to highest (project overrides user)
        # Reverse so project-level comes last
        for _template, scope_dir in reversed(all_scopes):
            for skill_dir in self._discover_skill_dirs(scope_dir):
                try:
                    skill = self._parse_skill(skill_dir / "SKILL.md")

                    # Check for name collision
                    if skill.name in skills:
                        existing = skills[skill.name]
                        self._diagnostics.append(
                            f"Skill collision: '{skill.name}' in {skill_dir} "
                            f"overrides {existing.location}"
                        )

                    skills[skill.name] = skill

                except SkillValidationError as e:
                    self._diagnostics.append(f"Invalid skill in {skill_dir}: {e}")
                except Exception as e:
                    self._diagnostics.append(f"Error parsing skill in {skill_dir}: {e}")

        return skills

    def _parse_skill(self, skill_md_path: Path) -> Skill:
        """Parse a SKILL.md file.

        Args:
            skill_md_path: Path to SKILL.md

        Returns:
            Parsed Skill object
        """
        text = skill_md_path.read_text(encoding="utf-8")

        # Parse YAML frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)

        if not match:
            raise SkillValidationError("Missing or invalid YAML frontmatter")

        frontmatter_text = match.group(1)
        body = match.group(2).strip()

        # Parse frontmatter fields
        fields = self._parse_frontmatter(frontmatter_text)

        # Required fields
        name = fields.get("name", skill_md_path.parent.name)
        description = fields.get("description", "")

        if not description:
            raise SkillValidationError("Missing required 'description' field")

        # Optional fields
        license_field = fields.get("license", "")
        compatibility = fields.get("compatibility", "")
        allowed_tools = fields.get("allowed-tools", "").split() if "allowed-tools" in fields else []

        # Metadata field (arbitrary key-values)
        metadata = {}
        if "metadata" in fields:
            # Simple YAML-like parsing for metadata
            metadata_text = fields["metadata"]
            for line in metadata_text.strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()

        return Skill(
            name=name,
            description=description,
            location=skill_md_path,
            body=body,
            license=license_field,
            compatibility=compatibility,
            metadata=metadata,
            allowed_tools=allowed_tools,
        )

    def _parse_frontmatter(self, frontmatter_text: str) -> dict[str, str]:
        """Parse YAML frontmatter text into fields.

        Handles common YAML patterns with lenient parsing.
        """
        fields: dict[str, str] = {}
        current_key: str | None = None
        current_value_lines: list[str] = []

        lines = frontmatter_text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                i += 1
                continue

            # Check for new key (key: value or key:)
            if ":" in stripped and not stripped.startswith("#"):
                # Save previous field if exists
                if current_key is not None:
                    fields[current_key] = "\n".join(current_value_lines).strip()

                key, value = stripped.split(":", 1)
                current_key = key.strip()
                current_value_lines = [value.strip()] if value.strip() else []

                # Check if next lines are indented (multi-line value)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if next_line.strip() and not next_line.startswith(" ") and ":" in next_line:
                        # New key
                        break
                    if next_line.startswith(" ") or next_line.startswith("\t"):
                        # Continuation of multi-line value
                        current_value_lines.append(next_line.strip())
                        j += 1
                    elif not next_line.strip():
                        # Empty line in multi-line value
                        current_value_lines.append("")
                        j += 1
                    else:
                        break
                i = j - 1

            i += 1

        # Save last field
        if current_key is not None:
            fields[current_key] = "\n".join(current_value_lines).strip()

        return fields


class SkillManager:
    """Manages skill lifecycle: discovery, catalog, activation."""

    def __init__(self, workdir: Path | None = None):
        """Initialize skill manager.

        Args:
            workdir: Project working directory
        """
        self.workdir = workdir or Path.cwd()
        self._scanner = SkillScanner(workdir)
        self._skills: dict[str, Skill] = {}
        self._activated: set[str] = set()
        self._discover()

    def _discover(self) -> None:
        """Discover all available skills."""
        self._skills = self._scanner.scan()

    @property
    def available_skills(self) -> list[str]:
        """List names of all available skills."""
        return list(self._skills.keys())

    @property
    def activated_skills(self) -> list[str]:
        """List names of currently activated skills."""
        return list(self._activated)

    def get_skill(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def get_catalog(self) -> str:
        """Generate skill catalog for system prompt (Tier 1 disclosure).

        Returns XML-formatted catalog of all available skills.
        """
        if not self._skills:
            return ""

        lines = ["<available_skills>"]
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            lines.append(skill.render_catalog_entry())
        lines.append("</available_skills>")
        return "\n".join(lines)

    def activate(self, name: str, args: str = "") -> str:
        """Activate a skill and return its content (Tier 2 disclosure).

        Args:
            name: Skill name
            args: Optional arguments string for $ARGUMENTS substitution.

        Returns:
            Skill content with structured wrapping

        Raises:
            SkillValidationError: If skill not found
        """
        skill = self._skills.get(name)
        if not skill:
            available = ", ".join(sorted(self._skills.keys()))
            raise SkillValidationError(
                f"Unknown skill '{name}'. Available: {available or '(none)'}"
            )

        # Track activation for deduplication
        self._activated.add(name)

        return skill.render_for_activation(args=args)

    def is_activated(self, name: str) -> bool:
        """Check if a skill has been activated."""
        return name in self._activated

    def get_diagnostics(self) -> list[str]:
        """Get scanner diagnostics."""
        return self._scanner.diagnostics
