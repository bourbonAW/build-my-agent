"""Tests for OpenTelemetry observability integration."""

from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from bourbon.access_control.capabilities import CapabilityType
from bourbon.access_control.policy import CapabilityDecision, PolicyAction, PolicyDecision
from bourbon.agent import Agent
from bourbon.config import Config, ObservabilityConfig
from bourbon.observability.manager import ObservabilityManager, _resolve_trace_endpoint
from bourbon.observability.tracer import BourbonTracer
from bourbon.permissions import PermissionChoice


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


def test_noop_tracer_contexts_do_not_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.agent_step(workdir="/tmp", entrypoint="step") as span:
        span.set_attribute("x", "y")
    with tracer.llm_call(model="m", max_tokens=100, provider="anthropic") as span:
        span.set_attribute("x", "y")
    with tracer.tool_call(name="Read", call_id="id1", concurrent=True) as span:
        span.set_attribute("x", "y")


def test_noop_tracer_exceptions_propagate():
    tracer = BourbonTracer(otel_tracer=None)
    with pytest.raises(ValueError):
        with tracer.agent_step(workdir="/tmp", entrypoint="step"):
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

    @contextmanager
    def agent_step(self, workdir: str, entrypoint: str = "step"):
        self.entrypoints.append(entrypoint)
        yield object()

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


def test_step_stream_records_step_stream_entrypoint(tmp_path):
    agent = make_entrypoint_agent(tmp_path)

    assert agent.step_stream("hello", lambda chunk: None) == "stream-ok"

    assert agent._tracer.entrypoints == ["step_stream"]


def test_resume_permission_request_records_resume_entrypoint(tmp_path):
    from bourbon.agent import Agent

    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = RecordingTracer()
    agent.suspended_tool_round = None

    assert agent.resume_permission_request(PermissionChoice.REJECT).startswith("Error:")

    assert agent._tracer.entrypoints == ["resume_permission"]


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


def test_non_streaming_llm_call_records_span_attributes(tmp_path):
    llm = SimpleNamespace(
        model="model-x",
        chat=lambda **kwargs: {
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 11, "output_tokens": 7},
        },
    )
    agent = make_llm_loop_agent(tmp_path, llm)

    assert agent._run_conversation_loop() == "done"

    call = agent._tracer.llm_calls[0]
    assert call["model"] == "model-x"
    assert call["max_tokens"] == 64000
    assert call["provider"] == "anthropic"
    assert call["span"].attributes["gen_ai.response.finish_reasons"] == ["end_turn"]
    assert call["span"].attributes["gen_ai.usage.input_tokens"] == 11
    assert call["span"].attributes["gen_ai.usage.output_tokens"] == 7


def test_streaming_llm_call_records_span_attributes(tmp_path):
    def chat_stream(**kwargs):
        yield {"type": "text", "text": "hi"}
        yield {"type": "usage", "input_tokens": 5, "output_tokens": 3}
        yield {"type": "stop", "stop_reason": "end_turn"}

    llm = SimpleNamespace(model="stream-model", chat_stream=chat_stream)
    agent = make_llm_loop_agent(tmp_path, llm)
    chunks = []

    assert agent._run_conversation_loop_stream(chunks.append) == "hi"

    call = agent._tracer.llm_calls[0]
    assert call["model"] == "stream-model"
    assert call["max_tokens"] == 64000
    assert call["provider"] == "anthropic"
    assert call["span"].attributes["gen_ai.response.finish_reasons"] == ["end_turn"]
    assert call["span"].attributes["gen_ai.usage.input_tokens"] == 5
    assert call["span"].attributes["gen_ai.usage.output_tokens"] == 3


CURRENT_ROOT = ContextVar("CURRENT_ROOT", default=None)


class ToolRecordingTracer:
    def __init__(self):
        self.tool_calls = []

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

    def record_error(self, span, exc: Exception):
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
