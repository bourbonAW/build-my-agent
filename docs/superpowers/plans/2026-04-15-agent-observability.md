# Agent Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Instrument bourbon with OpenTelemetry tracing so every agent run produces a span tree (agent step → LLM calls and tool calls) viewable in Langfuse or any OTel-compatible backend.

**Architecture:** New `src/bourbon/observability/` module provides a `BourbonTracer` context-manager API. Core files get three instrumentation points: `agent.step()` emits the root span, each `llm.chat()` call emits an LLM span, and each `_run_tool()` emits a tool span. Tool spans are siblings of LLM spans under the root agent span because tools execute after the LLM call returns. `ToolExecutionQueue` explicitly copies the current `contextvars` context into worker threads so concurrent tool spans remain children of the active root span. The module is a no-op when disabled or when the OTel SDK is not installed.

**Tech Stack:** `opentelemetry-sdk>=1.20`, `opentelemetry-exporter-otlp-proto-http>=1.20` (optional extra), `opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter` for tests.

**Spec:** `docs/superpowers/specs/2026-04-15-agent-observability-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/bourbon/observability/__init__.py` | `get_tracer()` / `init_tracer()` module-level singleton |
| Create | `src/bourbon/observability/tracer.py` | `BourbonTracer` + `_NoOpSpan` — span context managers |
| Create | `src/bourbon/observability/manager.py` | `ObservabilityManager` — reads config + env vars, inits OTel SDK |
| Modify | `src/bourbon/config.py` | Add `ObservabilityConfig` dataclass, wire into `Config` |
| Modify | `src/bourbon/agent.py` | 3 instrumentation points (root, LLM ×2 paths, import) |
| Modify | `src/bourbon/tools/execution_queue.py` | Context propagation in `_process_queue()` and tool span in `_run_tool()` |
| Modify | `src/bourbon/repl.py` | Flush observability manager during interactive shutdown |
| Modify | `pyproject.toml` | Add `[observability]` optional-dependencies |
| Create | `tests/test_observability.py` | Unit + attribute tests |

---

## Task 1: Add `ObservabilityConfig` to `config.py`

**Files:**
- Modify: `src/bourbon/config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_observability.py  (create new file)
from bourbon.config import Config, ObservabilityConfig


def test_observability_config_defaults():
    cfg = ObservabilityConfig()
    assert cfg.enabled is False
    assert cfg.service_name == "bourbon"
    assert cfg.otlp_endpoint == ""
    assert cfg.otlp_headers == {}


def test_config_has_observability_field():
    cfg = Config()
    assert isinstance(cfg.observability, ObservabilityConfig)
    assert cfg.observability.enabled is False


def test_config_from_dict_observability():
    data = {
        "observability": {
            "enabled": True,
            "service_name": "my-agent",
            "otlp_endpoint": "http://localhost:4318",
            "otlp_headers": {"Authorization": "Basic abc123"},
        }
    }
    cfg = Config.from_dict(data)
    assert cfg.observability.enabled is True
    assert cfg.observability.service_name == "my-agent"
    assert cfg.observability.otlp_endpoint == "http://localhost:4318"
    assert cfg.observability.otlp_headers == {"Authorization": "Basic abc123"}


def test_config_from_dict_observability_missing_section():
    cfg = Config.from_dict({})
    assert cfg.observability.enabled is False
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
uv run pytest tests/test_observability.py -v
```
Expected: `ImportError: cannot import name 'ObservabilityConfig' from 'bourbon.config'`

- [ ] **Step 3: Add `ObservabilityConfig` dataclass to `config.py`**

After the existing `MCPConfig` dataclass (around line 110), add:

```python
@dataclass
class ObservabilityConfig:
    """OpenTelemetry observability configuration."""

    enabled: bool = False
    service_name: str = "bourbon"
    otlp_endpoint: str = ""
    otlp_headers: dict = field(default_factory=dict)
```

- [ ] **Step 4: Add `observability` field to `Config` dataclass**

In the `Config` dataclass body, after the `mcp` field:

```python
observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
```

- [ ] **Step 5: Wire into `Config.from_dict()`**

In the `from_dict` method, after `mcp_data = data.get("mcp", {})`, add:
```python
observability_data = data.get("observability", {})
```

In the `return cls(...)` call, after `mcp=MCPConfig.from_dict(mcp_data),`, add:
```python
observability=ObservabilityConfig(**observability_data),
```

- [ ] **Step 6: Wire into `Config.to_dict()`**

In the `to_dict` method return dict, add:
```python
"observability": {
    "enabled": self.observability.enabled,
    "service_name": self.observability.service_name,
    "otlp_endpoint": self.observability.otlp_endpoint,
    "otlp_headers": self.observability.otlp_headers,
},
```

