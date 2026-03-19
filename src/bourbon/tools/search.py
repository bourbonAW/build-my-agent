"""Search tools: ripgrep and ast-grep integration."""

import json
import shutil
import subprocess
from pathlib import Path

from bourbon.tools import RiskLevel, register_tool


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
                    for submatch in match_data.get("submatches", []):
                        for l in match_data.get("lines", {}).get("text", "").split("\n"):
                            if l:
                                lines.append(l)

                    if lines:
                        matches.append({
                            "file": file_path,
                            "line": line_num,
                            "content": lines[0] if lines else "",
                        })
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


# Register tools
@register_tool(
    name="rg_search",
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
)
def rg_search_tool(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    case_sensitive: bool = False,
) -> str:
    """Tool handler for rg_search."""
    return rg_search(pattern, path, glob, case_sensitive)


@register_tool(
    name="ast_grep_search",
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
)
def ast_grep_search_tool(
    pattern: str,
    path: str = ".",
    language: str | None = None,
) -> str:
    """Tool handler for ast_grep_search."""
    return ast_grep_search(pattern, path, language)
