"""Tests for forced final summary when max_tool_rounds is reached.

Bug: The max_rounds branches used to return a hardcoded placeholder string
without calling the LLM, so the user never saw an actual summary.

Fix: `_force_final_summary()` makes one additional LLM call with tools=None,
injecting a transient (non-persisted) user nudge that tells the model to
produce a final answer. Only the assistant summary is persisted to session.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.session.types import MessageRole


class _Span:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_attributes(self, attributes):
        self.attributes.update(attributes)


class _Tracer:
    def __init__(self):
        self.providers = []
        self.recorded = []

    @contextmanager
    def llm_call(self, model, max_tokens, provider="anthropic"):
        self.providers.append(provider)
        yield _Span()

    def record_llm_response(self, span, *, finish_reason, input_tokens, output_tokens):
        self.recorded.append((finish_reason, input_tokens, output_tokens))


def _make_agent(tmp_path, llm):
    """Minimal Agent wired for max-rounds testing."""
    added: list = []
    source_messages = [{"role": "user", "content": "hi"}]

    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = _Tracer()
    agent.llm = llm
    agent.config = Config()
    agent.system_prompt = "system"
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    agent._max_tool_rounds = 1
    agent._tool_definitions = lambda: []
    agent._subagent_debug_fields = lambda: {}
    agent._execute_tools = lambda *a, **kw: []
    agent.active_permission_request = None
    agent._append_task_nudge_if_due = lambda *a, **kw: None
    agent.session = SimpleNamespace(
        # Fresh list on each call so local nudge appends cannot leak.
        get_messages_for_llm=lambda: list(source_messages),
        add_message=added.append,
        save=lambda: None,
    )
    agent._recorded_added = added
    return agent


def test_force_summary_calls_llm_without_tools(tmp_path):
    chat_kwargs: dict = {}

    def chat(**kwargs):
        chat_kwargs.update(kwargs)
        return {
            "content": [{"type": "text", "text": "done summary"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        }

    llm = SimpleNamespace(model="m", chat=chat)
    agent = _make_agent(tmp_path, llm)

    result = agent._force_final_summary()

    assert result == "done summary"
    # Critical: no tools offered so model cannot emit tool_use.
    assert chat_kwargs["tools"] is None
    # Nudge is the last message sent to the model but is NOT persisted.
    nudge = chat_kwargs["messages"][-1]
    assert nudge["role"] == "user"
    assert "maximum tool execution rounds" in nudge["content"]
    assert len(agent._recorded_added) == 1
    persisted = agent._recorded_added[0]
    assert persisted.role == MessageRole.ASSISTANT
    assert persisted.content[0].text == "done summary"
    # Usage accumulated
    assert agent.token_usage["input_tokens"] == 5
    assert agent.token_usage["output_tokens"] == 7
    # Tracer recorded once
    assert agent._tracer.recorded == [("end_turn", 5, 7)]


def test_force_summary_streaming_forwards_chunks(tmp_path):
    stream_kwargs: dict = {}

    def chat_stream(**kwargs):
        stream_kwargs.update(kwargs)
        yield {"type": "text", "text": "hello "}
        yield {"type": "text", "text": "world"}
        yield {"type": "usage", "input_tokens": 3, "output_tokens": 4}
        yield {"type": "stop", "stop_reason": "end_turn"}

    llm = SimpleNamespace(model="m", chat_stream=chat_stream)
    agent = _make_agent(tmp_path, llm)

    received: list[str] = []
    result = agent._force_final_summary(on_text_chunk=received.append)

    assert result == "hello world"
    assert received == ["hello ", "world"]
    assert stream_kwargs["tools"] is None
    assert "maximum tool execution rounds" in stream_kwargs["messages"][-1]["content"]
    assert len(agent._recorded_added) == 1
    assert agent._recorded_added[0].content[0].text == "hello world"
    assert agent._tracer.recorded == [("end_turn", 3, 4)]


def test_force_summary_error_persists_error_message(tmp_path):
    def chat(**kwargs):
        raise RuntimeError("network down")

    llm = SimpleNamespace(model="m", chat=chat)
    agent = _make_agent(tmp_path, llm)

    result = agent._force_final_summary()

    assert "network down" in result
    assert "LLM Error" in result
    assert len(agent._recorded_added) == 1
    assert agent._recorded_added[0].role == MessageRole.ASSISTANT
    assert "network down" in agent._recorded_added[0].content[0].text
    # Token usage unchanged on error
    assert agent.token_usage["input_tokens"] == 0


def test_max_rounds_end_to_end_uses_force_summary(tmp_path):
    """Loop hits max_rounds -> force_summary is invoked -> summary returned."""
    chat_calls: list[dict] = []

    def chat(**kwargs):
        chat_calls.append(dict(kwargs))
        if len(chat_calls) == 1:
            # First in-loop call: return tool_use so loop doesn't exit early.
            return {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "x", "input": {}}
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            }
        # Second call is force_summary.
        return {
            "content": [{"type": "text", "text": "final summary"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        }

    llm = SimpleNamespace(model="m", chat=chat)
    agent = _make_agent(tmp_path, llm)
    agent._build_tool_results_transcript_message = lambda *a, **kw: SimpleNamespace(
        role=MessageRole.USER, content=[]
    )

    result = agent._run_conversation_loop()

    assert result == "final summary"
    # Two LLM calls: in-loop (with tools=[]) + force_summary (tools=None).
    assert len(chat_calls) == 2
    assert chat_calls[0]["tools"] == []
    assert chat_calls[1]["tools"] is None
    nudge = chat_calls[1]["messages"][-1]
    assert "maximum tool execution rounds" in nudge["content"]
    # Nudge must not appear in persisted messages.
    persisted_user_texts = [
        str(getattr(m, "content", ""))
        for m in agent._recorded_added
    ]
    assert not any("maximum tool execution rounds" in c for c in persisted_user_texts)


def test_streaming_loop_max_rounds_uses_force_summary(tmp_path):
    """Streaming loop hits max_rounds -> summary streamed and appended."""
    stream_calls: list[dict] = []

    def chat_stream(**kwargs):
        stream_calls.append(dict(kwargs))
        if len(stream_calls) == 1:
            # In-loop call: tool_use triggers another iteration, but
            # max_tool_rounds=1 so the loop exits after this round.
            yield {"type": "text", "text": "thinking..."}
            yield {
                "type": "tool_use",
                "id": "t1",
                "name": "x",
                "input": {},
            }
            yield {"type": "usage", "input_tokens": 2, "output_tokens": 2}
            yield {"type": "stop", "stop_reason": "tool_use"}
        else:
            # force_summary call
            yield {"type": "text", "text": "the "}
            yield {"type": "text", "text": "summary"}
            yield {"type": "usage", "input_tokens": 4, "output_tokens": 5}
            yield {"type": "stop", "stop_reason": "end_turn"}

    llm = SimpleNamespace(model="m", chat_stream=chat_stream)
    agent = _make_agent(tmp_path, llm)
    agent._build_tool_results_transcript_message = lambda *a, **kw: SimpleNamespace(
        role=MessageRole.USER, content=[]
    )

    received: list[str] = []
    result = agent._run_conversation_loop_stream(received.append)

    # Return value = accumulated in-loop text + summary text.
    assert result == "thinking..." + "the summary"
    # Summary chunks forwarded to on_text_chunk (plus the in-loop "thinking...").
    assert "the " in received and "summary" in received
    # Summary stream call used tools=None.
    assert stream_calls[1]["tools"] is None