- [ ] **Step 7: Run tests to confirm PASS**

```bash
uv run pytest tests/test_observability.py -v
```
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add src/bourbon/config.py tests/test_observability.py
git commit -m "feat: add ObservabilityConfig to Config"
```

---

## Task 2: Create `observability/tracer.py` — `BourbonTracer` + no-op baseline

**Files:**
- Create: `src/bourbon/observability/tracer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_observability.py`:

```python
from bourbon.observability.tracer import BourbonTracer


def test_noop_tracer_agent_step_no_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.agent_step(workdir="/tmp") as span:
        span.set_attribute("gen_ai.provider.name", "bourbon")


def test_noop_tracer_llm_call_no_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.llm_call(model="claude-sonnet-4-6", max_tokens=64000) as span:
        span.set_attribute("gen_ai.usage.input_tokens", 100)
        span.set_attribute("gen_ai.usage.output_tokens", 50)


def test_noop_tracer_tool_call_no_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.tool_call(name="Bash", call_id="toolu_01", concurrent=False) as span:
        span.set_attribute("bourbon.tool.concurrent", False)


def test_noop_tracer_record_error_no_error():
    tracer = BourbonTracer(otel_tracer=None)
    with tracer.tool_call(name="Bash", call_id="toolu_01", concurrent=False) as span:
        tracer.record_error(span, ValueError("boom"))


def test_noop_tracer_agent_step_exception_propagates():
    tracer = BourbonTracer(otel_tracer=None)
    with pytest.raises(ValueError, match="boom"):
        with tracer.agent_step(workdir="/tmp"):
            raise ValueError("boom")
```

Add `import pytest` at the top of the test file.

- [ ] **Step 2: Run to confirm FAIL**

```bash
uv run pytest tests/test_observability.py::test_noop_tracer_agent_step_no_error -v
```
Expected: `ModuleNotFoundError: No module named 'bourbon.observability'`

- [ ] **Step 3: Create the observability package directory**

```bash
mkdir -p src/bourbon/observability
```

- [ ] **Step 4: Create `src/bourbon/observability/tracer.py`**

```python
"""BourbonTracer: semantic context-manager API over OpenTelemetry spans."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator


class _NoOpSpan:
    """Stand-in span used when OTel SDK is absent or observability is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def set_attributes(self, attributes: dict[str, Any]) -> None:  # noqa: ARG002
        pass

    def add_event(
        self,
        name: str,  # noqa: ARG002
        attributes: dict[str, Any] | None = None,  # noqa: ARG002
        timestamp: Any | None = None,  # noqa: ARG002
    ) -> None:
        pass

    def update_name(self, name: str) -> None:  # noqa: ARG002
        pass

    def record_exception(self, exc: Exception) -> None:  # noqa: ARG002
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


class BourbonTracer:
    """Wraps OTel span creation with bourbon-specific semantic attributes.

    Pass ``otel_tracer=None`` for a no-op instance that performs no work and
    requires no OTel SDK installation.
    """

    def __init__(self, otel_tracer: Any | None = None) -> None:
        self._tracer = otel_tracer
        self._status_code = self._load_status_code()

    @property
    def enabled(self) -> bool:
        """Return whether this tracer is backed by a real OTel tracer."""
        return self._tracer is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_status_code() -> Any:
        """Import OTel StatusCode lazily; return None if SDK not installed."""
        try:
            from opentelemetry.trace import StatusCode  # type: ignore[import-untyped]
            return StatusCode
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # Public span context managers
    # ------------------------------------------------------------------

    @contextmanager
    def agent_step(self, workdir: str) -> Generator[Any, None, None]:
        """Root span covering one full agent.step() / step_stream() call."""
        if self._tracer is None:
            yield _NoOpSpan()
            return
        with self._tracer.start_as_current_span("invoke_agent bourbon") as span:
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.provider.name", "bourbon")
            span.set_attribute("gen_ai.agent.name", "bourbon")
            span.set_attribute("bourbon.agent.workdir", workdir)
            try:
                yield span
            except Exception as exc:
                self.record_error(span, exc)
                raise

    @contextmanager
    def llm_call(self, model: str, max_tokens: int, provider: str = "anthropic") -> Generator[Any, None, None]:
        """Child span covering one LLM chat() or chat_stream() call."""
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
        """Child span covering one tool execution in the queue."""
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

    def record_error(self, span: Any, exc: Exception) -> None:
        """Record an exception on an active span, including swallowed tool errors."""
        span.record_exception(exc)
        span.set_attribute("error.type", type(exc).__name__)
        if self._status_code:
            span.set_status(self._status_code.ERROR, str(exc))
