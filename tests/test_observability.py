"""Tests for OpenTelemetry observability integration."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

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
