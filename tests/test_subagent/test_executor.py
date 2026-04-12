import threading

from bourbon.subagent.executor import AsyncExecutor


def test_async_executor_submit_returns_future_result():
    executor = AsyncExecutor(max_workers=1)

    future = executor.submit("run-1", lambda: "done")

    assert future.result(timeout=1) == "done"
    executor.shutdown()


def test_async_executor_tracks_running_future():
    executor = AsyncExecutor(max_workers=1)
    started = threading.Event()
    release = threading.Event()

    def wait_for_release():
        started.set()
        release.wait(timeout=1)
        return "done"

    future = executor.submit("run-1", wait_for_release)
    started.wait(timeout=1)

    assert executor.get_future("run-1") is future

    release.set()
    assert future.result(timeout=1) == "done"
    executor.shutdown()


def test_async_executor_removes_future_when_done():
    executor = AsyncExecutor(max_workers=1)

    future = executor.submit("run-1", lambda: "done")
    assert future.result(timeout=1) == "done"

    assert executor.get_future("run-1") is None
    executor.shutdown()


def test_async_executor_exported_from_package():
    from bourbon.subagent import AsyncExecutor as ExportedAsyncExecutor

    assert ExportedAsyncExecutor is AsyncExecutor