```

- [ ] **Step 5: Run tests to confirm PASS**

```bash
uv run pytest tests/test_observability.py -k "noop" -v
```
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/observability/tracer.py tests/test_observability.py
git commit -m "feat: add BourbonTracer with no-op baseline"
```

---

## Task 3: Create `observability/manager.py` — `ObservabilityManager`

**Files:**
- Create: `src/bourbon/observability/manager.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_observability.py`:

```python
from bourbon.observability.manager import ObservabilityManager


def test_manager_disabled_returns_noop_tracer():
    cfg = ObservabilityConfig(enabled=False)
    manager = ObservabilityManager(cfg)
    tracer = manager.get_tracer()
    # Must work without error even without OTel SDK
    with tracer.agent_step(workdir="/tmp") as span:
        span.set_attribute("test", "ok")


def test_manager_no_endpoint_returns_noop_tracer(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    cfg = ObservabilityConfig(enabled=True, otlp_endpoint="")
    manager = ObservabilityManager(cfg)
    tracer = manager.get_tracer()
    with tracer.llm_call(model="m", max_tokens=100) as span:
        span.set_attribute("test", "ok")


def test_manager_env_var_endpoint_enables_when_config_disabled(monkeypatch):
    """OTEL_EXPORTER_OTLP_ENDPOINT env var does NOT override enabled=False."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    cfg = ObservabilityConfig(enabled=False)
    manager = ObservabilityManager(cfg)
    tracer = manager.get_tracer()
    # Still no-op because enabled=False is a hard kill switch.
    assert tracer._tracer is None


def test_resolve_trace_endpoint_prefers_trace_specific_env(monkeypatch):
    from bourbon.observability.manager import _resolve_trace_endpoint

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://generic:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://trace:4318/v1/traces")
    cfg = ObservabilityConfig(enabled=True, otlp_endpoint="http://config:4318/v1/traces")

    assert _resolve_trace_endpoint(cfg) == "http://trace:4318/v1/traces"


def test_resolve_trace_endpoint_appends_trace_path_for_generic_env(monkeypatch):
    from bourbon.observability.manager import _resolve_trace_endpoint

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    cfg = ObservabilityConfig(enabled=True, otlp_endpoint="")

    assert _resolve_trace_endpoint(cfg) == "http://localhost:4318/v1/traces"
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
uv run pytest tests/test_observability.py -k "manager" -v
```
Expected: `ModuleNotFoundError: No module named 'bourbon.observability.manager'`

- [ ] **Step 3: Create `src/bourbon/observability/manager.py`**

```python
"""ObservabilityManager: initialises the OTel SDK from config + env vars."""

from __future__ import annotations

import atexit
import os
import threading
from typing import Any

from bourbon.config import ObservabilityConfig
from bourbon.observability.tracer import BourbonTracer

_PROVIDER_LOCK = threading.Lock()
_PROVIDER: Any | None = None


def _append_trace_path(endpoint: str) -> str:
    """Return an OTLP traces endpoint from a generic OTLP HTTP endpoint."""
    stripped = endpoint.rstrip("/")
    if stripped.endswith("/v1/traces"):
        return stripped
    return f"{stripped}/v1/traces"


def _resolve_trace_endpoint(config: ObservabilityConfig) -> str:
    """Resolve the final OTLP HTTP traces endpoint."""
    trace_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if trace_endpoint:
        return trace_endpoint

    generic_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if generic_endpoint:
        return _append_trace_path(generic_endpoint)

    return config.otlp_endpoint


def _resolve_headers(config: ObservabilityConfig) -> dict[str, str]:
    """Merge config headers with OTel env-var headers."""
    headers: dict[str, str] = dict(config.otlp_headers)
    headers_env = (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
        or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    )
    if headers_env:
        for pair in headers_env.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = v.strip()
    return headers


class ObservabilityManager:
    """Reads ObservabilityConfig (with env-var overrides) and builds a BourbonTracer."""

    def __init__(self, config: ObservabilityConfig) -> None:
        self._provider: Any | None = None
        self._tracer = self._build(config)

    def get_tracer(self) -> BourbonTracer:
        return self._tracer

    def shutdown(self) -> None:
        """Flush any pending spans. Called automatically at process exit via atexit."""
        if self._provider is not None:
            self._provider.shutdown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build(self, config: ObservabilityConfig) -> BourbonTracer:
        if not config.enabled:
            return BourbonTracer(otel_tracer=None)

        endpoint = _resolve_trace_endpoint(config)
        service_name = os.environ.get("OTEL_SERVICE_NAME", config.service_name)

        if not endpoint:
            return BourbonTracer(otel_tracer=None)

        try:
            from opentelemetry import trace  # type: ignore[import-untyped]
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-untyped]
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore[import-untyped]
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]
            from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-untyped]
        except ImportError:
            return BourbonTracer(otel_tracer=None)

        global _PROVIDER
        with _PROVIDER_LOCK:
            if _PROVIDER is None:
                resource = Resource.create({SERVICE_NAME: service_name})
                provider = TracerProvider(resource=resource)
                exporter = OTLPSpanExporter(endpoint=endpoint, headers=_resolve_headers(config))
                provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=2048))
                trace.set_tracer_provider(provider)
                _PROVIDER = provider
                atexit.register(provider.shutdown)

            self._provider = _PROVIDER

        otel_tracer = trace.get_tracer("bourbon")
        return BourbonTracer(otel_tracer=otel_tracer)
```

