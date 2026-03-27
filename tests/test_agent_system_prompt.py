"""Test Agent accepts custom system_prompt."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bourbon.config import ConfigManager


def test_agent_uses_custom_system_prompt(tmp_path: Path):
    """Agent.__init__ uses provided system_prompt instead of _build_system_prompt()."""
    config = ConfigManager().load_config()

    from bourbon.agent import Agent

    custom_prompt = "You are an evaluator agent."
    agent = Agent(config=config, workdir=tmp_path, system_prompt=custom_prompt)

    assert agent.system_prompt == custom_prompt


def test_agent_default_system_prompt(tmp_path: Path):
    """Agent.__init__ builds default system_prompt when none provided."""
    config = ConfigManager().load_config()

    from bourbon.agent import Agent

    agent = Agent(config=config, workdir=tmp_path)

    assert agent.system_prompt != ""
    assert "evaluator" not in agent.system_prompt.lower()
