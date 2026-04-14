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


def test_inferred_context_default_lists_are_not_shared():
    first = InferredContext()
    second = InferredContext()

    first.capabilities.append(CapabilityType.EXEC)
    first.file_paths.append("src/main.py")

    assert second.capabilities == []
    assert second.file_paths == []


def test_extracts_paths_for_file_tools():
    read_context = infer_capabilities(
        "Read",
        {"path": "src/app.py"},
        [CapabilityType.EXEC],
    )
    write_context = infer_capabilities(
        "Write",
        {"path": "notes/todo.txt"},
        [],
    )
    edit_context = infer_capabilities(
        "Edit",
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
        "Bash",
        {"command": "echo hello"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC]
    assert context.file_paths == []


def test_bash_ignores_non_command_fields():
    context = infer_capabilities(
        "Bash",
        {"command": "echo hello", "path": "src/app.py", "note": "curl https://example.com"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC]
    assert context.file_paths == []


def test_bash_pip_install_adds_net():
    context = infer_capabilities(
        "Bash",
        {"command": "pip install requests"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC, CapabilityType.NET]
    assert context.file_paths == []


def test_bash_read_detection_adds_file_read():
    context = infer_capabilities(
        "Bash",
        {"command": "cat /etc/hosts"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC, CapabilityType.FILE_READ]
    assert context.file_paths == []


def test_bash_write_detection_adds_file_write():
    context = infer_capabilities(
        "Bash",
        {"command": "echo hi > out.txt"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC, CapabilityType.FILE_WRITE]
    assert context.file_paths == []


def test_bash_path_like_content_does_not_extract_file_paths():
    context = infer_capabilities(
        "Bash",
        {"command": "cat src/app.py"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC, CapabilityType.FILE_READ]
    assert context.file_paths == []


def test_unknown_tool_returns_base_capabilities_and_no_paths():
    context = infer_capabilities(
        "unknown",
        {"command": "curl https://example.com", "path": "src/app.py"},
        [CapabilityType.EXEC],
    )

    assert context.capabilities == [CapabilityType.EXEC]
    assert context.file_paths == []


def test_unknown_tool_preserves_base_capabilities_exactly():
    base_capabilities = [CapabilityType.EXEC, CapabilityType.EXEC]

    context = infer_capabilities("unknown", {"path": "src/app.py"}, base_capabilities)

    assert context.capabilities == base_capabilities
    assert context.file_paths == []


class TestCapabilitiesNewNames:
    def test_new_names_infer_file_capabilities(self):
        """Canonical tool names should infer the expected file capabilities."""
        read_context = infer_capabilities("Read", {"path": "src/app.py"}, [])
        assert CapabilityType.FILE_READ in read_context.capabilities
        assert read_context.file_paths == ["src/app.py"]

        write_context = infer_capabilities("Write", {"path": "out.txt"}, [])
        assert CapabilityType.FILE_WRITE in write_context.capabilities

        edit_context = infer_capabilities("Edit", {"path": "notes.md"}, [])
        assert CapabilityType.FILE_WRITE in edit_context.capabilities

        grep_context = infer_capabilities("Grep", {"path": "src/"}, [])
        assert CapabilityType.FILE_READ in grep_context.capabilities

        glob_context = infer_capabilities("Glob", {}, [])
        assert CapabilityType.FILE_READ in glob_context.capabilities

    def test_bash_new_name_infers_net_capability(self):
        context = infer_capabilities("Bash", {"command": "curl https://example.com"}, [])
        assert CapabilityType.NET in context.capabilities

    def test_ast_grep_uses_workdir_default_path(self):
        context = infer_capabilities("AstGrep", {}, [])
        assert "." in context.file_paths

    def test_glob_uses_workdir_default_path_when_no_path_given(self):
        """Glob with no path argument should default to workdir ('.') for audit."""
        context = infer_capabilities("Glob", {}, [])
        assert CapabilityType.FILE_READ in context.capabilities
        assert "." in context.file_paths, (
            "Glob with no path should default to '.' like Grep/AstGrep"
        )

    def test_glob_with_explicit_path_uses_that_path(self):
        """Glob with explicit path should use that path, not default."""
        context = infer_capabilities("Glob", {"path": "src/"}, [])
        assert CapabilityType.FILE_READ in context.capabilities
        assert context.file_paths == ["src/"]

    def test_stage_b_tools_infer_file_read(self):
        for tool_name in ("CsvAnalyze", "JsonQuery", "PdfRead", "DocxRead"):
            context = infer_capabilities(tool_name, {"file_path": "data/file.csv"}, [])
            assert CapabilityType.FILE_READ in context.capabilities
            assert context.file_paths == ["data/file.csv"]
