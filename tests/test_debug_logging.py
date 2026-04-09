"""Tests for optional debug logging instrumentation."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_debug_log_writes_jsonl_when_enabled(monkeypatch, tmp_path: Path):
    """Debug helper should append JSONL records when a log path is configured."""
    from bourbon.debug import debug_log

    log_path = tmp_path / "bourbon-debug.jsonl"
    monkeypatch.setenv("BOURBON_DEBUG_LOG", str(log_path))

    debug_log("stream.start", component="repl", turn_id="abc123", chunk_count=0)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["event"] == "stream.start"
    assert record["component"] == "repl"
    assert record["turn_id"] == "abc123"
    assert record["chunk_count"] == 0
    assert "ts" in record


def test_agent_step_stream_emits_debug_events():
    """Streaming agent path should emit boundary logs around the LLM stream."""
    import tempfile
    from pathlib import Path

    from bourbon.agent import Agent
    from bourbon.config import Config
    from bourbon.session.manager import SessionManager
    from bourbon.session.storage import TranscriptStore

    agent = object.__new__(Agent)
    agent.config = Config()
    agent.workdir = Path.cwd()
    agent._rounds_without_todo = 0
    agent._max_tool_rounds = 50
    agent.active_permission_request = None
    agent._discovered_tools = set()
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    agent.system_prompt = "You are a test agent"
    from bourbon.prompt import ContextInjector, PromptBuilder, PromptContext

    agent._prompt_ctx = PromptContext(workdir=agent.workdir, skill_manager=None, mcp_manager=None)
    agent._prompt_builder = PromptBuilder(sections=[], custom_prompt="test prompt")
    agent._context_injector = ContextInjector()

    # Setup session
    base = Path(tempfile.mkdtemp())
    store = TranscriptStore(base_dir=base)
    mgr = SessionManager(store=store, project_name="test", project_dir=str(agent.workdir))
    agent.session = mgr.create_session()
    agent._session_manager = mgr

    class MockLLM:
        def chat_stream(self, **kwargs):
            yield {"type": "text", "text": "Hello"}
            yield {"type": "usage", "input_tokens": 11, "output_tokens": 7}
            yield {"type": "stop", "stop_reason": "end_turn"}

    agent.llm = MockLLM()

    with patch("bourbon.agent.debug_log") as mock_debug_log:
        result = agent.step_stream("test", lambda _text: None)

    assert result == "Hello"
    event_names = [call.args[0] for call in mock_debug_log.call_args_list]
    assert "agent.step_stream.start" in event_names
    assert "agent.stream.llm_call.start" in event_names
    assert "agent.stream.event.text" in event_names
    assert "agent.stream.event.stop" in event_names
    assert "agent.step_stream.complete" in event_names


def test_repl_process_input_streaming_emits_debug_events():
    """REPL streaming path should log chunk and render boundaries."""
    from bourbon.repl import REPL

    repl = object.__new__(REPL)
    repl.console = MagicMock()
    repl.agent = MagicMock()
    repl._handle_permission_request = MagicMock()

    def step_stream(_user_input, on_chunk):
        on_chunk("Hello ")
        on_chunk("world")
        return "Hello world"

    repl.agent.step_stream.side_effect = step_stream
    repl.agent.active_permission_request = None

    live_mock = MagicMock()

    with (
        patch("bourbon.repl.Live") as mock_live,
        patch("bourbon.repl.debug_log") as mock_debug_log,
    ):
        mock_live.return_value.__enter__ = MagicMock(return_value=live_mock)
        mock_live.return_value.__exit__ = MagicMock(return_value=False)
        repl._process_input_streaming("hi")

    event_names = [call.args[0] for call in mock_debug_log.call_args_list]
    assert "repl.stream.start" in event_names
    assert "repl.stream.chunk" in event_names
    assert "repl.stream.response" in event_names
    assert "repl.stream.complete" in event_names


def test_openai_chat_stream_emits_debug_events():
    """OpenAI-compatible streaming client should log stream lifecycle boundaries."""
    from bourbon.llm import OpenAILLMClient

    chunk_1 = MagicMock()
    chunk_1.choices = [MagicMock()]
    chunk_1.choices[0].delta = MagicMock()
    chunk_1.choices[0].delta.content = "Hi"
    chunk_1.choices[0].delta.tool_calls = None
    chunk_1.choices[0].finish_reason = None
    chunk_1.usage = None

    chunk_2 = MagicMock()
    chunk_2.choices = [MagicMock()]
    chunk_2.choices[0].delta = MagicMock()
    chunk_2.choices[0].delta.content = None
    chunk_2.choices[0].delta.tool_calls = None
    chunk_2.choices[0].finish_reason = "stop"
    chunk_2.usage = None

    chunk_3 = MagicMock()
    chunk_3.choices = []
    chunk_3.usage = MagicMock()
    chunk_3.usage.prompt_tokens = 20
    chunk_3.usage.completion_tokens = 4

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = [chunk_1, chunk_2, chunk_3]

    with (
        patch("bourbon.llm.OpenAI", return_value=mock_client),
        patch("bourbon.llm.debug_log") as mock_debug_log,
    ):
        client = OpenAILLMClient(api_key="test", model="gpt-test")
        events = list(client.chat_stream(messages=[{"role": "user", "content": "hi"}]))

    assert [event["type"] for event in events] == ["text", "usage", "stop"]
    event_names = [call.args[0] for call in mock_debug_log.call_args_list]
    assert "llm.openai.stream.start" in event_names
    assert "llm.openai.stream.chunk" in event_names
    assert "llm.openai.stream.complete" in event_names
