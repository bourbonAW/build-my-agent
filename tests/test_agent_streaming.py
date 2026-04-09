"""Tests for Agent streaming support."""

from pathlib import Path

from bourbon.session.manager import Session, SessionManager
from bourbon.session.storage import TranscriptStore


def _setup_mock_session(agent, tmp_path=None):
    """Set up a minimal session for tests that bypass Agent.__init__."""
    import tempfile

    base = tmp_path or Path(tempfile.mkdtemp())
    store = TranscriptStore(base_dir=base)
    mgr = SessionManager(store=store, project_name="test", project_dir=str(agent.workdir))
    agent.session = mgr.create_session()
    agent._session_manager = mgr
    agent._discovered_tools = set()


def _setup_prompt_state(agent):
    """Set up prompt attributes for tests that bypass Agent.__init__."""
    from bourbon.prompt import ContextInjector, PromptBuilder, PromptContext

    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="test prompt")
    agent._context_injector = ContextInjector()


def test_get_session_tokens_returns_estimate():
    """get_session_tokens returns estimated token count."""
    from bourbon.agent import Agent
    from bourbon.session.types import MessageRole, TextBlock, TranscriptMessage

    agent = object.__new__(Agent)
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)

    agent.session.add_message(TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="Hello world")],
    ))

    tokens = agent.get_session_tokens()
    assert tokens > 0


def test_step_stream_calls_callback_for_chunks():
    """step_stream calls on_text_chunk for each text chunk."""
    from bourbon.agent import Agent
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    _setup_prompt_state(agent)
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    # Mock LLM
    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {"type": "text", "text": "Hello "}
            yield {"type": "text", "text": "world"}
            yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
            yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"
    agent.compressor = None  # Not used in new code path

    chunks = []

    def on_chunk(text):
        chunks.append(text)

    result = agent.step_stream("test", on_chunk)

    assert len(chunks) == 2
    assert chunks[0] == "Hello "
    assert chunks[1] == "world"
    assert result == "Hello world"


def test_step_stream_updates_token_usage():
    """step_stream records usage from streaming events."""
    from bourbon.agent import Agent
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    _setup_prompt_state(agent)
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {"type": "text", "text": "Hello"}
            yield {"type": "usage", "input_tokens": 11, "output_tokens": 7}
            yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    result = agent.step_stream("test", lambda _text: None)

    assert result == "Hello"
    assert agent.token_usage == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}


