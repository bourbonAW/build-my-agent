"""Bourbon OpenTelemetry span helpers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from bourbon.observability.semconv import (
    AGENT_SPAN_KIND,
    AGENT_SPAN_NAME,
    LLM_SPAN_KIND,
    TOOL_ERROR_ATTR,
    TOOL_IS_ERROR_ATTR,
    TOOL_SPAN_KIND,
    agent_span_attributes,
    llm_request_attributes,
    llm_response_attributes,
    llm_span_name,
    tool_span_attributes,
    tool_span_name,
)


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        pass

    def add_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        timestamp: Any | None = None,
    ) -> None:
        pass

    def update_name(self, name: str) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass


class BourbonTracer:
    def __init__(self, otel_tracer: Tracer | None = None) -> None:
        self._tracer = otel_tracer

    @property
    def enabled(self) -> bool:
        return self._tracer is not None

    def _apply_attributes(self, span: Any, attributes: dict[str, object]) -> None:
        for key, value in attributes.items():
            span.set_attribute(key, value)

    def _set_error_status(self, span: Any, error_type: str, message: str) -> None:
        span.set_attribute(TOOL_ERROR_ATTR, error_type)
        span.set_status(Status(StatusCode.ERROR, message))

    def _record_span_error(self, span: Any, exc: Exception) -> None:
        span.record_exception(exc)
        self._set_error_status(span, type(exc).__name__, str(exc))

    @contextmanager
    def _span(
        self,
        name: str,
        *,
        kind: SpanKind,
        attributes: dict[str, object],
    ) -> Generator[Any, None, None]:
        if self._tracer is None:
            yield _NoOpSpan()
            return
        with self._tracer.start_as_current_span(name, kind=kind) as span:
            self._apply_attributes(span, attributes)
            try:
                yield span
            except Exception as exc:
                self._record_span_error(span, exc)
                raise

    @contextmanager
    def agent_step(self, workdir: str, entrypoint: str = "step") -> Generator[Any, None, None]:
        with self._span(
            AGENT_SPAN_NAME,
            kind=AGENT_SPAN_KIND,
            attributes=agent_span_attributes(workdir, entrypoint),
        ) as span:
            yield span

    @contextmanager
    def llm_call(
        self,
        model: str,
        max_tokens: int,
        provider: str = "anthropic",
    ) -> Generator[Any, None, None]:
        with self._span(
            llm_span_name(model),
            kind=LLM_SPAN_KIND,
            attributes=llm_request_attributes(model, max_tokens, provider),
        ) as span:
            yield span

    @contextmanager
    def tool_call(self, name: str, call_id: str, concurrent: bool) -> Generator[Any, None, None]:
        with self._span(
            tool_span_name(name),
            kind=TOOL_SPAN_KIND,
            attributes=tool_span_attributes(name, call_id, concurrent),
        ) as span:
            yield span

    def record_llm_response(
        self,
        span: Any,
        *,
        finish_reason: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        self._apply_attributes(
            span,
            llm_response_attributes(finish_reason, input_tokens, output_tokens),
        )

    def mark_tool_result(
        self,
        span: Any,
        *,
        is_error: bool,
        error_type: str = "tool_error",
        message: str = "",
    ) -> None:
        span.set_attribute(TOOL_IS_ERROR_ATTR, is_error)
        if is_error:
            self._set_error_status(span, error_type, message)

    def mark_error(self, span: Any, error_type: str = "tool_error", message: str = "") -> None:
        self.mark_tool_result(
            span,
            is_error=True,
            error_type=error_type,
            message=message,
        )

    def record_error(self, span: Any, exc: Exception) -> None:
        span.record_exception(exc)
        self.mark_error(span, type(exc).__name__, str(exc))
