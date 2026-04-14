# tests/test_tool_concurrency_safe.py
"""Tests for Tool.concurrent_safe_for() and register_tool concurrency_fn parameter."""
from dataclasses import field
from unittest.mock import MagicMock

import pytest

from bourbon.tools import Tool, RiskLevel, register_tool


def make_tool(*, is_safe=False, fn=None):
    return Tool(
        name="TestTool",
        description="test",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: "ok",
        is_concurrency_safe=is_safe,
        _concurrency_fn=fn,
    )


def test_concurrent_safe_for_returns_bool_when_no_fn():
    t = make_tool(is_safe=True)
    assert t.concurrent_safe_for({}) is True

    t2 = make_tool(is_safe=False)
    assert t2.concurrent_safe_for({}) is False


def test_concurrent_safe_for_uses_fn_over_bool():
    fn = lambda inp: inp.get("readonly", False)
    t = make_tool(is_safe=False, fn=fn)  # bool says False
    assert t.concurrent_safe_for({"readonly": True}) is True
    assert t.concurrent_safe_for({"readonly": False}) is False


def test_concurrent_safe_for_returns_false_on_fn_exception():
    def bad_fn(inp):
        raise RuntimeError("boom")

    t = make_tool(is_safe=True, fn=bad_fn)  # fn raises, fallback bool ignored, returns False
    assert t.concurrent_safe_for({}) is False


def test_register_tool_accepts_concurrency_fn():
    called_with = []

    def my_fn(inp):
        called_with.append(inp)
        return True

    # Register under a unique name so it doesn't clash with real tools
    @register_tool(
        name="_TestConcurrencyFnTool",
        description="test",
        input_schema={"type": "object", "properties": {}},
        concurrency_fn=my_fn,
    )
    def handler(**kwargs):
        return "ok"

    from bourbon.tools import get_registry
    tool = get_registry().get_tool("_TestConcurrencyFnTool")
    assert tool is not None
    assert tool.concurrent_safe_for({"x": 1}) is True
    assert called_with == [{"x": 1}]