- [ ] **Step 4: Run tests to confirm PASS**

```bash
uv run pytest tests/test_observability.py -k "manager" -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/observability/manager.py tests/test_observability.py
git commit -m "feat: add ObservabilityManager"
```

---

## Task 4: Create `observability/__init__.py` — `get_tracer` singleton

**Files:**
- Create: `src/bourbon/observability/__init__.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_observability.py`:

```python
from bourbon.observability import get_tracer, init_tracer


def test_get_tracer_returns_noop_before_init():
    tracer = get_tracer()
    # Must work without error
    with tracer.agent_step(workdir="/tmp") as span:
        span.set_attribute("test", "ok")


def test_init_tracer_replaces_singleton():
    original = get_tracer()
    custom = BourbonTracer(otel_tracer=None)
    init_tracer(custom, force=True)
    assert get_tracer() is custom
    # Restore for other tests
    init_tracer(original, force=True)
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
uv run pytest tests/test_observability.py -k "singleton" -v
```
Expected: `ImportError: cannot import name 'get_tracer' from 'bourbon.observability'`

- [ ] **Step 3: Create `src/bourbon/observability/__init__.py`**

```python
"""Bourbon observability module — OpenTelemetry tracing integration."""

from __future__ import annotations

from bourbon.observability.tracer import BourbonTracer

# Module-level no-op singleton; replaced by init_tracer() at agent startup.
_tracer: BourbonTracer = BourbonTracer(otel_tracer=None)


def get_tracer() -> BourbonTracer:
    """Return the active BourbonTracer (no-op until init_tracer() is called)."""
    return _tracer


def init_tracer(tracer: BourbonTracer, force: bool = False) -> None:
    """Replace the module-level tracer singleton. Called from Agent.__init__.

    By default this is idempotent: if a real tracer has already been set,
    it will NOT be overwritten to avoid conflicts between parent and child agents.
    Pass ``force=True`` to override.
    """
    global _tracer
    if not force and _tracer.enabled:
        return
    _tracer = tracer
```

- [ ] **Step 4: Run all observability tests**

```bash
uv run pytest tests/test_observability.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/observability/__init__.py tests/test_observability.py
git commit -m "feat: add get_tracer/init_tracer singleton"
```

---

## Task 5: Wire `ObservabilityManager` into `Agent.__init__`

**Files:**
- Modify: `src/bourbon/agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_observability.py`:

```python
def test_agent_init_calls_init_tracer(monkeypatch, tmp_path):
    """Agent.__init__ must call init_tracer() with a BourbonTracer."""
    from bourbon.observability import get_tracer
    from bourbon.observability.tracer import BourbonTracer

    called_with = []

    def fake_init_tracer(tracer, force=False):
        called_with.append((tracer, force))

    import bourbon.observability as observability
    monkeypatch.setattr(observability, "init_tracer", fake_init_tracer)

    from bourbon import agent as agent_module
    monkeypatch.setattr(agent_module, "init_tracer", fake_init_tracer, raising=False)
    Agent = agent_module.Agent
    from bourbon.config import Config

    cfg = Config()
    _agent = Agent(config=cfg, workdir=tmp_path)

    assert len(called_with) == 1
    assert isinstance(called_with[0][0], BourbonTracer)
    assert called_with[0][1] is False
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
uv run pytest tests/test_observability.py::test_agent_init_calls_init_tracer -v
```
Expected: FAIL — `AssertionError: assert 0 == 1` (init_tracer never called)

- [ ] **Step 3: Add imports to `agent.py`**

After the existing imports at the top of `src/bourbon/agent.py`, add:

```python
from bourbon.observability import get_tracer, init_tracer
from bourbon.observability.manager import ObservabilityManager
```

- [ ] **Step 4: Call `init_tracer` in `Agent.__init__`**

In `Agent.__init__`, after `self.audit = AuditLogger(...)` (near line 180), add:

