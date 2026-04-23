# Observability API/SDK Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor Bourbon's observability layer so core runtime instrumentation depends only on `opentelemetry-api`, while SDK/exporter bootstrap stays isolated and GenAI span semantics are centralized behind a thin tracer facade.

**Architecture:** Introduce a small semantic-convention helper module under `src/bourbon/observability/` that owns span names, explicit `SpanKind`, and attribute builders. Refactor `BourbonTracer` to use `opentelemetry-api` types and expose higher-level helpers for LLM responses and tool outcomes, then update `Agent` and `ToolExecutionQueue` to consume those helpers instead of hand-writing span attributes.

**Tech Stack:** Python 3.12, OpenTelemetry API/SDK, pytest, Ruff, mypy, existing Bourbon observability tests

---

## Preconditions

Install the local dependencies needed for observability tests before broad verification:

```bash
uv pip install -e ".[dev,observability]"
```

Relevant references:

- `docs/superpowers/specs/2026-04-15-agent-observability-design.md`
- `src/bourbon/observability/tracer.py`
- `src/bourbon/observability/manager.py`
- `src/bourbon/agent.py`
- `src/bourbon/tools/execution_queue.py`

Non-goals for this refactor:

- Do not add auto-instrumentation.
- Do not change the exported OTLP protocol or backend support.
- Do not redesign the trace tree shape beyond the existing root span, LLM span, and tool span hierarchy.

---

### Task 1: Add an API-Level Semantic Convention Layer

**Files:**
- Create: `src/bourbon/observability/semconv.py`
- Modify: `src/bourbon/observability/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/test_observability.py`

**Step 1: Write the failing tests**

Add tests near the existing observability unit tests:

```python
from opentelemetry.trace import SpanKind

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
    assert tool_span_attributes("Read", "tool-1", True) == {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "Read",
        "gen_ai.tool.call.id": "tool-1",
        "bourbon.tool.concurrent": True,
    }
    assert TOOL_IS_ERROR_ATTR == "bourbon.tool.is_error"
    assert TOOL_ERROR_ATTR == "error.type"
    assert TOOL_SPAN_KIND is SpanKind.INTERNAL
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k semconv -v
```

Expected:

- FAIL with `ModuleNotFoundError: No module named 'bourbon.observability.semconv'`

**Step 3: Write the minimal implementation**

Add the new semantic-convention module and promote the API dependency to the base install:

```python
# src/bourbon/observability/semconv.py
from __future__ import annotations

from opentelemetry.trace import SpanKind

AGENT_SPAN_NAME = "invoke_agent bourbon"
AGENT_SPAN_KIND = SpanKind.INTERNAL
LLM_SPAN_KIND = SpanKind.CLIENT
TOOL_SPAN_KIND = SpanKind.INTERNAL

AGENT_WORKDIR_ATTR = "bourbon.agent.workdir"
AGENT_ENTRYPOINT_ATTR = "bourbon.agent.entrypoint"
TOOL_IS_ERROR_ATTR = "bourbon.tool.is_error"
TOOL_ERROR_ATTR = "error.type"


def llm_span_name(model: str) -> str:
    return f"chat {model}"


def tool_span_name(name: str) -> str:
    return f"execute_tool {name}"


def agent_span_attributes(workdir: str, entrypoint: str) -> dict[str, object]:
    return {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.provider.name": "bourbon",
        "gen_ai.agent.name": "bourbon",
        AGENT_WORKDIR_ATTR: workdir,
        AGENT_ENTRYPOINT_ATTR: entrypoint,
    }


def llm_request_attributes(model: str, max_tokens: int, provider: str) -> dict[str, object]:
    return {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "gen_ai.request.max_tokens": max_tokens,
    }


def llm_response_attributes(
    finish_reason: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, object]:
    return {
        "gen_ai.response.finish_reasons": [finish_reason],
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
    }


def tool_span_attributes(name: str, call_id: str, concurrent: bool) -> dict[str, object]:
    return {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": name,
        "gen_ai.tool.call.id": call_id,
        "bourbon.tool.concurrent": concurrent,
    }
```

```python
# src/bourbon/observability/__init__.py
from bourbon.observability.manager import ObservabilityManager
from bourbon.observability.tracer import BourbonTracer

__all__ = ["BourbonTracer", "ObservabilityManager"]
```

```toml
# pyproject.toml
dependencies = [
    ...
    "mcp>=1.0.0,<2.0.0",
    "opentelemetry-api>=1.20",
]
```

**Step 4: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k semconv -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add pyproject.toml src/bourbon/observability/__init__.py src/bourbon/observability/semconv.py tests/test_observability.py
git commit -m "refactor: centralize observability semantic conventions"
```

---

### Task 2: Refactor `BourbonTracer` Into an API-Only Thin Facade

**Files:**
- Modify: `src/bourbon/observability/tracer.py`
- Test: `tests/test_observability.py`

**Step 1: Write the failing tests**

Add tests that force `BourbonTracer` to own span kinds and common response helpers:

```python
from opentelemetry.trace import SpanKind, StatusCode


