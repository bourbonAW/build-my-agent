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

    @contextmanager
    def agent_step(self, workdir: str, entrypoint: str = "step"):
        self.entrypoints.append(entrypoint)
        yield object()


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
