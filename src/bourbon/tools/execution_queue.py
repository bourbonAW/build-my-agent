"""Queue-based concurrent tool execution."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolStatus(Enum):
    """Execution state for a queued tool call."""

    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"


@dataclass
class TrackedTool:
    """Tool call plus queue state."""

    block: dict
    tool: Any
    concurrent: bool
    original_index: int
    status: ToolStatus = ToolStatus.QUEUED
    result: dict | None = None
    future: Future | None = None


class ToolExecutionQueue:
    """Execute concurrent-safe tools in parallel and serial tools exclusively."""

    MAX_CONCURRENT_WORKERS = 10

    def __init__(
        self,
        execute_fn: Callable[[dict], str],
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
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

    def add(self, block: dict, tool: Any, index: int) -> None:
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

    def execute_all(self) -> list[dict]:
        """Run all queued tools and return tool_result blocks in original order."""
        try:
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

    def _can_execute(self, concurrent: bool) -> bool:
        """Return whether a queued tool can start now. Requires self._lock."""
        executing = [tool for tool in self._tools if tool.status == ToolStatus.EXECUTING]
        return len(executing) == 0 or (
            concurrent and all(tool.concurrent for tool in executing)
        )

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
            tool.future = self._thread_pool.submit(self._run_tool, tool)
            if tool.concurrent:
                tool.future.add_done_callback(
                    lambda _future, tracked=tool: self._on_tool_done(tracked)
                )

    def _run_tool(self, tool: TrackedTool) -> None:
        name = tool.block.get("name", "")
        tool_input = tool.block.get("input", {})
        self._safe_callback(self._on_tool_start, name, tool_input)

        try:
            raw_output = self._execute_fn(tool.block)
        except Exception as exc:
            raw_output = f"Error: {exc}"

        output = str(raw_output)
        tool.result = {
            "type": "tool_result",
            "tool_use_id": tool.block.get("id", ""),
            "content": output[:50000],
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
                    tool
                    for tool in self._tools
                    if tool.future is not None and tool.status != ToolStatus.COMPLETED
                ]
            if not pending:
                break
            for tool in pending:
                tool.future.result()
            self._process_queue()