```python
# Initialize observability tracer (no-op if disabled or OTel SDK not installed)
# Use force=False so parent agent tracer is not overwritten by child agents.
self._obs_manager = ObservabilityManager(config.observability)
init_tracer(self._obs_manager.get_tracer(), force=False)
```

- [ ] **Step 5: Add explicit shutdown hook in REPL exit path**

In `src/bourbon/repl.py`, find `REPL.run()` and its `finally:` block (currently calls `self._shutdown_mcp()`). Add this before `_shutdown_mcp()`:

```python
# Flush any pending observability spans before exit
if hasattr(self.agent, "_obs_manager"):
    self.agent._obs_manager.shutdown()
```

- [ ] **Step 6: Run test to confirm PASS**

```bash
uv run pytest tests/test_observability.py::test_agent_init_calls_init_tracer -v
```
Expected: PASS

- [ ] **Step 7: Run full test suite to check no regressions**

```bash
uv run pytest tests/ -q
```
Expected: all existing tests pass

- [ ] **Step 8: Commit**

```bash
git add src/bourbon/agent.py src/bourbon/repl.py
git commit -m "feat: wire ObservabilityManager into Agent.__init__ and add shutdown hook"
```

---

## Task 6: Instrument root span in `step()` and `step_stream()`

**Files:**
- Modify: `src/bourbon/agent.py`

- [ ] **Step 1: Instrument `step()` — wrap `_run_conversation_loop()`**

In `src/bourbon/agent.py`, find `step()` (line ~259). Replace:

```python
        # Run the conversation loop
        return self._run_conversation_loop()
```

with:

```python
        # Run the conversation loop (root observability span)
        with get_tracer().agent_step(workdir=str(self.workdir)):
            return self._run_conversation_loop()
```

- [ ] **Step 2: Instrument `step_stream()` — wrap `_run_conversation_loop_stream()`**

In `step_stream()` (line ~286), find:

```python
        # Run the streaming conversation loop
        response = self._run_conversation_loop_stream(on_text_chunk)
```

Replace with:

```python
        # Run the streaming conversation loop (root observability span)
        with get_tracer().agent_step(workdir=str(self.workdir)):
            response = self._run_conversation_loop_stream(on_text_chunk)
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/agent.py
git commit -m "feat: add root observability span to step() and step_stream()"
```

---

## Task 7: Instrument LLM span in `_run_conversation_loop()` (non-streaming)

**Files:**
- Modify: `src/bourbon/agent.py`

- [ ] **Step 1: Find the LLM call in `_run_conversation_loop()`**

The call is at approximately line 557:
```python
                response = self.llm.chat(
                    messages=messages,
                    tools=tool_defs,
                    system=self.system_prompt,
                    max_tokens=64000,
                )
```

- [ ] **Step 2: Wrap with LLM span and set token attributes**

Replace the block from `response = self.llm.chat(...)` through the token-tracking block:

```python
                with get_tracer().llm_call(
                    model=str(getattr(self.llm, "model", "")),
                    max_tokens=64000,
                    provider=self.config.llm.default_provider,
                ) as _llm_span:
                    response = self.llm.chat(
                        messages=messages,
                        tools=tool_defs,
                        system=self.system_prompt,
                        max_tokens=64000,
                    )
                    # Set span attributes from response
                    _llm_span.set_attribute(
                        "gen_ai.response.finish_reasons", [response.get("stop_reason", "")]
                    )
                    if "usage" in response:
                        _usage = response["usage"]
                        _llm_span.set_attribute(
                            "gen_ai.usage.input_tokens", _usage.get("input_tokens", 0)
                        )
                        _llm_span.set_attribute(
                            "gen_ai.usage.output_tokens", _usage.get("output_tokens", 0)
                        )
```

Keep the existing `debug_log` calls and token cumulative tracking (`self.token_usage`) immediately after the `with` block — they are unchanged.

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/agent.py
git commit -m "feat: add LLM span to _run_conversation_loop (non-streaming)"
```

---

## Task 8: Instrument LLM span in `_run_conversation_loop_stream()` (streaming)

**Files:**
- Modify: `src/bourbon/agent.py`

- [ ] **Step 1: Add per-call token tracking variables and span**

In `_run_conversation_loop_stream()`, find the block starting at approximately line 355
(inside `while tool_round < ...: try:`, so at 16-space indent level).

Add the three `_span_*` variables immediately before the `with` block.
Wrap `event_stream = ...` and the entire `for event in event_stream:` loop inside
`with get_tracer().llm_call(...) as _llm_span:`.
The wrapped code shifts one indent level deeper (4 more spaces, bourbon 4-space convention).

Before:
```python
                event_stream = self.llm.chat_stream(
                    messages=messages,
                    tools=self._tool_definitions(),
                    system=self.system_prompt,
                    max_tokens=64000,
                )
                current_text = ""
                has_tool_calls = False
                tool_use_blocks: list[dict] = []
                saw_text = False
                for event in event_stream:
