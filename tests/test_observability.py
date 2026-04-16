"""Tests for OpenTelemetry observability integration."""

from bourbon.config import Config, ObservabilityConfig


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
