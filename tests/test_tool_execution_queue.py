"""Tests for ToolExecutionQueue concurrent tool execution."""

import threading
import time

from bourbon.tools.execution_queue import ToolExecutionQueue, ToolStatus


def make_tool_obj(*, concurrent: bool):
    """Create a minimal Tool-like object with concurrent_safe_for()."""

    class FakeTool:
        def concurrent_safe_for(self, inp):
            return concurrent

    return FakeTool()


def make_block(tool_id: str, name: str = "Read") -> dict:
    return {"id": tool_id, "name": name, "input": {}}


def simple_execute(block: dict) -> str:
    return f"result:{block['id']}"


def test_execute_all_returns_results_in_original_order():
    q = ToolExecutionQueue(execute_fn=simple_execute)
    blocks = [make_block(f"id{i}") for i in range(3)]
    tools = [make_tool_obj(concurrent=True) for _ in blocks]
    for i, (block, tool) in enumerate(zip(blocks, tools)):
        q.add(block, tool, i)

    results = q.execute_all()

    assert len(results) == 3
    assert results[0]["tool_use_id"] == "id0"
    assert results[1]["tool_use_id"] == "id1"
    assert results[2]["tool_use_id"] == "id2"
    assert results[0]["content"] == "result:id0"


def test_all_concurrent_tools_run_in_parallel():
    """Concurrent tools should overlap in time."""
    start_times = {}
    lock = threading.Lock()

    def slow_execute(block):
        with lock:
            start_times[block["id"]] = time.monotonic()
        time.sleep(0.05)
        return "ok"

    q = ToolExecutionQueue(execute_fn=slow_execute)
    blocks = [make_block(f"c{i}") for i in range(3)]
    for i, block in enumerate(blocks):
        q.add(block, make_tool_obj(concurrent=True), i)

    results = q.execute_all()

    assert len(results) == 3
    times = list(start_times.values())
    assert max(times) - min(times) < 0.04, "Expected concurrent execution"


def test_serial_tool_blocks_until_concurrent_done():
    """A serial tool should not start until all concurrent tools finish."""
    order = []
    lock = threading.Lock()

    def execute(block):
        with lock:
            order.append(block["id"])
        return "ok"

    q = ToolExecutionQueue(execute_fn=execute)
    q.add(make_block("conc1"), make_tool_obj(concurrent=True), 0)
    q.add(make_block("conc2"), make_tool_obj(concurrent=True), 1)
    q.add(make_block("serial"), make_tool_obj(concurrent=False), 2)
    q.execute_all()

    assert order.index("serial") > order.index("conc1")
    assert order.index("serial") > order.index("conc2")


def test_tool_status_queued_then_completed():
    q = ToolExecutionQueue(execute_fn=simple_execute)
    block = make_block("x1")
    tool = make_tool_obj(concurrent=True)
    q.add(block, tool, 0)

    assert q._tools[0].status == ToolStatus.QUEUED

    q.execute_all()

    assert q._tools[0].status == ToolStatus.COMPLETED


def test_execute_fn_exception_becomes_error_result():
    def bad_execute(block):
        raise ValueError("oops")

    q = ToolExecutionQueue(execute_fn=bad_execute)
    q.add(make_block("err1"), make_tool_obj(concurrent=False), 0)

    results = q.execute_all()

    assert results[0]["content"].startswith("Error:")


def test_on_tool_start_and_end_called_for_each_tool():
    starts = []
    ends = []
    q = ToolExecutionQueue(
        execute_fn=simple_execute,
        on_tool_start=lambda name, inp: starts.append(name),
        on_tool_end=lambda name, out: ends.append(name),
    )
    blocks = [make_block(f"cb{i}", name=f"Tool{i}") for i in range(2)]
    for i, block in enumerate(blocks):
        q.add(block, make_tool_obj(concurrent=True), i)

    q.execute_all()

    assert len(starts) == 2
    assert len(ends) == 2


def test_callback_exception_does_not_abort_execution():
    def bad_callback(name, _):
        raise RuntimeError("callback boom")

    q = ToolExecutionQueue(
        execute_fn=simple_execute,
        on_tool_start=bad_callback,
    )
    q.add(make_block("safe1"), make_tool_obj(concurrent=False), 0)

    results = q.execute_all()

    assert results[0]["content"] == "result:safe1"


def test_concurrent_callbacks_are_serialized():
    """on_tool_start must not interleave from concurrent worker threads."""
    callback_order = []
    cb_lock = threading.Lock()

    def on_start(name, inp):
        time.sleep(0.01)
        with cb_lock:
            callback_order.append(threading.current_thread().name)

    q = ToolExecutionQueue(
        execute_fn=lambda b: (time.sleep(0.02), "ok")[1],
        on_tool_start=on_start,
    )
    for i in range(4):
        q.add(make_block(f"p{i}"), make_tool_obj(concurrent=True), i)

    q.execute_all()

    assert len(callback_order) == 4


def test_empty_queue_execute_all_returns_empty():
    q = ToolExecutionQueue(execute_fn=simple_execute)

    assert q.execute_all() == []


def test_result_content_is_string():
    q = ToolExecutionQueue(execute_fn=lambda b: 42)
    q.add(make_block("x"), make_tool_obj(concurrent=False), 0)

    results = q.execute_all()

    assert isinstance(results[0]["content"], str)