```

After:
```python
                _span_input_tokens = 0
                _span_output_tokens = 0
                _span_stop_reason = "end_turn"
                with get_tracer().llm_call(
                    model=str(getattr(self.llm, "model", "")),
                    max_tokens=64000,
                    provider=self.config.llm.default_provider,
                ) as _llm_span:
                    event_stream = self.llm.chat_stream(
                        messages=messages,
                        tools=self._tool_definitions(),
                        system=self.system_prompt,
                        max_tokens=64000,
                    )
                    current_text = ""
                    has_tool_calls = False
                    tool_use_blocks: list[dict] = []
                    saw_text = False
                    for event in event_stream:
```

- [ ] **Step 2: Capture token counts inside the `usage` event handler**

Inside the `for event in event_stream:` loop, find the `elif event["type"] == "usage":` branch:

```python
                    elif event["type"] == "usage":
                        usage = event
                        self.token_usage["input_tokens"] += usage.get("input_tokens", 0)
                        self.token_usage["output_tokens"] += usage.get("output_tokens", 0)
```

Add capture of per-span values:

```python
                    elif event["type"] == "usage":
                        usage = event
                        _span_input_tokens = usage.get("input_tokens", 0)
                        _span_output_tokens = usage.get("output_tokens", 0)
                        self.token_usage["input_tokens"] += _span_input_tokens
                        self.token_usage["output_tokens"] += _span_output_tokens
```

- [ ] **Step 3: Capture stop_reason inside the `stop` event handler**

Find the `elif event["type"] == "stop":` branch:

```python
                    elif event["type"] == "stop":
                        stop_reason = event.get("stop_reason", "end_turn")
```

Add:

```python
                    elif event["type"] == "stop":
                        stop_reason = event.get("stop_reason", "end_turn")
                        _span_stop_reason = stop_reason
```

- [ ] **Step 4: Set span attributes after the `for` loop (before span closes)**

After the `for event in event_stream:` loop ends but still inside the `with _llm_span:` block, add:

```python
                  # Set span attributes now that stream is complete
                  _llm_span.set_attribute("gen_ai.usage.input_tokens", _span_input_tokens)
                  _llm_span.set_attribute("gen_ai.usage.output_tokens", _span_output_tokens)
                  _llm_span.set_attribute("gen_ai.response.finish_reasons", [_span_stop_reason])
```

Then close the `with _llm_span:` block. Everything that follows (building the assistant message, executing tools) is outside the span.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/agent.py
git commit -m "feat: add LLM span to _run_conversation_loop_stream (streaming)"
```

---

## Task 9: Propagate context and instrument tool spans in `execution_queue.py`

**Files:**
- Modify: `src/bourbon/tools/execution_queue.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_observability.py`:

```python
def test_tool_call_span_is_error_false_on_success():
    tracer = BourbonTracer(otel_tracer=None)
    # Simulate the pattern _run_tool uses
    is_error = False
    with tracer.tool_call(name="Read", call_id="id_1", concurrent=True) as span:
        try:
            _result = "file contents"  # simulate success
        except Exception:
            is_error = True
        span.set_attribute("bourbon.tool.is_error", is_error)
    assert is_error is False


def test_tool_call_span_is_error_true_on_exception():
    tracer = BourbonTracer(otel_tracer=None)
    is_error = False
    raw_output = ""
    with tracer.tool_call(name="Bash", call_id="id_2", concurrent=False) as span:
        try:
            raise RuntimeError("command failed")
        except Exception as exc:
            tracer.record_error(span, exc)
            raw_output = f"Error: {exc}"
            is_error = True
        span.set_attribute("bourbon.tool.is_error", is_error)
    assert is_error is True
    assert "command failed" in raw_output
```

- [ ] **Step 2: Run to confirm PASS** (these tests use the no-op tracer, so they should pass immediately after Task 2)

```bash
uv run pytest tests/test_observability.py -k "tool_call_span_is_error" -v
```
Expected: 2 passed

- [ ] **Step 3: Copy the active OTel context into worker threads**

At the top of `src/bourbon/tools/execution_queue.py`, add:

```python
from contextvars import copy_context
```

In `_process_queue()`, replace:

```python
            tool.future = self._thread_pool.submit(self._run_tool, tool)
```

with:

```python
            ctx = copy_context()
            tool.future = self._thread_pool.submit(ctx.run, self._run_tool, tool)
```

This is required because `ThreadPoolExecutor` does not automatically propagate `contextvars`; without this, concurrent tool spans will lose the active root span parent.

- [ ] **Step 4: Add the span to `_run_tool()` in `execution_queue.py`**

