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
