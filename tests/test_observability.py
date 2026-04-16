"""Tests for OpenTelemetry observability integration."""

from types import SimpleNamespace

import pytest

from bourbon.config import Config, ObservabilityConfig
from bourbon.observability.manager import ObservabilityManager, _resolve_trace_endpoint
from bourbon.observability.tracer import BourbonTracer


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
