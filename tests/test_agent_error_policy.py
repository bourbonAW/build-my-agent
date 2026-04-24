"""Test agent error handling policy."""

from pathlib import Path

import pytest

from bourbon.agent import Agent
from bourbon.config import Config


class MockLLM:
    """Mock LLM client."""

    def chat(self, **kwargs):
        return {
            "content": [{"type": "text", "text": "Mock"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    def chat_stream(self, **kwargs):
        """Mock streaming for tests."""
        yield {"type": "text", "text": "Mock response"}
        yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
        yield {"type": "stop", "stop_reason": "end_turn"}


@pytest.fixture
def mock_agent():
    """Create agent with mock LLM."""
    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.todos = None

    # Mock skills with new API
    mock_skills = type(
        "obj",
        (object,),
        {
            "get_catalog": lambda self: "",
            "available_skills": [],
        },
    )()
    agent.skills = mock_skills

    agent.compressor = None
    agent.llm = MockLLM()
    from bourbon.prompt import ALL_SECTIONS, ContextInjector, PromptBuilder, PromptContext
    from bourbon.tools import _get_async_runtime

    agent._prompt_ctx = PromptContext(
        workdir=agent.workdir,
        skill_manager=agent.skills,
        mcp_manager=None,
    )
    agent._prompt_builder = PromptBuilder(sections=ALL_SECTIONS)
    agent._context_injector = ContextInjector()
    agent.system_prompt = _get_async_runtime().run(agent._prompt_builder.build(agent._prompt_ctx))
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.active_permission_request = None
    return agent


class TestErrorHandlingPolicy:
    """Test error handling policy in system prompt."""

    def test_critical_error_handling_section_exists(self, mock_agent):
        """System prompt must contain error handling rules."""
        assert "CRITICAL ERROR HANDLING RULES" in mock_agent.system_prompt

    def test_high_risk_policy_exists(self, mock_agent):
        """High risk operations policy must be defined."""
        assert "HIGH RISK" in mock_agent.system_prompt
        assert "MUST STOP and ask" in mock_agent.system_prompt

    def test_no_auto_switch_rule(self, mock_agent):
        """Must forbid automatic version switching."""
        assert "NEVER automatically switch" in mock_agent.system_prompt

    def test_low_risk_policy_exists(self, mock_agent):
        """Low risk policy must exist but must not license blind retry loops."""
        assert "LOW RISK" in mock_agent.system_prompt
        # Agent must trust empty results, not silently retry with tweaked params.
        assert "TRUST the empty result" in mock_agent.system_prompt
        assert "slightly different parameters" in mock_agent.system_prompt

    def test_medium_risk_policy_exists(self, mock_agent):
        """Medium risk operations policy must be defined."""
        assert "MEDIUM RISK" in mock_agent.system_prompt

    def test_pip_install_example(self, mock_agent):
        """Must include pip install version error example."""
        assert "pip install" in mock_agent.system_prompt
        assert (
            "wrong_version" in mock_agent.system_prompt
            or "version not found" in mock_agent.system_prompt
        )

    def test_read_file_example(self, mock_agent):
        """Must include the canonical low-risk file-read tool example."""
        assert "Read" in mock_agent.system_prompt

    def test_memory_write_operations_rule_exists(self, mock_agent):
        """System prompt must tell the agent not to bash-verify memory writes."""
        prompt = mock_agent.system_prompt
        assert "memory_write" in prompt
        assert "memory_promote" in prompt
        assert "memory_archive" in prompt
        assert "not observable in the current session" in prompt

    def test_memory_read_stale_reference_removed(self, mock_agent):
        """memory_read tool does not exist; its reference must not leak into prompt."""
        assert "memory_read" not in mock_agent.system_prompt

    def test_memory_search_stays_in_trust_rules(self, mock_agent):
        """Guard against accidental over-deletion while fixing the stale reference."""
        prompt = mock_agent.system_prompt
        assert "TRUSTING TOOL RESULTS" in prompt
        assert "memory_search" in prompt
