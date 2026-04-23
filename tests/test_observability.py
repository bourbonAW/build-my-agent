"""Tests for OpenTelemetry observability integration."""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from bourbon.access_control.capabilities import CapabilityType
from bourbon.access_control.policy import CapabilityDecision, PolicyAction, PolicyDecision
from bourbon.agent import Agent
from bourbon.config import Config, ObservabilityConfig
from bourbon.observability.manager import ObservabilityManager, _resolve_trace_endpoint
from bourbon.observability.semconv import (
    AGENT_ENTRYPOINT_ATTR,
    AGENT_SPAN_KIND,
    AGENT_SPAN_NAME,
    TOOL_ERROR_ATTR,
    TOOL_IS_ERROR_ATTR,
    TOOL_SPAN_KIND,
    agent_span_attributes,
    llm_request_attributes,
    llm_response_attributes,
    tool_span_attributes,
)
from bourbon.observability.tracer import BourbonTracer
from bourbon.permissions import (
    PermissionAction,
    PermissionChoice,
    PermissionDecision,
    PermissionRequest,
)
from bourbon.permissions.runtime import SuspendedToolRound


def test_observability_config_defaults():
    cfg = ObservabilityConfig()
    assert cfg.enabled is False
    assert cfg.service_name == "bourbon"
    assert cfg.otlp_endpoint == ""
    assert cfg.otlp_headers == {}


def test_config_from_dict_observability():
    cfg = Config.from_dict(
        {
            "observability": {
                "enabled": True,
                "service_name": "agent-x",
                "otlp_endpoint": "http://localhost:4318",
                "otlp_headers": {"Authorization": "Basic abc123"},
            }
        }
    )
    assert cfg.observability.enabled is True
    assert cfg.observability.service_name == "agent-x"
    assert cfg.observability.otlp_endpoint == "http://localhost:4318"
    assert cfg.observability.otlp_headers == {"Authorization": "Basic abc123"}


def test_config_to_dict_includes_observability():
    cfg = Config()
    data = cfg.to_dict()
    assert data["observability"]["enabled"] is False
    assert data["observability"]["service_name"] == "bourbon"


def test_semconv_agent_span_metadata_is_centralized():
    assert AGENT_SPAN_NAME == "invoke_agent bourbon"
    assert AGENT_SPAN_KIND is SpanKind.INTERNAL
    assert agent_span_attributes("/tmp/project", "step_stream") == {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.provider.name": "bourbon",
        "gen_ai.agent.name": "bourbon",
        "bourbon.agent.workdir": "/tmp/project",
        "bourbon.agent.entrypoint": "step_stream",
    }


def test_semconv_llm_and_tool_helpers_build_expected_attributes():
    assert llm_request_attributes("claude-test", 2048, "anthropic") == {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "anthropic",
        "gen_ai.request.model": "claude-test",
        "gen_ai.request.max_tokens": 2048,
    }
    assert llm_response_attributes("tool_use", 12, 8) == {
        "gen_ai.response.finish_reasons": ["tool_use"],
        "gen_ai.usage.input_tokens": 12,
        "gen_ai.usage.output_tokens": 8,
    }
    assert llm_response_attributes("end_turn", None, None) == {
        "gen_ai.response.finish_reasons": ["end_turn"],
    }
    assert tool_span_attributes("Read", "tool-1", True) == {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "Read",
        "gen_ai.tool.call.id": "tool-1",
        "bourbon.tool.concurrent": True,
    }
    assert AGENT_ENTRYPOINT_ATTR == "bourbon.agent.entrypoint"
    assert TOOL_IS_ERROR_ATTR == "bourbon.tool.is_error"
    assert TOOL_ERROR_ATTR == "error.type"
    assert TOOL_SPAN_KIND is SpanKind.INTERNAL


def test_noop_tracer_contexts_do_not_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.agent_step(workdir="/tmp", entrypoint="step") as span:
        span.set_attribute("x", "y")
    with tracer.llm_call(model="m", max_tokens=100, provider="anthropic") as span:
        span.set_attribute("x", "y")
    with tracer.tool_call(name="Read", call_id="id1", concurrent=True) as span:
        span.set_attribute("x", "y")


def test_noop_tracer_helper_methods_do_not_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.llm_call(model="m", max_tokens=100, provider="anthropic") as span:
        tracer.record_llm_response(
            span,
            finish_reason="end_turn",
            input_tokens=3,
            output_tokens=2,
        )
    with tracer.tool_call(name="Read", call_id="id1", concurrent=True) as span:
        tracer.mark_tool_result(
            span,
            is_error=True,
            error_type="tool_error",
            message="bad output",
        )


def test_noop_tracer_exceptions_propagate():
    tracer = BourbonTracer(otel_tracer=None)
    with pytest.raises(ValueError), tracer.agent_step(workdir="/tmp", entrypoint="step"):
        raise ValueError("boom")


