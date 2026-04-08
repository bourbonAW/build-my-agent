"""Search tools: ripgrep and ast-grep integration."""

import json
import shutil
import subprocess
from pathlib import Path

from bourbon.tools import RiskLevel, ToolContext, register_tool


def rg_search(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
    context_lines: int = 2,
    max_results: int = 100,
) -> str:
    """Search files using ripgrep.

    Args:
        pattern: Regex pattern to search
        path: Directory or file to search
        glob: File glob pattern (e.g., '*.py')
        case_sensitive: Whether to match case
        context_lines: Lines of context to include
        max_results: Maximum number of matches

    Returns:
        Search results or error message
    """
    # Check if rg is available
    if not shutil.which("rg"):
        return "Error: ripgrep (rg) not found. Please install it."

    cmd = ["rg", "--json", "--context", str(context_lines)]

    if not case_sensitive:
        cmd.append("--smart-case")
    else:
        cmd.append("--case-sensitive")

    if glob:
        cmd.extend(["--glob", glob])

    # Add default excludes
    cmd.extend(["--glob", "!.git"])

    cmd.extend([pattern, path])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode not in (0, 1):  # 0 = matches, 1 = no matches
            return f"Error: rg failed with code {result.returncode}: {result.stderr}"

        if not result.stdout.strip():
            return f"No matches for '{pattern}'"

        # Parse JSON lines
        matches = []

        for line in result.stdout.strip().split("\n"):
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data.get("data", {})
                    file_path = match_data.get("path", {}).get("text", "")
                    line_num = match_data.get("line_number", 0)

                    # Extract matched lines
                    lines = []
                    for _submatch in match_data.get("submatches", []):
                        for match_line in match_data.get("lines", {}).get("text", "").split("\n"):
                            if match_line:
                                lines.append(match_line)

                    if lines:
                        matches.append(
                            {
                                "file": file_path,
                                "line": line_num,
                                "content": lines[0] if lines else "",
                            }
                        )
            except json.JSONDecodeError:
                continue

        if not matches:
            return f"No matches for '{pattern}'"

        # Format output
        truncated = len(matches) > max_results
        matches = matches[:max_results]

        lines = [f"Found {len(matches)} matches for '{pattern}':\n"]
        for m in matches:
            lines.append(f"{m['file']}:{m['line']}: {m['content']}")

        if truncated:
            lines.append(f"\n... (results truncated to {max_results})")

        return "\n".join(lines)

    except subprocess.TimeoutExpired:
        return "Error: Search timed out (60s)"
    except Exception as e:
        return f"Error during search: {e}"


def ast_grep_search(
    pattern: str,
    path: str = ".",
    language: str | None = None,
    max_results: int = 100,
) -> str:
    """Search code using ast-grep.

    Args:
        pattern: ast-grep pattern (e.g., 'class $NAME:')
        path: Directory or file to search
        language: Language hint (python, javascript, etc.)
        max_results: Maximum number of matches

    Returns:
        Search results or error message

    Pattern examples:
        - 'class $NAME:' - Find class definitions
        - 'def $FUNC($$$ARGS):' - Find function definitions
        - '$VAR = $EXPR' - Find assignments
    """
    # Check if ast-grep is available
    if not shutil.which("ast-grep"):
        return "Error: ast-grep not found. Please install it: https://ast-grep.github.io/"

    cmd = ["ast-grep", "run", "--json", "--pattern", pattern]

    if language:
        cmd.extend(["--lang", language])

    cmd.append(path)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Parse JSON output
        try:
            matches = json.loads(result.stdout) if result.stdout.strip() else []
            if not isinstance(matches, list):
                matches = [matches] if matches else []
        except json.JSONDecodeError:
            return f"No matches for pattern '{pattern}'"

        if not matches:
            return f"No matches for pattern '{pattern}'"

        # Format output
        truncated = len(matches) > max_results
        matches = matches[:max_results]

        lines = [f"Found {len(matches)} AST matches for '{pattern}':\n"]
        for m in matches:
            file_path = m.get("file", "")
            line = m.get("range", {}).get("start", {}).get("line", 0)
            text = m.get("text", "").replace("\n", " ")[:100]
            lines.append(f"{file_path}:{line}: {text}")

        if truncated:
            lines.append(f"\n... (results truncated to {max_results})")

        return "\n".join(lines)

    except subprocess.TimeoutExpired:
        return "Error: Search timed out (60s)"
    except Exception as e:
        return f"Error during search: {e}"


def glob_files(pattern: str, path: str = ".", *, workdir: Path | None = None) -> str:
    """Find files matching a glob pattern."""
    cwd = workdir or Path.cwd()
    base = Path(path) if Path(path).is_absolute() else cwd / path

    try:
        matches = sorted(base.glob(pattern))
    except Exception as e:
        return f"Error: {e}"

    truncated = len(matches) > 100
    matches = matches[:100]

    if not matches:
        return f"No files matching '{pattern}'"

    lines = [str(match.relative_to(cwd) if match.is_relative_to(cwd) else match) for match in matches]
    if truncated:
        lines.append("... (results truncated to 100 files)")
    return "\n".join(lines)


# Register tools
@register_tool(
    name="Grep",
    aliases=["rg_search"],
    description="Search files using ripgrep (regex-based text search).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search (default: current directory)",
            },
            "glob": {
                "type": "string",
                "description": "File glob pattern, e.g., '*.py'",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search",
            },
        },
        "required": ["pattern"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def grep_handler(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
    *,
    ctx: ToolContext,
) -> str:
    """Tool handler for Grep."""
    resolved_path = str(ctx.workdir / path) if not Path(path).is_absolute() else path
    return rg_search(pattern, resolved_path, glob, case_sensitive)


@register_tool(
    name="AstGrep",
    aliases=["ast_grep_search"],
    description="Search code using ast-grep (structural/AST-based search).",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "ast-grep pattern (e.g., 'class $NAME:', 'def $FUNC($$$ARGS):')",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search",
            },
            "language": {
                "type": "string",
                "description": "Language hint (python, javascript, rust, etc.)",
            },
        },
        "required": ["pattern"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def ast_grep_handler(
    pattern: str,
    path: str = ".",
    language: str | None = None,
    *,
    ctx: ToolContext,
) -> str:
    """Tool handler for AstGrep."""
    resolved_path = str(ctx.workdir / path) if not Path(path).is_absolute() else path
    return ast_grep_search(pattern, resolved_path, language)


@register_tool(
    name="Glob",
    description="Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '**/*.py'",
            },
            "path": {
                "type": "string",
                "description": "Base directory to search (default: workspace root)",
            },
        },
        "required": ["pattern"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    required_capabilities=["file_read"],
)
def glob_handler(pattern: str, path: str = ".", *, ctx: ToolContext) -> str:
    """Tool handler for Glob."""
    return glob_files(pattern, path, workdir=ctx.workdir)
