"""Skills module for Bourbon."""

from pathlib import Path
from typing import Any


class SkillManager:
    """Manage skills for the agent."""
    
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.skills = {}
        self._active_skills = set()
    
    def activate(self, name: str) -> str:
        """Activate a skill by name.
        
        Args:
            name: Skill name to activate
            
        Returns:
            Activation result message
        """
        if name in self.skills:
            self._active_skills.add(name)
            return f"Skill '{name}' activated"
        return f"Skill '{name}' not found"
    
    def activated_skills(self) -> list[str]:
        """Return list of currently active skills."""
        return list(self._active_skills)
    
    def register(self, name: str, skill: Any) -> None:
        """Register a new skill."""
        self.skills[name] = skill


class Skill:
    """Base skill class."""
    
    def __init__(self, name: str):
        self.name = name
    
    def execute(self, *args, **kwargs) -> Any:
        """Execute the skill."""
        raise NotImplementedError