def test_manager_disabled_returns_noop_even_with_env(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    manager = ObservabilityManager(ObservabilityConfig(enabled=False))
    assert manager.get_tracer().enabled is False


def test_resolve_trace_endpoint_prefers_trace_specific_env(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://generic:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://trace:4318/v1/traces")
    cfg = ObservabilityConfig(enabled=True, otlp_endpoint="http://config:4318")
    assert _resolve_trace_endpoint(cfg) == "http://trace:4318/v1/traces"


def test_resolve_trace_endpoint_appends_trace_path(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    cfg = ObservabilityConfig(enabled=True, otlp_endpoint="http://localhost:4318")
    assert _resolve_trace_endpoint(cfg) == "http://localhost:4318/v1/traces"


def test_create_tracer_provider_disables_sdk_atexit():
    from bourbon.observability.manager import _create_tracer_provider

    calls = []
    resource = object()

    class FakeTracerProvider:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    provider = _create_tracer_provider(FakeTracerProvider, resource)

    assert isinstance(provider, FakeTracerProvider)
    assert calls == [{"resource": resource, "shutdown_on_exit": False}]


def test_agent_gets_instance_tracer(monkeypatch, tmp_path):
    from bourbon.agent import Agent

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("bourbon.agent.create_client", lambda cfg: SimpleNamespace(model="m"))
    cfg = Config()
    cfg.observability = ObservabilityConfig(enabled=False)
    agent = Agent(config=cfg, workdir=tmp_path)
    assert isinstance(agent._tracer, BourbonTracer)
    assert agent._tracer.enabled is False


def test_disabled_agent_does_not_reuse_enabled_tracer(monkeypatch, tmp_path):
    from bourbon.agent import Agent

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("bourbon.agent.create_client", lambda cfg: SimpleNamespace(model="m"))
    enabled_tracer = BourbonTracer(otel_tracer=object())
    disabled_tracer = BourbonTracer(otel_tracer=None)

    class FakeManager:
        def __init__(self, config):
            self.config = config

        def get_tracer(self):
            return enabled_tracer if self.config.enabled else disabled_tracer

        def shutdown(self):
            pass

    monkeypatch.setattr("bourbon.agent.ObservabilityManager", FakeManager, raising=False)

    enabled = Config()
    enabled.observability = ObservabilityConfig(enabled=True, otlp_endpoint="http://otel:4318")
    disabled = Config()
    disabled.observability = ObservabilityConfig(enabled=False)
    first = Agent(config=enabled, workdir=tmp_path / "a")
    second = Agent(config=disabled, workdir=tmp_path / "b")
    assert first._tracer is enabled_tracer
    assert second._tracer is disabled_tracer


class RecordingTracer:
    def __init__(self):
        self.entrypoints = []
        self.llm_calls = []
        self.events = []

    @contextmanager
    def agent_step(self, workdir: str, entrypoint: str = "step"):
        self.entrypoints.append(entrypoint)
        self.events.append(f"{entrypoint}:enter")
        try:
            yield object()
        finally:
            self.events.append(f"{entrypoint}:exit")

    @contextmanager
    def llm_call(self, model: str, max_tokens: int, provider: str = "anthropic"):
        span = RecordingSpan()
        self.llm_calls.append(
            {
                "model": model,
                "max_tokens": max_tokens,
                "provider": provider,
                "span": span,
            }
        )
        yield span


class RecordingSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class AsyncPromptBuilder:
    async def build(self, prompt_ctx):
        return "system"


class AsyncContextInjector:
    async def inject(self, user_input, prompt_ctx):
        return user_input


def make_entrypoint_agent(tmp_path):
    from bourbon.agent import Agent

    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = RecordingTracer()
    agent._obs_manager = SimpleNamespace(
        force_flush=lambda timeout=None: agent._tracer.events.append(f"flush:{timeout}")
        or True
    )
    agent._prompt_builder = AsyncPromptBuilder()
    agent._prompt_ctx = object()
    agent._context_injector = AsyncContextInjector()
    agent.system_prompt = "system"
    agent.active_permission_request = None
    agent.session = SimpleNamespace(
        chain=SimpleNamespace(message_count=0),
        add_message=lambda msg: None,
        save=lambda: None,
        context_manager=SimpleNamespace(microcompact=lambda: None),
        maybe_compact=lambda: None,
    )
    agent._run_conversation_loop = lambda: "ok"
    agent._run_conversation_loop_stream = lambda on_text_chunk: "stream-ok"
    return agent


def test_step_records_step_entrypoint(tmp_path):
    agent = make_entrypoint_agent(tmp_path)

    assert agent.step("hello") == "ok"

    assert agent._tracer.entrypoints == ["step"]
    assert agent._tracer.events == ["step:enter", "step:exit", "flush:2.0"]


def test_step_stream_records_step_stream_entrypoint(tmp_path):
    agent = make_entrypoint_agent(tmp_path)

    assert agent.step_stream("hello", lambda chunk: None) == "stream-ok"

    assert agent._tracer.entrypoints == ["step_stream"]
    assert agent._tracer.events == ["step_stream:enter", "step_stream:exit", "flush:2.0"]


def test_resume_permission_request_records_resume_entrypoint(tmp_path):
    from bourbon.agent import Agent

    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = RecordingTracer()
    agent._obs_manager = SimpleNamespace(
        force_flush=lambda timeout=None: agent._tracer.events.append(f"flush:{timeout}")
        or True
    )
    agent.suspended_tool_round = None

    assert agent.resume_permission_request(PermissionChoice.REJECT).startswith("Error:")

    assert agent._tracer.entrypoints == ["resume_permission"]
    assert agent._tracer.events == [
        "resume_permission:enter",
        "resume_permission:exit",
        "flush:2.0",
    ]


def make_llm_loop_agent(tmp_path, llm):
    from bourbon.agent import Agent

    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = RecordingTracer()
    agent.llm = llm
    agent.config = Config()
    agent.system_prompt = "system"
    agent.token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    agent._max_tool_rounds = 1
    agent._tool_definitions = lambda: []
    agent._subagent_debug_fields = lambda: {}
    agent._execute_tools = lambda *args, **kwargs: []
    agent.active_permission_request = None
    agent._append_task_nudge_if_due = lambda *args, **kwargs: None
    agent.session = SimpleNamespace(
        get_messages_for_llm=lambda: [{"role": "user", "content": "hi"}],
        add_message=lambda msg: None,
        save=lambda: None,
    )
    return agent


def test_sync_llm_path_uses_record_llm_response_helper(tmp_path):
    llm = SimpleNamespace(
        model="model-x",
        chat=lambda **kwargs: {
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 2, "output_tokens": 1},
        },
    )
    agent = make_llm_loop_agent(tmp_path, llm)
    agent._build_assistant_transcript_message = lambda content: SimpleNamespace(
        uuid="assistant-1", content=content, usage=None
    )
    agent._tracer.recorded_llm_responses = []

    def record_llm_response(span, *, finish_reason, input_tokens, output_tokens):
        agent._tracer.recorded_llm_responses.append(
            (span, finish_reason, input_tokens, output_tokens)
        )

    agent._tracer.record_llm_response = record_llm_response

    assert agent._run_conversation_loop() == "done"

    call = agent._tracer.llm_calls[0]
    assert call["model"] == "model-x"
    assert call["max_tokens"] == 8000
    assert call["provider"] == "anthropic"
    assert agent._tracer.recorded_llm_responses == [(call["span"], "end_turn", 2, 1)]
    assert call["span"].attributes == {}


def test_sync_llm_path_omits_token_attrs_when_usage_missing(tmp_path):
    llm = SimpleNamespace(
        model="model-x",
        chat=lambda **kwargs: {
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
        },
    )
    agent = make_llm_loop_agent(tmp_path, llm)
    agent._build_assistant_transcript_message = lambda content: SimpleNamespace(
        uuid="assistant-1", content=content, usage=None
    )
    agent._tracer.recorded_llm_responses = []

    def record_llm_response(span, *, finish_reason, input_tokens, output_tokens):
        agent._tracer.recorded_llm_responses.append(
            (span, finish_reason, input_tokens, output_tokens)
        )

    agent._tracer.record_llm_response = record_llm_response

    assert agent._run_conversation_loop() == "done"

    call = agent._tracer.llm_calls[0]
    assert agent._tracer.recorded_llm_responses == [
        (call["span"], "end_turn", None, None)
    ]
    assert call["span"].attributes == {}


def test_streaming_llm_path_uses_record_llm_response_helper_once(tmp_path):
    def chat_stream(**kwargs):
        yield {"type": "text", "text": "hi"}
        yield {"type": "usage", "input_tokens": 2, "output_tokens": 1}
        yield {"type": "usage", "input_tokens": 5, "output_tokens": 3}
        yield {"type": "stop", "stop_reason": "end_turn"}

    llm = SimpleNamespace(model="stream-model", chat_stream=chat_stream)
    agent = make_llm_loop_agent(tmp_path, llm)
    agent._build_assistant_transcript_message = lambda content: SimpleNamespace(
        uuid="assistant-1", content=content, usage=None
    )
    agent._tracer.recorded_llm_responses = []

    def record_llm_response(span, *, finish_reason, input_tokens, output_tokens):
        agent._tracer.recorded_llm_responses.append(
            (span, finish_reason, input_tokens, output_tokens)
        )

    agent._tracer.record_llm_response = record_llm_response
    chunks = []

    assert agent._run_conversation_loop_stream(chunks.append) == "hi"

    call = agent._tracer.llm_calls[0]
    assert call["model"] == "stream-model"
    assert call["max_tokens"] == 8000
    assert call["provider"] == "anthropic"
    assert agent._tracer.recorded_llm_responses == [(call["span"], "end_turn", 7, 4)]
    assert call["span"].attributes == {}


CURRENT_ROOT = ContextVar("CURRENT_ROOT", default=None)


class ToolRecordingTracer:
    def __init__(self):
        self.tool_calls = []
        self.tool_results = []
        self.recorded_errors = []

    @contextmanager
    def agent_step(self, workdir: str, entrypoint: str = "step"):
        yield object()

    @contextmanager
    def tool_call(self, name: str, call_id: str, concurrent: bool):
        span = RecordingSpan()
        self.tool_calls.append(
            {
                "name": name,
                "call_id": call_id,
                "concurrent": concurrent,
                "parent": CURRENT_ROOT.get(),
                "span": span,
            }
        )
        yield span

    def mark_error(self, span, error_type: str = "tool_error", message: str = ""):
        span.set_attribute("error.type", error_type)
        span.set_attribute("error.message", message)

    def mark_tool_result(
        self,
        span,
        *,
        is_error: bool,
        error_type: str = "tool_error",
        message: str = "",
    ):
        self.tool_results.append((span, is_error, error_type, message))
        span.set_attribute("bourbon.tool.is_error", is_error)
        if is_error:
            self.mark_error(span, error_type, message)

    def record_error(self, span, exc: Exception):
        self.recorded_errors.append((span, exc))
        span.set_attribute("exception.type", type(exc).__name__)
        self.mark_error(span, type(exc).__name__, str(exc))


def make_queue_tool(*, concurrent: bool):
    return SimpleNamespace(concurrent_safe_for=lambda tool_input: concurrent)


def make_queue_block(tool_id: str, name: str = "Read"):
    return {"id": tool_id, "name": name, "input": {}}


def test_tool_execution_queue_preserves_parent_context_for_parallel_and_serial_tools():
    from bourbon.tools.execution_queue import ToolExecutionQueue

    tracer = ToolRecordingTracer()
    q = ToolExecutionQueue(execute_fn=lambda block: "ok", tracer=tracer)
    q.add(make_queue_block("c1"), make_queue_tool(concurrent=True), 0)
    q.add(make_queue_block("c2"), make_queue_tool(concurrent=True), 1)
    q.add(make_queue_block("s1"), make_queue_tool(concurrent=False), 2)

    token = CURRENT_ROOT.set("root-span")
    try:
        q.execute_all()
    finally:
        CURRENT_ROOT.reset(token)

    assert [call["parent"] for call in tracer.tool_calls] == [
        "root-span",
        "root-span",
        "root-span",
    ]


def test_tool_execution_outcome_marks_tool_span_error():
    from bourbon.tools.execution_queue import ToolExecutionOutcome, ToolExecutionQueue

    tracer = ToolRecordingTracer()
    q = ToolExecutionQueue(
        execute_fn=lambda block: ToolExecutionOutcome(
            content="bad",
            is_error=True,
            error_type="custom_tool_error",
            error_message="bad things happened",
        ),
        tracer=tracer,
    )
    q.add(make_queue_block("err"), make_queue_tool(concurrent=False), 0)

    results = q.execute_all()

    assert results[0]["is_error"] is True
    assert tracer.tool_calls[0]["span"].attributes["bourbon.tool.is_error"] is True
    assert tracer.tool_calls[0]["span"].attributes["error.type"] == "custom_tool_error"


def test_tool_execution_outcome_success_can_start_with_error_text():
    from bourbon.tools.execution_queue import ToolExecutionOutcome, ToolExecutionQueue

    tracer = ToolRecordingTracer()
    q = ToolExecutionQueue(
        execute_fn=lambda block: ToolExecutionOutcome(
            content="Error: no matches found",
            is_error=False,
        ),
        tracer=tracer,
    )
    q.add(make_queue_block("ok"), make_queue_tool(concurrent=False), 0)

    results = q.execute_all()

    assert results == [
        {"type": "tool_result", "tool_use_id": "ok", "content": "Error: no matches found"}
    ]
    assert tracer.tool_calls[0]["span"].attributes["bourbon.tool.is_error"] is False


def test_tool_execution_exception_marks_tool_span_error():
    from bourbon.tools.execution_queue import ToolExecutionQueue

    def bad_execute(block):
        raise ValueError("boom")

    tracer = ToolRecordingTracer()
    q = ToolExecutionQueue(execute_fn=bad_execute, tracer=tracer)
    q.add(make_queue_block("boom"), make_queue_tool(concurrent=False), 0)

    results = q.execute_all()

    assert results[0]["is_error"] is True
    assert results[0]["content"] == "Error: boom"
    assert tracer.tool_calls[0]["span"].attributes["bourbon.tool.is_error"] is True
    assert tracer.tool_calls[0]["span"].attributes["error.type"] == "ValueError"


def test_tool_execution_queue_uses_mark_tool_result_helper_for_semantic_errors():
    from bourbon.tools.execution_queue import ToolExecutionOutcome, ToolExecutionQueue

    tracer = ToolRecordingTracer()
    q = ToolExecutionQueue(
        execute_fn=lambda block: ToolExecutionOutcome(
            content="bad",
            is_error=True,
            error_type="custom_tool_error",
            error_message="bad things happened",
        ),
        tracer=tracer,
    )
    q.add(make_queue_block("err"), make_queue_tool(concurrent=False), 0)

    q.execute_all()

    assert [
        (is_error, error_type, message)
        for _, is_error, error_type, message in tracer.tool_results
    ] == [(True, "custom_tool_error", "bad things happened")]
    assert tracer.recorded_errors == []


def test_tool_execution_queue_exception_uses_record_error_and_mark_tool_result():
    from bourbon.tools.execution_queue import ToolExecutionQueue

    def bad_execute(block):
        raise ValueError("boom")

    tracer = ToolRecordingTracer()
    q = ToolExecutionQueue(execute_fn=bad_execute, tracer=tracer)
    q.add(make_queue_block("boom"), make_queue_tool(concurrent=False), 0)

    q.execute_all()

    assert [
        (is_error, error_type, message)
        for _, is_error, error_type, message in tracer.tool_results
    ] == [(True, "ValueError", "boom")]
    assert [type(exc).__name__ for _, exc in tracer.recorded_errors] == ["ValueError"]


def allow_policy_decision():
    return PolicyDecision(
        action=PolicyAction.ALLOW,
        reason="allowed",
        decisions=[
            CapabilityDecision(
                capability=CapabilityType.FILE_READ,
                action=PolicyAction.ALLOW,
                matched_rule="default",
            )
        ],
    )


def deny_policy_decision():
    return PolicyDecision(
        action=PolicyAction.DENY,
        reason="denied by policy",
        decisions=[
            CapabilityDecision(
                capability=CapabilityType.FILE_READ,
                action=PolicyAction.DENY,
                matched_rule="deny",
            )
        ],
    )


def make_regular_tool_agent():
    agent = object.__new__(Agent)
    agent.workdir = "/tmp"
    agent.access_controller = SimpleNamespace(evaluate=lambda name, inp: allow_policy_decision())
    agent._record_policy_decision = lambda **kwargs: None
    agent.sandbox = SimpleNamespace(enabled=False)
    agent.audit = SimpleNamespace(record=lambda event: None)
    agent.skills = SimpleNamespace()
    agent._discovered_tools = set()
    agent._tool_consecutive_failures = {}
    agent._max_tool_consecutive_failures = 3
    return agent


def test_regular_tool_outcome_keeps_error_prefixed_success_successful(monkeypatch):
    agent = make_regular_tool_agent()
    registry = SimpleNamespace(call=lambda name, inp, ctx: "Error: no matches found")
    monkeypatch.setattr("bourbon.agent.get_registry", lambda: registry)
    monkeypatch.setattr("bourbon.agent.get_tool_with_metadata", lambda name: None)

    outcome = agent._execute_regular_tool_outcome(
        "Grep",
        {"pattern": "missing"},
        skip_policy_check=True,
    )

    assert outcome.content == "Error: no matches found"
    assert outcome.is_error is False


def test_regular_tool_outcome_marks_policy_denial_error():
    agent = make_regular_tool_agent()
    agent.access_controller = SimpleNamespace(evaluate=lambda name, inp: deny_policy_decision())

    outcome = agent._execute_regular_tool_outcome("Read", {"path": "secret.txt"})

    assert outcome.content == "Denied: denied by policy"
    assert outcome.is_error is True
    assert outcome.error_type == "permission_denied"


def make_direct_tool_agent(tmp_path):
    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = ToolRecordingTracer()
    agent.on_tool_start = None
    agent.on_tool_end = None
    agent.active_permission_request = None
    agent.suspended_tool_round = None
    agent.session_permissions = SimpleNamespace(add=lambda candidate: None)
    agent._subagent_tool_denial = lambda tool_name: None
    agent._permission_decision_for_tool = lambda tool_name, tool_input: PermissionDecision(
        action=PermissionAction.ALLOW,
        reason="allowed",
    )
    agent._manual_compact = lambda: None
    agent._execute_regular_tool_outcome = lambda *args, **kwargs: __import__(
        "bourbon.tools.execution_queue", fromlist=["ToolExecutionOutcome"]
    ).ToolExecutionOutcome(content="ok")
    agent._build_tool_results_transcript_message = lambda results, source_uuid: SimpleNamespace(
        results=results
    )
    agent._append_task_nudge_if_due = lambda *args, **kwargs: None
    agent._run_conversation_loop = lambda: "continued"
    agent.session = SimpleNamespace(add_message=lambda msg: None, save=lambda: None)
    return agent


def test_direct_tool_span_records_subagent_tool_denial(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    agent._subagent_tool_denial = lambda tool_name: "Denied for subagent"

    results = agent._execute_tools(
        [{"id": "deny1", "name": "Bash", "input": {}}],
        source_assistant_uuid="assistant",
    )

    assert results[0]["is_error"] is True
    call = agent._tracer.tool_calls[0]
    assert call["name"] == "Bash"
    assert call["span"].attributes["bourbon.tool.is_error"] is True
    assert call["span"].attributes["error.type"] == "subagent_tool_denial"


def test_direct_tool_span_records_compress(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    compacted = []
    agent._manual_compact = lambda: compacted.append(True)

    results = agent._execute_tools(
        [{"id": "compact1", "name": "compress", "input": {}}],
        source_assistant_uuid="assistant",
    )

    assert results[0]["content"] == "Compressing context..."
    assert compacted == [True]
    call = agent._tracer.tool_calls[0]
    assert call["name"] == "compress"
    assert call["span"].attributes["bourbon.tool.is_error"] is False


def test_direct_tool_span_records_policy_denial(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    agent._permission_decision_for_tool = lambda tool_name, tool_input: PermissionDecision(
        action=PermissionAction.DENY,
        reason="blocked",
    )

    results = agent._execute_tools(
        [{"id": "deny-policy", "name": "Read", "input": {}}],
        source_assistant_uuid="assistant",
    )

    assert results[0]["content"] == "Denied: blocked"
    call = agent._tracer.tool_calls[0]
    assert call["span"].attributes["bourbon.tool.is_error"] is True
    assert call["span"].attributes["error.type"] == "permission_denied"


def test_direct_tool_span_records_permission_ask(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    agent._permission_decision_for_tool = lambda tool_name, tool_input: PermissionDecision(
        action=PermissionAction.ASK,
        reason="needs approval",
    )

    results = agent._execute_tools(
        [{"id": "ask1", "name": "Bash", "input": {"command": "pip install flask"}}],
        source_assistant_uuid="assistant",
    )

    assert results == []
    assert agent.active_permission_request is not None
    call = agent._tracer.tool_calls[0]
    assert call["span"].attributes["bourbon.tool.is_error"] is False
    assert call["span"].attributes["bourbon.tool.suspended"] is True


def test_direct_tool_span_records_unknown_tool(tmp_path, monkeypatch):
    agent = make_direct_tool_agent(tmp_path)
    monkeypatch.setattr("bourbon.agent.get_tool_with_metadata", lambda name: None)

    results = agent._execute_tools(
        [{"id": "unknown1", "name": "MissingTool", "input": {}}],
        source_assistant_uuid="assistant",
    )

    assert results[0]["is_error"] is True
    call = agent._tracer.tool_calls[0]
    assert call["name"] == "MissingTool"
    assert call["span"].attributes["bourbon.tool.is_error"] is True
    assert call["span"].attributes["error.type"] == "unknown_tool"


def make_permission_request(tool_name: str = "Bash") -> PermissionRequest:
    return PermissionRequest(
        request_id="req1",
        tool_use_id="tool1",
        tool_name=tool_name,
        tool_input={"command": "pip install flask"},
        title="Needs approval",
        description="Approve",
        reason="needs approval",
    )


def suspend_direct_tool_agent(agent, request: PermissionRequest) -> None:
    agent.suspended_tool_round = SuspendedToolRound(
        source_assistant_uuid="assistant",
        tool_use_blocks=[
            {
                "id": request.tool_use_id,
                "name": request.tool_name,
                "input": request.tool_input,
            }
        ],
        completed_results=[],
        next_tool_index=0,
        active_request=request,
    )


def test_resume_permission_request_reject_records_tool_span(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    suspend_direct_tool_agent(agent, make_permission_request())

    assert agent.resume_permission_request(PermissionChoice.REJECT) == "continued"

    call = agent._tracer.tool_calls[0]
    assert call["name"] == "Bash"
    assert call["span"].attributes["bourbon.tool.is_error"] is True
    assert call["span"].attributes["error.type"] == "permission_rejected"


def test_resume_permission_request_approved_execution_records_tool_span(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    suspend_direct_tool_agent(agent, make_permission_request())

    assert agent.resume_permission_request(PermissionChoice.ALLOW_ONCE) == "continued"

    call = agent._tracer.tool_calls[0]
    assert call["name"] == "Bash"
    assert call["span"].attributes["bourbon.tool.is_error"] is False


def test_resume_permission_request_subagent_denial_after_approval_records_tool_span(tmp_path):
    agent = make_direct_tool_agent(tmp_path)
    agent._subagent_tool_denial = lambda tool_name: "Denied after approval"
    suspend_direct_tool_agent(agent, make_permission_request())

    assert agent.resume_permission_request(PermissionChoice.ALLOW_ONCE) == "continued"

    call = agent._tracer.tool_calls[0]
    assert call["name"] == "Bash"
    assert call["span"].attributes["bourbon.tool.is_error"] is True
    assert call["span"].attributes["error.type"] == "subagent_tool_denial"


def test_resume_permission_request_uses_mark_tool_result_helper(tmp_path):
    tracer = ToolRecordingTracer()

    def mark_tool_result(span, *, is_error, error_type="tool_error", message=""):
        tracer.tool_results.append((is_error, error_type, message))

    tracer.mark_tool_result = mark_tool_result
    tracer.record_error = lambda span, exc: None
    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = tracer
    agent._obs_manager = SimpleNamespace(force_flush=lambda timeout=None: True)
    agent.session_permissions = SimpleNamespace(add=lambda candidate: None)
    agent._subagent_tool_denial = lambda tool_name: None
    agent._execute_regular_tool_outcome = lambda *args, **kwargs: SimpleNamespace(
        content="bad output",
        is_error=True,
        error_type="tool_error",
        error_message="bad output",
    )
    agent._execute_tools = lambda *args, **kwargs: []
    agent._build_tool_results_transcript_message = lambda *args, **kwargs: SimpleNamespace(content=[])
    agent._append_task_nudge_if_due = lambda *args, **kwargs: None
    agent._run_conversation_loop = lambda: "continued"
    agent.session = SimpleNamespace(add_message=lambda msg: None, save=lambda: None)
    request = PermissionRequest(
        request_id="req-1",
        tool_use_id="tool-1",
        tool_name="Read",
        tool_input={"path": "README.md"},
        title="Read file",
        description="Read README.md",
        reason="approval",
    )
    agent.suspended_tool_round = SuspendedToolRound(
        source_assistant_uuid=None,
        tool_use_blocks=[{"id": "tool-1"}],
        completed_results=[],
        next_tool_index=0,
        active_request=request,
    )

    agent.resume_permission_request(PermissionChoice.ALLOW_ONCE)
    assert tracer.tool_results == [
        (False, "tool_error", ""),
        (True, "tool_error", "bad output"),
    ]


def _make_test_tracer():
    pytest.importorskip("opentelemetry.sdk", reason="opentelemetry SDK not installed")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return BourbonTracer(provider.get_tracer("bourbon-test")), exporter


def _span_named(exporter, name: str):
    matches = [span for span in exporter.get_finished_spans() if span.name == name]
    assert matches, f"span {name!r} not found"
    return matches[0]


def test_otel_root_span_records_agent_attributes():
    tracer, exporter = _make_test_tracer()

    with tracer.agent_step(workdir="/tmp/project", entrypoint="step_stream"):
        pass

    span = _span_named(exporter, "invoke_agent bourbon")
    assert span.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert span.attributes["gen_ai.provider.name"] == "bourbon"
    assert span.attributes["gen_ai.agent.name"] == "bourbon"
    assert span.attributes["bourbon.agent.workdir"] == "/tmp/project"
    assert span.attributes["bourbon.agent.entrypoint"] == "step_stream"


def test_otel_agent_span_uses_explicit_kind():
    tracer, exporter = _make_test_tracer()

    with tracer.agent_step(workdir="/tmp/project", entrypoint="step"):
        pass

    span = _span_named(exporter, "invoke_agent bourbon")
    assert span.kind is SpanKind.INTERNAL


def test_otel_llm_span_records_request_and_response_attributes():
    tracer, exporter = _make_test_tracer()

    with tracer.llm_call(model="model-x", max_tokens=123, provider="anthropic") as span:
        span.set_attribute("gen_ai.response.finish_reasons", ["end_turn"])
        span.set_attribute("gen_ai.usage.input_tokens", 10)
        span.set_attribute("gen_ai.usage.output_tokens", 4)

    span = _span_named(exporter, "chat model-x")
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert span.attributes["gen_ai.provider.name"] == "anthropic"
    assert span.attributes["gen_ai.request.model"] == "model-x"
    assert span.attributes["gen_ai.request.max_tokens"] == 123
    assert span.attributes["gen_ai.response.finish_reasons"] == ("end_turn",)
    assert span.attributes["gen_ai.usage.input_tokens"] == 10
    assert span.attributes["gen_ai.usage.output_tokens"] == 4


def test_record_llm_response_sets_all_response_attributes():
    tracer, exporter = _make_test_tracer()

    with tracer.llm_call(model="model-x", max_tokens=123, provider="anthropic") as span:
        tracer.record_llm_response(
            span,
            finish_reason="end_turn",
            input_tokens=10,
            output_tokens=4,
        )

    span = _span_named(exporter, "chat model-x")
    assert span.kind is SpanKind.CLIENT
    assert span.attributes["gen_ai.response.finish_reasons"] == ("end_turn",)
    assert span.attributes["gen_ai.usage.input_tokens"] == 10
    assert span.attributes["gen_ai.usage.output_tokens"] == 4


def test_record_llm_response_omits_token_attributes_when_usage_missing():
    tracer, exporter = _make_test_tracer()

    with tracer.llm_call(model="model-x", max_tokens=123, provider="anthropic") as span:
        tracer.record_llm_response(
            span,
            finish_reason="end_turn",
            input_tokens=None,
            output_tokens=None,
        )

    span = _span_named(exporter, "chat model-x")
    assert span.kind is SpanKind.CLIENT
    assert span.attributes["gen_ai.response.finish_reasons"] == ("end_turn",)
    assert "gen_ai.usage.input_tokens" not in span.attributes
    assert "gen_ai.usage.output_tokens" not in span.attributes


def test_otel_tool_span_records_call_attributes():
    tracer, exporter = _make_test_tracer()

    with tracer.tool_call(name="Read", call_id="tool-1", concurrent=True) as span:
        span.set_attribute("bourbon.tool.is_error", False)

    span = _span_named(exporter, "execute_tool Read")
    assert span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert span.attributes["gen_ai.tool.name"] == "Read"
    assert span.attributes["gen_ai.tool.call.id"] == "tool-1"
    assert span.attributes["bourbon.tool.concurrent"] is True
    assert span.attributes["bourbon.tool.is_error"] is False


def test_mark_tool_result_sets_error_flag_and_status():
    tracer, exporter = _make_test_tracer()

    with tracer.tool_call(name="Read", call_id="tool-1", concurrent=False) as span:
        tracer.mark_tool_result(
            span,
            is_error=True,
            error_type="tool_error",
            message="bad output",
        )

    span = _span_named(exporter, "execute_tool Read")
    assert span.kind is SpanKind.INTERNAL
    assert span.attributes["bourbon.tool.is_error"] is True
    assert span.attributes["error.type"] == "tool_error"
    assert span.status.status_code == StatusCode.ERROR


def test_mark_error_sets_status_without_exception_event():
    tracer, exporter = _make_test_tracer()

    with tracer.tool_call(name="Read", call_id="tool-1", concurrent=False) as span:
        tracer.mark_error(span, "tool_error", "bad output")

    span = _span_named(exporter, "execute_tool Read")
    assert span.attributes["bourbon.tool.is_error"] is True
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "tool_error"
    assert list(span.events) == []


def test_record_error_sets_status_and_exception_event():
    tracer, exporter = _make_test_tracer()

    with tracer.tool_call(name="Read", call_id="tool-1", concurrent=False) as span:
        tracer.record_error(span, ValueError("boom"))

    span = _span_named(exporter, "execute_tool Read")
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ValueError"
    assert [event.name for event in span.events] == ["exception"]


def test_otel_llm_and_tool_spans_are_children_of_agent_root():
    tracer, exporter = _make_test_tracer()

    with tracer.agent_step(workdir="/tmp", entrypoint="step"):
        with tracer.llm_call(model="model-x", max_tokens=10):
            pass
        with tracer.tool_call(name="Read", call_id="tool-1", concurrent=False):
            pass

    root = _span_named(exporter, "invoke_agent bourbon")
    llm = _span_named(exporter, "chat model-x")
    tool = _span_named(exporter, "execute_tool Read")
    assert llm.parent.span_id == root.context.span_id
    assert tool.parent.span_id == root.context.span_id


def test_otel_queue_parallel_and_serial_tools_keep_agent_root_parent():
    from bourbon.tools.execution_queue import ToolExecutionQueue

    tracer, exporter = _make_test_tracer()

    with tracer.agent_step(workdir="/tmp", entrypoint="step"):
        q = ToolExecutionQueue(execute_fn=lambda block: "ok", tracer=tracer)
        q.add(make_queue_block("c1", name="Read"), make_queue_tool(concurrent=True), 0)
        q.add(make_queue_block("c2", name="Grep"), make_queue_tool(concurrent=True), 1)
        q.add(make_queue_block("s1", name="Bash"), make_queue_tool(concurrent=False), 2)
        q.execute_all()

    root = _span_named(exporter, "invoke_agent bourbon")
    tool_spans = [
        span for span in exporter.get_finished_spans() if span.name.startswith("execute_tool ")
    ]
    assert len(tool_spans) == 3
    assert {span.parent.span_id for span in tool_spans} == {root.context.span_id}


def test_manager_shutdown_calls_shutdown_provider_once(monkeypatch):
    """shutdown() must delegate to _shutdown_provider_once() to stop BatchSpanProcessor thread."""
    import bourbon.observability.manager as mgr_module

    shutdown_once_calls = []
    monkeypatch.setattr(
        mgr_module,
        "_shutdown_provider_once",
        lambda timeout=None: shutdown_once_calls.append(timeout),
    )

    manager = object.__new__(ObservabilityManager)
    manager._shutdown_called = False
    manager._provider = object()  # non-None triggers path
    manager._tracer = BourbonTracer(otel_tracer=None)

    manager.shutdown()

    assert shutdown_once_calls == [mgr_module.DEFAULT_SHUTDOWN_TIMEOUT_SECONDS], (
        "shutdown() must call _shutdown_provider_once() to fully stop BatchSpanProcessor"
    )


def test_manager_shutdown_is_idempotent(monkeypatch):
    """shutdown() must not call _shutdown_provider_once() more than once."""
    import bourbon.observability.manager as mgr_module

    calls = []
    monkeypatch.setattr(
        mgr_module,
        "_shutdown_provider_once",
        lambda timeout=None: calls.append(timeout),
    )

    manager = object.__new__(ObservabilityManager)
    manager._shutdown_called = False
    manager._provider = object()
    manager._tracer = BourbonTracer(otel_tracer=None)

    manager.shutdown()
    manager.shutdown()

    assert len(calls) == 1, "shutdown() must be idempotent"


def test_shutdown_provider_once_returns_after_timeout(monkeypatch):
    """Provider shutdown can block on exporter flush; manager shutdown must be bounded."""
    import bourbon.observability.manager as mgr_module

    shutdown_started = Event()
    shutdown_finished = Event()

    class BlockingProvider:
        def shutdown(self):
            shutdown_started.set()
            time.sleep(0.2)
            shutdown_finished.set()

    monkeypatch.setattr(mgr_module, "_PROVIDER", BlockingProvider())
    monkeypatch.setattr(mgr_module, "_PROVIDER_SHUTDOWN", False)

    started_at = time.monotonic()
    completed = mgr_module._shutdown_provider_once(timeout=0.01)
    elapsed = time.monotonic() - started_at

    assert completed is False
    assert elapsed < 0.1
    assert shutdown_started.is_set()
    assert mgr_module._PROVIDER is None
    assert mgr_module._PROVIDER_SHUTDOWN is True

    assert shutdown_finished.wait(timeout=1)


def test_manager_force_flush_delegates_to_provider_timeout_millis():
    calls = []

    class Provider:
        def force_flush(self, timeout_millis):
            calls.append(timeout_millis)
            return True

    manager = object.__new__(ObservabilityManager)
    manager._provider = Provider()
    manager._shutdown_called = False
    manager._tracer = BourbonTracer(otel_tracer=None)

    assert manager.force_flush(timeout=0.5) is True
    assert calls == [500]


def test_manager_force_flush_handles_missing_provider():
    manager = object.__new__(ObservabilityManager)
    manager._provider = None
    manager._shutdown_called = False
    manager._tracer = BourbonTracer(otel_tracer=None)

    assert manager.force_flush(timeout=0.5) is True


def test_agent_shutdown_observability_forwards_timeout():
    agent = object.__new__(Agent)
    agent._obs_manager = SimpleNamespace(shutdown=MagicMock())

    agent.shutdown_observability(timeout=0.5)

    agent._obs_manager.shutdown.assert_called_once_with(timeout=0.5)


def test_inline_subagent_root_span_is_child_of_agent_tool_span():
    tracer, exporter = _make_test_tracer()

    with (
        tracer.agent_step(workdir="/tmp", entrypoint="step"),
        tracer.tool_call(name="Agent", call_id="tool-agent", concurrent=False),
        tracer.agent_step(workdir="/tmp/sub", entrypoint="step"),
    ):
        pass

    root_spans = [
        span for span in exporter.get_finished_spans() if span.name == "invoke_agent bourbon"
    ]
    tool = _span_named(exporter, "execute_tool Agent")
    subagent_root = next(
        span for span in root_spans if span.attributes["bourbon.agent.workdir"] == "/tmp/sub"
    )
    top_root = next(
        span for span in root_spans if span.attributes["bourbon.agent.workdir"] == "/tmp"
    )
    assert tool.parent.span_id == top_root.context.span_id
    assert subagent_root.parent.span_id == tool.context.span_id
