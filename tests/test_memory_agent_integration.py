from pathlib import Path
from unittest.mock import MagicMock, patch

from bourbon.config import Config


def _make_config(tmp_path: Path, *, enabled: bool) -> Config:
    return Config.from_dict(
        {
            "memory": {
                "enabled": enabled,
                "storage_dir": str(tmp_path / "memory_store"),
            },
            "llm": {
                "default_provider": "anthropic",
                "anthropic": {"api_key": "test-key"},
            },
        }
    )


def test_agent_initializes_memory_manager(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._memory_manager is not None


def test_agent_no_memory_when_disabled(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=False)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._memory_manager is None


def test_agent_prompt_context_has_memory_manager(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    assert agent._prompt_ctx.memory_manager is not None


def test_make_tool_context_includes_memory_fields(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = _make_config(tmp_path, enabled=True)
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    ctx = agent._make_tool_context()
    assert ctx.memory_manager is agent._memory_manager
    assert ctx.memory_actor is not None
    assert ctx.memory_actor.kind == "agent"


def test_agent_tool_context_has_memory_actor_without_cue_runtime_context(tmp_path: Path) -> None:
    from bourbon.agent import Agent

    config = Config()
    config.memory.enabled = True
    config.memory.storage_dir = str(tmp_path / "memory")
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        agent = Agent(config=config, workdir=tmp_path)

    ctx = agent._make_tool_context()

    assert ctx.memory_manager is agent._memory_manager
    assert ctx.memory_actor is not None
    assert ctx.memory_actor.kind == "agent"
    assert not hasattr(ctx, "cue_runtime_context_" + "factory")
