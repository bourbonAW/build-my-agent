"""Utilities for running long-lived async MCP resources from sync code."""

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from contextlib import suppress
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncRuntime:
    """Run async coroutines on a dedicated background event loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._lock = threading.Lock()
        self._queue: (
            asyncio.Queue[tuple[Coroutine[Any, Any, Any], Future[Any]] | None] | None
        ) = None
        self._worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the background event loop if it is not already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return

            self._started.clear()
            loop = asyncio.new_event_loop()

            def run_loop() -> None:
                asyncio.set_event_loop(loop)
                queue: asyncio.Queue[tuple[Coroutine[Any, Any, Any], Future[Any]] | None] = (
                    asyncio.Queue()
                )
                self._queue = queue

                async def worker() -> None:
                    while True:
                        item = await queue.get()
                        if item is None:
                            return

                        coro, future = item
                        if future.cancelled():
                            coro.close()
                            continue

                        try:
                            result = await coro
                        except Exception as e:
                            future.set_exception(e)
                        else:
                            future.set_result(result)

                self._worker_task = loop.create_task(worker())
                self._started.set()
                try:
                    loop.run_forever()
                finally:
                    if self._worker_task and not self._worker_task.done():
                        self._worker_task.cancel()
                        with suppress(asyncio.CancelledError):
                            loop.run_until_complete(self._worker_task)
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

            thread = threading.Thread(
                target=run_loop,
                name="bourbon-mcp-runtime",
                daemon=True,
            )
            self._loop = loop
            self._thread = thread
            thread.start()

        self._started.wait()

    def run(self, coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
        """Run a coroutine on the background loop and wait for the result."""
        self.start()
        if self._loop is None or self._queue is None:
            raise RuntimeError("MCP runtime loop is not available")

        future: Future[T] = Future()

        def submit() -> None:
            if self._queue is None:
                future.set_exception(RuntimeError("MCP runtime queue is not available"))
                return
            self._queue.put_nowait((coro, future))

        self._loop.call_soon_threadsafe(submit)
        return future.result(timeout=timeout)

    def stop(self) -> None:
        """Stop the background event loop."""
        with self._lock:
            loop = self._loop
            thread = self._thread
            queue = self._queue
            self._loop = None
            self._thread = None
            self._queue = None
            self._worker_task = None
            self._started.clear()

        if loop is None or thread is None:
            return

        def shutdown() -> None:
            if queue is not None:
                queue.put_nowait(None)
            loop.stop()

        loop.call_soon_threadsafe(shutdown)
        thread.join(timeout=5)
