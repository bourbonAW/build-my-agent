"""Base tools: bash, read, write, edit."""

import subprocess
from pathlib import Path

from bourbon.tools import RiskLevel, register_tool


def safe_path(path: str, workdir: Path) -> Path:
    """Validate and resolve path within workspace.

    Args:
        path: Path string (relative or absolute)
        workdir: Workspace root directory

    Returns:
        Resolved Path object

    Raises:
        ValueError: If path escapes workspace
    """
    # Handle absolute paths
    if Path(path).is_absolute():
        resolved = Path(path).resolve()
    else:
        resolved = (workdir / path).resolve()

    # Check for path traversal
    try:
        resolved.relative_to(workdir.resolve())
    except ValueError as e:
        raise ValueError(f"Path escapes workspace: {path}") from e

    return resolved


def run_bash(
    command: str,
    workdir: Path | None = None,
    timeout: int = 120,
    max_output: int = 50000,
) -> str:
    """Run a shell command.

    Args:
        command: Shell command to run
        workdir: Working directory (default: current)
        timeout: Timeout in seconds
        max_output: Maximum output length

    Returns:
        Command output or error message
    """
    cwd = workdir or Path.cwd()

    # Security checks
    dangerous = ["rm -rf /", "sudo ", "shutdown", "reboot", "> /dev/sda", "mkfs."]
    for d in dangerous:
        if d in command:
            return f"Error: Dangerous command blocked ({d})"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()

        if not output:
            return "(no output)"

        if len(output) > max_output:
            output = output[:max_output] + f"\n... ({len(output) - max_output} more chars)"

        return output

    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"


def read_file(
    path: str,
    workdir: Path | None = None,
    limit: int | None = None,
    max_output: int = 50000,
) -> str:
    """Read file contents.

    Args:
        path: File path (relative to workdir)
        workdir: Workspace root
        limit: Maximum lines to read
        max_output: Maximum characters to return

    Returns:
        File contents or error message
    """
    cwd = workdir or Path.cwd()

    try:
        fp = safe_path(path, cwd)

        if not fp.exists():
            return f"Error: File not found: {path}"

        if not fp.is_file():
            return f"Error: Not a file: {path}"

        lines = fp.read_text().splitlines()

        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]

        content = "\n".join(lines)

        if len(content) > max_output:
            content = content[:max_output] + f"\n... ({len(content) - max_output} more chars)"

        return content

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def write_file(
    path: str,
    content: str,
    workdir: Path | None = None,
) -> str:
    """Write content to file.

    Args:
        path: File path (relative to workdir)
        content: Content to write
        workdir: Workspace root

    Returns:
        Success or error message
    """
    cwd = workdir or Path.cwd()

    try:
        fp = safe_path(path, cwd)

        # Create parent directories
        fp.parent.mkdir(parents=True, exist_ok=True)

        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    workdir: Path | None = None,
) -> str:
    """Replace text in file.

    Args:
        path: File path
        old_text: Text to find
        new_text: Text to replace with
        workdir: Workspace root

    Returns:
        Success or error message
    """
    cwd = workdir or Path.cwd()

    try:
        fp = safe_path(path, cwd)

        if not fp.exists():
            return f"Error: File not found: {path}"

        content = fp.read_text()

        if old_text not in content:
            return f"Error: Text not found in {path}"

        # Replace only first occurrence
        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content)

        return f"Edited {path}"

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error editing {path}: {e}"


# Register tools with schemas
@register_tool(
    name="bash",
    description="Run a shell command in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
        },
        "required": ["command"],
    },
    risk_level=RiskLevel.HIGH,
)
def bash_tool(command: str) -> str:
    """Tool handler for bash."""
    return run_bash(command)


@register_tool(
    name="read_file",
    description="Read the contents of a file.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file (relative to workspace)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
        },
        "required": ["path"],
    },
    risk_level=RiskLevel.LOW,
)
def read_file_tool(path: str, limit: int | None = None) -> str:
    """Tool handler for read_file."""
    return read_file(path, limit=limit)


@register_tool(
    name="write_file",
    description="Write content to a file (creates directories if needed).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file",
            },
            "content": {
                "type": "string",
                "description": "Content to write",
            },
        },
        "required": ["path", "content"],
    },
    risk_level=RiskLevel.MEDIUM,
)
def write_file_tool(path: str, content: str) -> str:
    """Tool handler for write_file."""
    return write_file(path, content)


@register_tool(
    name="edit_file",
    description="Replace exact text in a file (only first occurrence).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file",
            },
            "old_text": {
                "type": "string",
                "description": "Text to find",
            },
            "new_text": {
                "type": "string",
                "description": "Text to replace with",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
    risk_level=RiskLevel.MEDIUM,
)
def edit_file_tool(path: str, old_text: str, new_text: str) -> str:
    """Tool handler for edit_file."""
    return edit_file(path, old_text, new_text)
