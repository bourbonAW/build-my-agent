"""ObservabilityManager: builds per-Agent BourbonTracer instances."""

from __future__ import annotations

import atexit
import os
import threading
from typing import Any

from bourbon.config import ObservabilityConfig
from bourbon.observability.tracer import BourbonTracer

_PROVIDER_LOCK = threading.Lock()
_PROVIDER: Any | None = None
_ATEXIT_REGISTERED = False
_PROVIDER_SHUTDOWN = False


def _append_trace_path(endpoint: str) -> str:
    stripped = endpoint.rstrip("/")
    if stripped.endswith("/v1/traces"):
        return stripped
    return f"{stripped}/v1/traces"


def _resolve_trace_endpoint(config: ObservabilityConfig) -> str:
    trace_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if trace_endpoint:
        return trace_endpoint
    generic_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if generic_endpoint:
        return _append_trace_path(generic_endpoint)
    return _append_trace_path(config.otlp_endpoint) if config.otlp_endpoint else ""


def _resolve_headers(config: ObservabilityConfig) -> dict[str, str]:
    headers = dict(config.otlp_headers)
    headers_env = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or os.environ.get(
        "OTEL_EXPORTER_OTLP_HEADERS", ""
    )
    for pair in headers_env.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def _shutdown_provider_once() -> None:
    global _PROVIDER, _PROVIDER_SHUTDOWN
    with _PROVIDER_LOCK:
        if _PROVIDER is None or _PROVIDER_SHUTDOWN:
            return
        _PROVIDER.shutdown()
        _PROVIDER_SHUTDOWN = True
        _PROVIDER = None


class ObservabilityManager:
    def __init__(self, config: ObservabilityConfig) -> None:
        self._provider: Any | None = None
        self._shutdown_called = False
        self._tracer = self._build(config)

    def get_tracer(self) -> BourbonTracer:
        return self._tracer

    def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        if self._provider is not None:
            self._provider.force_flush()

    def _build(self, config: ObservabilityConfig) -> BourbonTracer:
        if not config.enabled:
            return BourbonTracer(otel_tracer=None)

        endpoint = _resolve_trace_endpoint(config)
        if not endpoint:
            return BourbonTracer(otel_tracer=None)

        try:
            from opentelemetry import trace  # type: ignore[import-untyped]
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-untyped]
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import (  # type: ignore[import-untyped]
                SERVICE_NAME,
                Resource,
            )
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,  # type: ignore[import-untyped]
            )
        except ImportError:
            return BourbonTracer(otel_tracer=None)

        global _PROVIDER, _ATEXIT_REGISTERED, _PROVIDER_SHUTDOWN
        service_name = os.environ.get("OTEL_SERVICE_NAME", config.service_name)
        with _PROVIDER_LOCK:
            if _PROVIDER is None:
                resource = Resource.create({SERVICE_NAME: service_name})
                provider = TracerProvider(resource=resource)
                exporter = OTLPSpanExporter(endpoint=endpoint, headers=_resolve_headers(config))
                provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=2048))
                trace.set_tracer_provider(provider)
                _PROVIDER = provider
                _PROVIDER_SHUTDOWN = False
                if not _ATEXIT_REGISTERED:
                    atexit.register(_shutdown_provider_once)
                    _ATEXIT_REGISTERED = True
            self._provider = _PROVIDER

        return BourbonTracer(otel_tracer=trace.get_tracer("bourbon"))
