"""Tests for Agent streaming support."""

from pathlib import Path


def test_get_session_tokens_returns_estimate():
    """get_session_tokens returns estimated token count."""
    from bourbon.agent import Agent

    agent = object.__new__(Agent)
    agent.messages = [{"role": "user", "content": "Hello world"}]

    # Mock compressor
    class MockCompressor:
        def estimate_tokens(self, msgs):
            return 25

    agent.compressor = MockCompressor()

    tokens = agent.get_session_tokens()
    assert tokens == 25


def test_step_stream_calls_callback_for_chunks():
    """step_stream calls on_text_chunk for each text chunk."""
    from bourbon.agent import Agent
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
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

    # Mock compressor
    class MockCompressor:
        def microcompact(self, msgs):
            pass

        def should_compact(self, msgs):
            return False

    agent.compressor = MockCompressor()

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
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {"type": "text", "text": "Hello"}
            yield {"type": "usage", "input_tokens": 11, "output_tokens": 7}
            yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()
    agent.system_prompt = "You are a test agent"

    class MockCompressor:
        def microcompact(self, msgs):
            pass

        def should_compact(self, msgs):
            return False

    agent.compressor = MockCompressor()

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
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
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

    class MockCompressor:
        def microcompact(self, msgs):
            pass

        def should_compact(self, msgs):
            return False

        token_threshold = 100000

    agent.compressor = MockCompressor()

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


def test_step_stream_returns_confirmation_prompt_when_tool_sets_pending_confirmation():
    """step_stream returns the formatted confirmation prompt for follow-up UI handling."""
    from bourbon.agent import Agent, PendingConfirmation
    from bourbon.config import Config

    config = Config()
    agent = object.__new__(Agent)
    agent.config = config
    agent.workdir = Path.cwd()
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
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

    class MockCompressor:
        def microcompact(self, msgs):
            pass

        def should_compact(self, msgs):
            return False

        token_threshold = 100000

    agent.compressor = MockCompressor()

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
    agent.messages = []
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.pending_confirmation = None
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

    class MockCompressor:
        def microcompact(self, msgs):
            pass

        def should_compact(self, msgs):
            return False

        token_threshold = 100000

    agent.compressor = MockCompressor()

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
