# tests/test_is_readonly_bash.py
"""Tests for the _is_readonly_bash concurrency gate."""
import pytest


def get_fn():
    """Lazy import after bourbon.tools.base has been loaded."""
    from bourbon.tools.base import _is_readonly_bash
    return _is_readonly_bash


@pytest.mark.parametrize("cmd,expected", [
    # 控制符 → False
    ("ls | grep foo", False),
    ("cat file && echo done", False),
    ("echo a; echo b", False),
    ("cat > /tmp/x", False),
    ("echo $(pwd)", False),
    ("cmd1 || cmd2", False),
    ("ls >> out.txt", False),
    ("sleep 1 &", False),
    # 多行 → False
    ("ls\necho hi", False),
    # 路径前缀 → False
    ("/bin/ls", False),
    # 非白名单命令 → False
    ("curl http://example.com", False),
    ("rm -rf /", False),
    ("python script.py", False),
    # 白名单命令的可写/阻塞参数 → False
    ("tail -f log", False),
    ("tail --follow log", False),
    ("sort -o sorted.txt items.txt", False),
    ("sort --output=sorted.txt items.txt", False),
    ("uniq input.txt output.txt", False),
    ("find . -fprint out.txt", False),
    ("find . -fprintf out.txt %p", False),
    ("find . -fls out.txt", False),
    # 白名单命令 → True
    ("ls -la", True),
    ("cat README.md", True),
    ("grep -r foo src/", True),
    ("find . -name '*.py'", True),
    ("echo hello world", True),
    ("wc -l file.txt", True),
    ("head -20 file", True),
    ("tail -20 log", True),
    ("stat file.txt", True),
    ("diff a.txt b.txt", True),
    ("sort items.txt", True),
    ("uniq -c words.txt", True),
    ("pwd", True),
    # find 带危险 flag → False
    ("find . -delete", False),
    ("find . -exec rm {} \\;", False),
])
def test_is_readonly_bash(cmd, expected):
    fn = get_fn()
    assert fn({"command": cmd}) is expected, f"Failed for: {cmd!r}"


def test_is_readonly_bash_empty_input():
    fn = get_fn()
    assert fn({}) is False


def test_is_readonly_bash_non_string_command():
    fn = get_fn()
    assert fn({"command": 42}) is False


def test_bash_tool_has_concurrency_fn():
    """Bash tool should have a _concurrency_fn, not just is_concurrency_safe=True."""
    from bourbon.tools import (
        definitions,  # trigger registration
        get_registry,
    )
    definitions()
    tool = get_registry().get_tool("Bash")
    assert tool is not None
    assert tool._concurrency_fn is not None


def test_agent_tool_is_concurrency_safe():
    from bourbon.tools import definitions, get_registry
    definitions()
    tool = get_registry().get_tool("Agent")
    assert tool is not None
    assert tool.is_concurrency_safe is True


def test_webfetch_is_concurrency_safe():
    from bourbon.tools import definitions, get_registry
    definitions()
    tool = get_registry().get_tool("WebFetch")
    assert tool is not None
    assert tool.is_concurrency_safe is True