def test_otel_agent_span_uses_explicit_kind():
    tracer, exporter = _make_test_tracer()

    with tracer.agent_step(workdir="/tmp/project", entrypoint="step"):
        pass

    span = _span_named(exporter, "invoke_agent bourbon")
    assert span.kind is SpanKind.INTERNAL


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
```

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "explicit_kind or record_llm_response or mark_tool_result" -v
```

Expected:

- FAIL because `record_llm_response()` and `mark_tool_result()` do not exist
- FAIL because span kind is still implicit

**Step 3: Write the minimal implementation**

Refactor `BourbonTracer` to use API imports and semantic helpers:

```python
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry.trace import Status, StatusCode, Tracer

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


class BourbonTracer:
    def __init__(self, otel_tracer: Tracer | None = None) -> None:
        self._tracer = otel_tracer

    def _apply_attributes(self, span: Any, attributes: dict[str, object]) -> None:
        for key, value in attributes.items():
            span.set_attribute(key, value)

    @contextmanager
    def _span(
        self,
        name: str,
        *,
        kind,
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
                self.record_error(span, exc)
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
    def llm_call(self, model: str, max_tokens: int, provider: str = "anthropic"):
        with self._span(
            llm_span_name(model),
            kind=LLM_SPAN_KIND,
            attributes=llm_request_attributes(model, max_tokens, provider),
        ) as span:
            yield span

    @contextmanager
    def tool_call(self, name: str, call_id: str, concurrent: bool):
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
        input_tokens: int,
        output_tokens: int,
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
            span.set_attribute(TOOL_ERROR_ATTR, error_type)
            span.set_status(Status(StatusCode.ERROR, message))

    def mark_error(self, span: Any, error_type: str = "tool_error", message: str = "") -> None:
        span.set_attribute(TOOL_ERROR_ATTR, error_type)
        span.set_status(Status(StatusCode.ERROR, message))

    def record_error(self, span: Any, exc: Exception) -> None:
        span.record_exception(exc)
        self.mark_error(span, type(exc).__name__, str(exc))
```

Keep `_NoOpSpan` as a no-op fallback and add `mark_tool_result()` plus `record_llm_response()` methods to `_NoOpSpan` if needed for simple call-site symmetry.

**Step 4: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "explicit_kind or record_llm_response or mark_tool_result" -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/bourbon/observability/tracer.py tests/test_observability.py
git commit -m "refactor: make bourbon tracer api-only"
```

---

### Task 3: Remove Hand-Written LLM Span Attributes From `Agent`

**Files:**
- Modify: `src/bourbon/agent.py`
- Test: `tests/test_observability.py`

**Step 1: Write the failing tests**

Add focused tests around the helper call boundary instead of duplicating exporter assertions:

```python
def test_sync_llm_path_uses_record_llm_response_helper(monkeypatch, tmp_path):
    from bourbon.agent import Agent

    tracer = RecordingTracer()
    tracer.recorded_llm_responses = []

    def record_llm_response(span, *, finish_reason, input_tokens, output_tokens):
        tracer.recorded_llm_responses.append(
            (finish_reason, input_tokens, output_tokens)
        )

    tracer.record_llm_response = record_llm_response
    agent = object.__new__(Agent)
    agent.workdir = tmp_path
    agent._tracer = tracer
    agent._llm_max_tokens = lambda: 10
    agent.config = SimpleNamespace(llm=SimpleNamespace(default_provider="anthropic"))
    agent.llm = SimpleNamespace(
        model="model-x",
        chat=lambda **kwargs: {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 2, "output_tokens": 1},
        },
    )
    agent.session = SimpleNamespace(
        get_messages_for_llm=lambda: [],
        add_message=lambda msg: None,
        save=lambda: None,
    )
    agent._tool_definitions = lambda: []
    agent._build_assistant_transcript_message = lambda content: SimpleNamespace(
        uuid="assistant-1", content=content, usage=None
    )
    agent._subagent_debug_fields = lambda: {}

    assert agent._run_conversation_loop() == "ok"
    assert tracer.recorded_llm_responses == [("end_turn", 2, 1)]
```

Add the streaming equivalent that asserts only one `record_llm_response()` call is made with the aggregated stop reason and token counts.

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "record_llm_response_helper" -v
```

Expected:

- FAIL because `Agent` still writes LLM response attributes directly on the span

**Step 3: Write the minimal implementation**

Update both LLM paths in `Agent`:

```python
with tracer.llm_call(
    model=str(getattr(self.llm, "model", "")),
    max_tokens=self._llm_max_tokens(),
    provider=self.config.llm.default_provider,
) as llm_span:
    response = self.llm.chat(...)
    usage = response.get("usage", {})
    tracer.record_llm_response(
        llm_span,
        finish_reason=response.get("stop_reason", ""),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )
```

In `_run_conversation_loop_stream()`, replace the three direct `set_attribute()` calls with one `record_llm_response()` call after the stream loop finishes.

Do not change token accumulation logic outside the helper migration.

