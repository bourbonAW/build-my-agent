"""Agent module for Bourbon."""

from pathlib import Path
from typing import Any


class Agent:
    """Main agent class."""
    
    def __init__(self, config: dict, workdir: Path | None = None):
        self.config = config
        self.workdir = workdir or Path.cwd()
        self.messages = []
    
    def activate(self, mode: str = "default") -> str:
        """Activate the agent with specified mode.
        
        Args:
            mode: Activation mode (default, advanced, minimal)
            
        Returns:
            Activation status message
        """
        self.mode = mode
        return f"Agent activated in {mode} mode"
    
    def process(self, input_text: str) -> str:
        """Process user input."""
        return f"Processed: {input_text}"


def create_agent(config: dict) -> Agent:
    """Factory function to create an agent."""
    return Agent(config)