Find `_run_tool()` in `src/bourbon/tools/execution_queue.py`:

```python
    def _run_tool(self, tool: TrackedTool) -> None:
        name = tool.block.get("name", "")
        tool_input = tool.block.get("input", {})
        self._safe_callback(self._on_tool_start, name, tool_input)

        is_error = False
        try:
            raw_output = self._execute_fn(tool.block)
        except Exception as exc:
            raw_output = f"Error: {exc}"
            is_error = True

        output = str(raw_output)
```

Replace with:

```python
    def _run_tool(self, tool: TrackedTool) -> None:
        from bourbon.observability import get_tracer

        name = tool.block.get("name", "")
        call_id = tool.block.get("id", "")
        tool_input = tool.block.get("input", {})
        self._safe_callback(self._on_tool_start, name, tool_input)

        is_error = False
        raw_output: Any = ""
        _tracer = get_tracer()
        with _tracer.tool_call(name=name, call_id=call_id, concurrent=tool.concurrent) as _tool_span:
            try:
                raw_output = self._execute_fn(tool.block)
            except Exception as exc:
                _tracer.record_error(_tool_span, exc)
                raw_output = f"Error: {exc}"
                is_error = True
            _tool_span.set_attribute("bourbon.tool.is_error", is_error)

        output = str(raw_output)
```

Also add `Any` to the existing imports at the top of `execution_queue.py` if not already present:
```python
from typing import Any
```

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/tools/execution_queue.py
git commit -m "feat: add tool spans with context propagation"
```

---

## Task 10: Add span attribute tests using `InMemorySpanExporter`

**Files:**
- Modify: `tests/test_observability.py`

- [ ] **Step 1: Add OTel-dependent tests (skipped when OTel not installed)**

Append to `tests/test_observability.py`:

```python
def _make_test_tracer():
    """Create a BourbonTracer backed by InMemorySpanExporter for assertions."""
    pytest.importorskip("opentelemetry.sdk", reason="opentelemetry SDK not installed")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_tracer = provider.get_tracer("bourbon-test")
    return BourbonTracer(otel_tracer=otel_tracer), exporter


def test_agent_step_span_name_and_attributes():
    tracer, exporter = _make_test_tracer()
    with tracer.agent_step(workdir="/my/project"):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "invoke_agent bourbon"
    assert span.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert span.attributes["gen_ai.provider.name"] == "bourbon"
    assert span.attributes["gen_ai.agent.name"] == "bourbon"
    assert span.attributes["bourbon.agent.workdir"] == "/my/project"


def test_llm_call_span_name_and_attributes():
    tracer, exporter = _make_test_tracer()
    with tracer.llm_call(model="claude-sonnet-4-6", max_tokens=64000, provider="anthropic") as span:
        span.set_attribute("gen_ai.usage.input_tokens", 123)
        span.set_attribute("gen_ai.usage.output_tokens", 456)
        span.set_attribute("gen_ai.response.finish_reasons", ["tool_use"])
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "chat claude-sonnet-4-6"
    assert s.attributes["gen_ai.operation.name"] == "chat"
    assert s.attributes["gen_ai.provider.name"] == "anthropic"
    assert s.attributes["gen_ai.request.model"] == "claude-sonnet-4-6"
    assert s.attributes["gen_ai.request.max_tokens"] == 64000
    assert s.attributes["gen_ai.usage.input_tokens"] == 123
    assert s.attributes["gen_ai.usage.output_tokens"] == 456
    assert s.attributes["gen_ai.response.finish_reasons"] == ("tool_use",)


def test_tool_call_span_name_and_attributes():
    tracer, exporter = _make_test_tracer()
    with tracer.tool_call(name="Bash", call_id="toolu_01", concurrent=False) as span:
        span.set_attribute("bourbon.tool.is_error", False)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "execute_tool Bash"
    assert s.attributes["gen_ai.operation.name"] == "execute_tool"
    assert s.attributes["gen_ai.tool.name"] == "Bash"
    assert s.attributes["gen_ai.tool.call.id"] == "toolu_01"
    assert s.attributes["bourbon.tool.concurrent"] is False
    assert s.attributes["bourbon.tool.is_error"] is False


def test_span_parent_child_relationships():
    tracer, exporter = _make_test_tracer()
    with tracer.agent_step(workdir="/tmp"):
        with tracer.llm_call(model="m", max_tokens=100, provider="anthropic"):
            pass
        with tracer.tool_call(name="Read", call_id="id_1", concurrent=True):
            pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    by_name = {s.name: s for s in spans}
    agent_span = by_name["invoke_agent bourbon"]
    llm_span = by_name["chat m"]
    tool_span = by_name["execute_tool Read"]
    assert llm_span.parent.span_id == agent_span.context.span_id
    assert tool_span.parent.span_id == agent_span.context.span_id


