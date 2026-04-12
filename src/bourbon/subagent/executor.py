"""Async execution helper for background subagent runs."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any


class AsyncExecutor:
    """Manages a thread pool and active futures for background runs."""

    def __init__(self, max_workers: int = 10):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="subagent_",
        )
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit(
        self,
        run_id: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Future:
        """Submit a runtime job to the thread pool."""
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[run_id] = future

        def cleanup(_future: Future) -> None:
            with self._lock:
                self._futures.pop(run_id, None)

        future.add_done_callback(cleanup)
        return future

    def get_future(self, run_id: str) -> Future | None:
        """Return the active future for a runtime job if it is still running."""
        with self._lock:
            return self._futures.get(run_id)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the thread pool."""
        self._executor.shutdown(wait=wait)
