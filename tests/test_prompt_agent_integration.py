"""Integration tests for PromptBuilder + ContextInjector wiring in Agent.step()."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bourbon.agent import Agent, PendingConfirmation
from bourbon.config import Config
from bourbon.prompt import ALL_SECTIONS, ContextInjector, PromptBuilder, PromptContext
from bourbon.session.manager import SessionManager
from bourbon.session.storage import TranscriptStore
from bourbon.tools import _get_async_runtime


def _make_agent() -> Agent:
    """Minimal Agent stub for integration tests."""
    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path("/tmp/test-project")
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.todos = None
    agent.skills = MagicMock()
    agent.skills.get_catalog.return_value = ""
    agent.compressor = None
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    agent._discovered_tools = set()
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3

    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=ALL_SECTIONS)
    agent._context_injector = ContextInjector()
    agent.system_prompt = _get_async_runtime().run(
        agent._prompt_builder.build(agent._prompt_ctx)
    )

    base = Path(tempfile.mkdtemp())
    store = TranscriptStore(base_dir=base)
    mgr = SessionManager(store=store, project_name="test", project_dir=str(agent.workdir))
    agent.session = mgr.create_session()
    agent._session_manager = mgr

    from bourbon.access_control.policy import PolicyAction

    agent.access_controller = MagicMock()
    agent.access_controller.evaluate.return_value = MagicMock(action=PolicyAction.ALLOW)
    agent.audit = MagicMock()
    agent.sandbox = MagicMock()
    agent.sandbox.enabled = False

    return agent


class MockLLM:
    def chat(self, **kwargs):
        return {
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


def test_step_rebuilds_system_prompt_on_each_call():
    """system_prompt must be refreshed on every step() call."""
    agent = _make_agent()
    agent.llm = MockLLM()

    original_prompt = agent.system_prompt
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="new prompt v2")

    with patch.object(agent._context_injector, "inject", new=AsyncMock(return_value="hi")):
        agent.step("hi")

    assert agent.system_prompt == "new prompt v2"
    assert agent.system_prompt != original_prompt


def test_step_stores_enriched_message_with_system_reminder():
    """The message written to session must contain <system-reminder>."""
    agent = _make_agent()
    agent.llm = MockLLM()

    with patch.object(
        agent._context_injector,
        "inject",
        new=AsyncMock(
            return_value="<system-reminder>\nWorking directory: /tmp\n</system-reminder>\nhello"
        ),
    ):
        agent.step("hello")

    messages = agent.session.get_messages_for_llm()
    user_messages = [message for message in messages if message["role"] == "user"]
    assert user_messages, "No user messages found in session"
    first_user_content = user_messages[0]["content"]
    if isinstance(first_user_content, list):
        text = " ".join(
            block["text"] for block in first_user_content if block.get("type") == "text"
        )
    else:
        text = first_user_content
    assert "<system-reminder>" in text


def test_step_rebuilds_prompt_before_pending_confirmation_shortcircuit():
    """pending_confirmation path: prompt rebuilt BEFORE short-circuit, inject() never called."""
    agent = _make_agent()
    agent.pending_confirmation = PendingConfirmation(
        tool_name="Bash",
        tool_input={"command": "rm -rf /"},
        error_output="Error: permission denied",
        options=["Retry", "Skip"],
    )
    agent.llm = MockLLM()
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="rebuilt-confirmation-prompt")

    inject_spy = AsyncMock(return_value="should not be called")
    with (
        patch.object(agent._context_injector, "inject", new=inject_spy),
        patch.object(agent, "_handle_confirmation_response", return_value="ok") as handle_spy,
    ):
        agent.step("yes")

    inject_spy.assert_not_called()
    handle_spy.assert_called_once_with("yes")
    assert agent.system_prompt == "rebuilt-confirmation-prompt"
