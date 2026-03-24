"""Tests for capability inference."""

from bourbon.access_control.capabilities import (
    CapabilityType,
    InferredContext,
    infer_capabilities,
)


def test_capability_type_values():
    assert CapabilityType.FILE_READ.value == "file_read"
    assert CapabilityType.FILE_WRITE.value == "file_write"
    assert CapabilityType.EXEC.value == "exec"
    assert CapabilityType.NET.value == "net"
    assert CapabilityType.SKILL.value == "skill"
    assert CapabilityType.MCP.value == "mcp"


def test_inferred_context_shape():
    context = InferredContext(
        capabilities=[CapabilityType.FILE_READ],
        file_paths=["src/main.py"],
    )

    assert context.capabilities == [CapabilityType.FILE_READ]
    assert context.file_paths == ["src/main.py"]


def test_extracts_paths_for_file_tools():
    read_context = infer_capabilities(
        "read_file",
        {"path": "src/app.py"},
        [CapabilityType.EXEC],
    )
    write_context = infer_capabilities(
        "write_file",
        {"path": "notes/todo.txt"},
        [],
    )
    edit_context = infer_capabilities(
        "edit_file",
        {"path": "docs/spec.md"},
        [],
    )

    assert read_context.capabilities == [CapabilityType.EXEC, CapabilityType.FILE_READ]
    assert read_context.file_paths == ["src/app.py"]
    assert write_context.capabilities == [CapabilityType.FILE_WRITE]
    assert write_context.file_paths == ["notes/todo.txt"]
    assert edit_context.capabilities == [CapabilityType.FILE_WRITE]
    assert edit_context.file_paths == ["docs/spec.md"]


def test_bash_basic_returns_exec_only_and_no_paths():
    context = infer_capabilities(
        "bash",
        {"command": "echo hello"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC]
    assert context.file_paths == []


def test_bash_pip_install_adds_net():
    context = infer_capabilities(
        "bash",
        {"command": "pip install requests"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC, CapabilityType.NET]
    assert context.file_paths == []


def test_unknown_tool_returns_base_capabilities_and_no_paths():
    context = infer_capabilities(
        "unknown",
        {"command": "curl https://example.com", "path": "src/app.py"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC]
    assert context.file_paths == []
