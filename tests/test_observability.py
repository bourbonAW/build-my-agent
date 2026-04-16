"""Tests for OpenTelemetry observability integration."""

import pytest

from bourbon.config import Config, ObservabilityConfig
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
