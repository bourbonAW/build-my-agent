"""Queue-based concurrent tool execution."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from contextvars import Context, copy_context
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bourbon.observability.tracer import BourbonTracer

ToolBlock = dict[str, Any]
ToolResult = dict[str, Any]


class ToolStatus(Enum):
    """Execution state for a queued tool call."""

    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"


@dataclass
class TrackedTool:
    """Tool call plus queue state."""

    block: ToolBlock
    tool: Any
    concurrent: bool
    original_index: int
    status: ToolStatus = ToolStatus.QUEUED
    result: ToolResult | None = None
    future: Future[None] | None = None


@dataclass(frozen=True)
class ToolExecutionOutcome:
    content: str
    is_error: bool = False
    error_type: str = "tool_error"
    error_message: str = ""


class ToolExecutionQueue:
    """Execute concurrent-safe tools in parallel and serial tools exclusively."""

    MAX_CONCURRENT_WORKERS = 10

    def __init__(
        self,
        execute_fn: Callable[[ToolBlock], Any],
        on_tool_start: Callable[[str, ToolBlock], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
        tracer: BourbonTracer | None = None,
    ) -> None:
        self._tools: list[TrackedTool] = []
        self._lock = threading.Lock()
        self._callback_lock = threading.Lock()
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT_WORKERS,
            thread_name_prefix="tool_queue_",
        )
        self._execute_fn = execute_fn
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._tracer = tracer or BourbonTracer(otel_tracer=None)
        self._parent_context: Context | None = None

    def add(self, block: ToolBlock, tool: Any, index: int) -> None:
        """Enqueue one tool call. Call before execute_all()."""
        concurrent_safe_for = getattr(tool, "concurrent_safe_for", None)
        concurrent = (
            bool(concurrent_safe_for(block.get("input", {})))
            if callable(concurrent_safe_for)
            else False
        )
        with self._lock:
            self._tools.append(
                TrackedTool(
                    block=block,
                    tool=tool,
                    concurrent=concurrent,
                    original_index=index,
                )
            )

    def execute_all(self) -> list[ToolResult]:
        """Run all queued tools and return tool_result blocks in original order."""
        try:
            self._parent_context = copy_context()
            self._process_queue()
            self._wait_all()
            with self._lock:
                return [
                    tool.result
                    for tool in sorted(self._tools, key=lambda item: item.original_index)
                    if tool.result is not None
                ]
        finally:
            self._thread_pool.shutdown(wait=True)

    def _copy_parent_context(self) -> Context:
        return self._parent_context.copy() if self._parent_context is not None else copy_context()

    def _can_execute(self, concurrent: bool) -> bool:
        """Return whether a queued tool can start now. Requires self._lock."""
        executing = [tool for tool in self._tools if tool.status == ToolStatus.EXECUTING]
        return len(executing) == 0 or (concurrent and all(tool.concurrent for tool in executing))

    def _process_queue(self) -> None:
        """Start every currently eligible queued tool."""
        to_start: list[TrackedTool] = []
        with self._lock:
            for tool in self._tools:
                if tool.status != ToolStatus.QUEUED:
                    continue
                if self._can_execute(tool.concurrent):
                    tool.status = ToolStatus.EXECUTING
                    to_start.append(tool)
                elif not tool.concurrent:
                    break

        for tool in to_start:
            ctx = self._copy_parent_context()
            tool.future = self._thread_pool.submit(ctx.run, self._run_tool, tool)
            if tool.concurrent:
                callback_ctx = self._copy_parent_context()

                def on_done(
                    _future: Future[None],
                    tracked: TrackedTool = tool,
                    cb_ctx: Context = callback_ctx,
                ) -> None:
                    cb_ctx.run(self._on_tool_done, tracked)

                tool.future.add_done_callback(on_done)

    def _run_tool(self, tool: TrackedTool) -> None:
        name = tool.block.get("name", "")
        tool_input = tool.block.get("input", {})
        self._safe_callback(self._on_tool_start, name, tool_input)

        is_error = False
        error_type = "tool_error"
        error_message = ""
        with self._tracer.tool_call(
            name=name,
            call_id=tool.block.get("id", ""),
            concurrent=tool.concurrent,
        ) as _tool_span:
            try:
                raw = self._execute_fn(tool.block)
            except Exception as exc:
                raw_output = f"Error: {exc}"
                is_error = True
                error_type = type(exc).__name__
                error_message = str(exc)
                self._tracer.record_error(_tool_span, exc)
            else:
                if isinstance(raw, ToolExecutionOutcome):
                    raw_output = raw.content
                    is_error = raw.is_error
                    error_type = raw.error_type
                    error_message = raw.error_message or raw.content
                else:
                    raw_output = str(raw)
                    is_error = False

                self._tracer.mark_tool_result(
                    _tool_span,
                    is_error=is_error,
                    error_type=error_type,
                    message=error_message,
                )

        output = str(raw_output)
        tool.result = {
            "type": "tool_result",
            "tool_use_id": tool.block.get("id", ""),
            "content": output[:50000],
            **({"is_error": True} if is_error else {}),
        }
        self._safe_callback(self._on_tool_end, name, output)

        with self._lock:
            tool.status = ToolStatus.COMPLETED

    def _safe_callback(self, fn: Callable[..., None] | None, *args: Any) -> None:
        if fn is None:
            return
        with self._callback_lock, suppress(Exception):
            fn(*args)

    def _on_tool_done(self, tool: TrackedTool) -> None:
        self._process_queue()

    def _wait_all(self) -> None:
        while True:
            with self._lock:
                pending = [
                    tool.future
                    for tool in self._tools
                    if tool.future is not None and tool.status != ToolStatus.COMPLETED
                ]
                all_done = all(t.status == ToolStatus.COMPLETED for t in self._tools)
            if all_done:
                break
            for future in pending:
                future.result()
            self._process_queue()