def test_tool_execution_queue_preserves_context_in_threadpool():
    """Verify queue-created tool spans keep the active root span parent."""
    tracer, exporter = _make_test_tracer()
    from bourbon.observability import get_tracer, init_tracer
    from bourbon.tools.execution_queue import ToolExecutionQueue

    class ConcurrentTool:
        def concurrent_safe_for(self, tool_input: dict) -> bool:
            return True

    original = get_tracer()
    init_tracer(tracer, force=True)
    try:
        with tracer.agent_step(workdir="/tmp"):
            queue = ToolExecutionQueue(execute_fn=lambda block: "ok")
            queue.add({"id": "id_1", "name": "Read", "input": {}}, ConcurrentTool(), 0)
            queue.add({"id": "id_2", "name": "Bash", "input": {}}, ConcurrentTool(), 1)
            assert len(queue.execute_all()) == 2
    finally:
        init_tracer(original, force=True)

    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    agent_span = [s for s in spans if s.name == "invoke_agent bourbon"][0]
    tool_spans = [s for s in spans if s.name.startswith("execute_tool ")]
    assert len(tool_spans) == 2
    for ts in tool_spans:
        assert ts.parent.span_id == agent_span.context.span_id


def test_tool_execution_queue_records_swallowed_exception_as_error_span():
    tracer, exporter = _make_test_tracer()
    from opentelemetry.trace import StatusCode
    from bourbon.observability import get_tracer, init_tracer
    from bourbon.tools.execution_queue import ToolExecutionQueue

    class SerialTool:
        def concurrent_safe_for(self, tool_input: dict) -> bool:
            return False

    def fail(block: dict) -> str:
        raise RuntimeError("command failed")

    original = get_tracer()
    init_tracer(tracer, force=True)
    try:
        with tracer.agent_step(workdir="/tmp"):
            queue = ToolExecutionQueue(execute_fn=fail)
            queue.add({"id": "id_err", "name": "Bash", "input": {}}, SerialTool(), 0)
            results = queue.execute_all()
            assert results[0]["is_error"] is True
    finally:
        init_tracer(original, force=True)

    tool_span = [s for s in exporter.get_finished_spans() if s.name == "execute_tool Bash"][0]
    assert tool_span.status.status_code == StatusCode.ERROR
    assert tool_span.attributes["error.type"] == "RuntimeError"


def test_error_span_records_exception():
    tracer, exporter = _make_test_tracer()
    from opentelemetry.trace import StatusCode
    with pytest.raises(ValueError):
        with tracer.tool_call(name="Bash", call_id="id_err", concurrent=False):
            raise ValueError("tool blew up")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    s = spans[0]
    assert s.status.status_code == StatusCode.ERROR
    assert s.attributes["error.type"] == "ValueError"
    assert len(s.events) == 1  # record_exception adds one event
    assert s.events[0].name == "exception"
```

- [ ] **Step 2: Install OTel SDK for tests**

Because `pyproject.toml` has not been updated yet (Task 11 comes later), install the packages directly:

```bash
uv pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

- [ ] **Step 3: Run OTel attribute tests**

```bash
uv run pytest tests/test_observability.py -v
```
Expected: all tests pass (including the new OTel ones)

- [ ] **Step 4: Commit**

```bash
git add tests/test_observability.py
git commit -m "test: add InMemorySpanExporter span attribute assertions"
```

---

## Task 11: Add `[observability]` optional dependencies to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the optional dependency group**

In `pyproject.toml`, in the `[project.optional-dependencies]` section, after the `stage-b` block, add:

```toml
observability = [
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp-proto-http>=1.20",
]
```

- [ ] **Step 2: Verify install works**

```bash
uv pip install -e ".[observability]"
```
Expected: installs without error

- [ ] **Step 3: Run full test suite one final time**

```bash
uv run pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add [observability] optional dependencies"
```

---

## Verification

After all tasks are complete, verify the full integration manually:

```bash
# 1. Set up Langfuse (cloud or local docker)
# 2. Configure ~/.bourbon/config.toml:
#    [observability]
#    enabled = true
#    otlp_endpoint = "https://cloud.langfuse.com/api/public/otel/v1/traces"
#    otlp_headers = { Authorization = "Basic <base64(pk:sk)>" }

# 3. Run bourbon
python -m bourbon
# > 帮我列出当前目录的文件

# 4. Check Langfuse UI for:
#    - Root span "invoke_agent bourbon" with workdir attribute
#    - Child span "chat <model>" with input/output token counts
#    - Child span "execute_tool Bash" with call_id and no error status
```