def test_step_stream_handles_tool_calls():
    """step_stream pauses for tool calls and continues."""
    from bourbon.agent import Agent
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    _setup_prompt_state(agent)
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    call_count = 0

    class MockLLM:
        def chat_stream(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: tool use
                yield {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "bash",
                    "input": {"command": "ls"},
                }
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
                yield {"type": "stop", "stop_reason": "tool_use"}
            else:
                # Second call: final text
                yield {"type": "text", "text": "Done"}
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
                yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    # Mock _execute_tools to return simple result
    agent._execute_tools = lambda tools: [
        {"type": "tool_result", "tool_use_id": "tool-1", "content": "file.txt"}
    ]

    chunks = []

    def on_chunk(text):
        chunks.append(text)

    result = agent.step_stream("list files", on_chunk)

    assert call_count == 2  # Two LLM calls
    assert result == "Done"
    assert chunks == ["Done"]


def test_step_stream_persists_usage_to_session_message():
    """step_stream sets usage on the assistant message stored in the session."""
    from bourbon.agent import Agent
    from bourbon.config import Config
    from bourbon.session.types import MessageRole

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    _setup_prompt_state(agent)
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {"type": "text", "text": "Hello"}
            yield {"type": "usage", "input_tokens": 11, "output_tokens": 7}
            yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    agent.step_stream("test", lambda _text: None)

    messages = agent.session.get_messages_for_llm()
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1

    # Verify usage is persisted to the transcript message
    chain = agent.session.chain
    transcript_msgs = chain.build_active_chain()
    assistant_transcript = [m for m in transcript_msgs if m.role == MessageRole.ASSISTANT]
    assert len(assistant_transcript) == 1
    assert assistant_transcript[0].usage is not None, "streaming path must persist usage to session message"
    assert assistant_transcript[0].usage.input_tokens == 11
    assert assistant_transcript[0].usage.output_tokens == 7
    assert assistant_transcript[0].usage.total_tokens == 18


def test_step_stream_returns_confirmation_prompt_when_tool_sets_pending_confirmation():
    """step_stream returns the formatted confirmation prompt for follow-up UI handling."""
    from bourbon.agent import Agent, PendingConfirmation
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    _setup_prompt_state(agent)
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {
                "type": "tool_use",
                "id": "tool-1",
                "name": "bash",
                "input": {"command": "pip install thing"},
            }
            yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
            yield {"type": "stop", "stop_reason": "tool_use"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    def mock_execute(_tools):
        agent.pending_confirmation = PendingConfirmation(
            tool_name="bash",
            tool_input={"command": "pip install thing"},
            error_output="Install failed",
            options=["Install latest version"],
        )
        return []

    agent._execute_tools = mock_execute

    result = agent.step_stream("install thing", lambda _text: None)

    assert "HIGH-RISK OPERATION FAILED" in result
    assert "Operation: bash" in result


def test_step_stream_handles_multiple_tool_calls_per_turn():
    """step_stream collects and executes ALL tool calls in a single turn."""
    from bourbon.agent import Agent
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    _setup_prompt_state(agent)
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    call_count = 0

    class MockLLM:
        def chat_stream(self, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: TWO tool calls in one turn
                yield {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "bash",
                    "input": {"command": "ls"},
                }
                yield {
                    "type": "tool_use",
                    "id": "tool-2",
                    "name": "bash",
                    "input": {"command": "pwd"},
                }
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 5}
                yield {"type": "stop", "stop_reason": "tool_use"}
            else:
                yield {"type": "text", "text": "Done"}
                yield {"type": "usage", "input_tokens": 10, "output_tokens": 2}
                yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    # Track which tool blocks were passed to _execute_tools
    executed_tools = []

    def mock_execute(tools):
        executed_tools.extend(tools)
        return [{"type": "tool_result", "tool_use_id": t["id"], "content": "ok"} for t in tools]

    agent._execute_tools = mock_execute

    result = agent.step_stream("do stuff", lambda t: None)

    # Both tool calls must have been executed
    assert len(executed_tools) == 2
    assert executed_tools[0]["id"] == "tool-1"
    assert executed_tools[1]["id"] == "tool-2"
    assert result == "Done"


def test_handle_confirmation_response_persists_session_metadata():
    """High-risk confirmation follow-up should persist updated session metadata."""
    from bourbon.agent import Agent, PendingConfirmation
    from bourbon.config import Config

    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent.pending_confirmation = PendingConfirmation(
        tool_name="bash",
        tool_input={"command": "pip install thing"},
        error_output="Install failed",
        options=["Retry"],
        confirmation_type="high_risk_failure",
    )
    agent._run_conversation_loop = lambda: "continued"

    result = agent._handle_confirmation_response("Retry")

    assert result == "continued"
    transcript = agent._session_manager.store.load_transcript("test", agent.session.session_id)
    assert len(transcript) == 1
    assert "User decision: Retry" in transcript[0].content[0].text

    metadata = agent._session_manager.store.load_metadata("test", agent.session.session_id)
    assert metadata is not None
    assert metadata.message_count == 1


def test_run_conversation_loop_persists_error_message_metadata():
    """Sync LLM error path should persist the assistant error turn in session metadata."""
    from bourbon.agent import Agent
    from bourbon.config import Config
    from bourbon.llm import LLMError

    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path.cwd()
    _setup_mock_session(agent)
    agent._max_tool_rounds = 50
    agent.system_prompt = "You are a test agent"
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    class FailingLLM:
        def chat(self, **kwargs):
            raise LLMError("boom")

    agent.llm = FailingLLM()

    result = agent._run_conversation_loop()

    assert result == "LLM Error: boom"
    transcript = agent._session_manager.store.load_transcript("test", agent.session.session_id)
    assert len(transcript) == 1
    assert transcript[0].content[0].text == "LLM Error: boom"

    metadata = agent._session_manager.store.load_metadata("test", agent.session.session_id)
    assert metadata is not None
    assert metadata.message_count == 1
