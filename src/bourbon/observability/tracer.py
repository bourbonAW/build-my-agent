"""Bourbon OpenTelemetry span helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator


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
    def __init__(self, otel_tracer: Any | None = None) -> None:
        self._tracer = otel_tracer
        self._status_code = self._load_status_code()

    @property
    def enabled(self) -> bool:
        return self._tracer is not None

    @staticmethod
    def _load_status_code() -> Any:
        try:
            from opentelemetry.trace import StatusCode  # type: ignore[import-untyped]

            return StatusCode
        except ImportError:
            return None

    @contextmanager
    def agent_step(self, workdir: str, entrypoint: str = "step") -> Generator[Any, None, None]:
        if self._tracer is None:
            yield _NoOpSpan()
            return
        with self._tracer.start_as_current_span("invoke_agent bourbon") as span:
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.provider.name", "bourbon")
            span.set_attribute("gen_ai.agent.name", "bourbon")
            span.set_attribute("bourbon.agent.workdir", workdir)
            span.set_attribute("bourbon.agent.entrypoint", entrypoint)
            try:
                yield span
            except Exception as exc:
                self.record_error(span, exc)
                raise

    @contextmanager
    def llm_call(
        self,
        model: str,
        max_tokens: int,
        provider: str = "anthropic",
    ) -> Generator[Any, None, None]:
        if self._tracer is None:
            yield _NoOpSpan()
            return
        with self._tracer.start_as_current_span(f"chat {model}") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.provider.name", provider)
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.request.max_tokens", max_tokens)
            try:
                yield span
            except Exception as exc:
                self.record_error(span, exc)
                raise

    @contextmanager
    def tool_call(self, name: str, call_id: str, concurrent: bool) -> Generator[Any, None, None]:
        if self._tracer is None:
            yield _NoOpSpan()
            return
        with self._tracer.start_as_current_span(f"execute_tool {name}") as span:
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", name)
            span.set_attribute("gen_ai.tool.call.id", call_id)
            span.set_attribute("bourbon.tool.concurrent", concurrent)
            try:
                yield span
            except Exception as exc:
                self.record_error(span, exc)
                raise

    def mark_error(self, span: Any, error_type: str = "tool_error", message: str = "") -> None:
        span.set_attribute("error.type", error_type)
        if self._status_code:
            span.set_status(self._status_code.ERROR, message)

    def record_error(self, span: Any, exc: Exception) -> None:
        span.record_exception(exc)
        self.mark_error(span, type(exc).__name__, str(exc))