**Step 4: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "record_llm_response_helper or llm_call" -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/bourbon/agent.py tests/test_observability.py
git commit -m "refactor: route agent llm spans through tracer helpers"
```

---

### Task 4: Unify Direct Tool Spans and Queued Tool Outcome Recording

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `src/bourbon/tools/execution_queue.py`
- Test: `tests/test_observability.py`

**Step 1: Write the failing tests**

Add tests that assert tool error bookkeeping now flows through the tracer helper instead of direct attribute writes:

```python
def test_resume_permission_request_uses_mark_tool_result_helper(tmp_path):
    from bourbon.agent import Agent

    tracer = RecordingTracer()
    tracer.tool_results = []

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
    assert tracer.tool_results == [(True, "tool_error", "bad output")]
```

Add a queue-side test that injects a recording tracer and verifies `mark_tool_result()` is called for semantic errors and `record_error()` is called for exception errors.

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "mark_tool_result_helper or tool_execution_queue" -v
```

Expected:

- FAIL because direct tool paths and queue paths still mutate span attributes themselves

**Step 3: Write the minimal implementation**

Refactor the direct and queued tool paths to share helper-based tool result handling:

```python
# src/bourbon/agent.py
@contextmanager
def _direct_tool_span(...):
    tracer = self._get_tracer()
    with tracer.tool_call(name=name, call_id=call_id, concurrent=False) as span:
        tracer.mark_tool_result(
            span,
            is_error=is_error,
            error_type=error_type,
            message=message,
        )
        yield span
```

```python
# src/bourbon/agent.py
if outcome.is_error:
    tracer = self._get_tracer()
    tracer.mark_tool_result(
        span,
        is_error=True,
        error_type=outcome.error_type,
        message=outcome.error_message,
    )
```

```python
# src/bourbon/tools/execution_queue.py
with self._tracer.tool_call(...) as tool_span:
    try:
        raw = self._execute_fn(tool.block)
    except Exception as exc:
        raw_output = f"Error: {exc}"
        is_error = True
        error_type = type(exc).__name__
        error_message = str(exc)
        self._tracer.record_error(tool_span, exc)
        self._tracer.mark_tool_result(
            tool_span,
            is_error=True,
            error_type=error_type,
            message=error_message,
        )
    else:
        ...
        self._tracer.mark_tool_result(
            tool_span,
            is_error=is_error,
            error_type=error_type,
            message=error_message,
        )
```

Once the helper is used consistently, remove the direct `span.set_attribute("bourbon.tool.is_error", ...)` writes from both files.

**Step 4: Run the tests to verify they pass**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "mark_tool_result_helper or tool_execution_queue or permission_request" -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add src/bourbon/agent.py src/bourbon/tools/execution_queue.py tests/test_observability.py
git commit -m "refactor: unify tool span outcome recording"
```

---

### Task 5: Verify Dependency Boundaries and Update Observability Documentation

**Files:**
- Modify: `tests/test_observability.py`
- Modify: `docs/superpowers/specs/2026-04-15-agent-observability-design.md`

**Step 1: Write the failing tests**

Add a dependency-boundary test that documents the new contract:

```python
def test_manager_returns_noop_when_sdk_and_exporter_are_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("opentelemetry.sdk"):
            raise ImportError(name)
        if name.startswith("opentelemetry.exporter.otlp"):
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    manager = ObservabilityManager(
        ObservabilityConfig(enabled=True, otlp_endpoint="http://otel:4318")
    )
    assert manager.get_tracer().enabled is False
```

Also extend the design doc with one short section describing the new dependency boundary:

- `opentelemetry-api` is a base runtime dependency
- `opentelemetry-sdk` and OTLP exporter remain under the `observability` extra
- `BourbonTracer` is the stable instrumentation facade for runtime code

**Step 2: Run the tests to verify they fail**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -k "sdk_and_exporter_are_unavailable" -v
```

Expected:

- FAIL until the test is added and the manager behavior is verified against the new documented boundary

**Step 3: Write the minimal implementation**

Keep the lazy SDK imports in `ObservabilityManager._build()` and only update the doc wording to match the new dependency model. Do not move exporter setup out of `manager.py` in this task unless the previous tasks reveal an actual blocker.

Suggested design-doc addition:

```md
### Dependency Boundary

- `opentelemetry-api` is a base Bourbon dependency because runtime tracing helpers import API types directly.
- `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http` remain optional and are only required when OTLP export is enabled.
- Runtime modules such as `agent.py` and `execution_queue.py` must only interact with `BourbonTracer`, never with SDK classes or exporter setup.
```

**Step 4: Run the tests and verification commands**

Run:

```bash
uv run --extra dev --extra observability pytest tests/test_observability.py -q
uv run ruff check src tests
uv run mypy src/bourbon/observability src/bourbon/agent.py src/bourbon/tools/execution_queue.py
```

Expected:

- All targeted observability tests PASS
- Ruff reports no issues
- mypy reports no new type errors in the touched modules

**Step 5: Commit**

```bash
git add tests/test_observability.py docs/superpowers/specs/2026-04-15-agent-observability-design.md
git commit -m "docs: clarify observability dependency boundary"
```
