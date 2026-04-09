"""Tool-aware session approval matching."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _resolve_path(path: str, workdir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (workdir / candidate).resolve()


def _normalized_command_prefix(command: str) -> str:
    tokens = command.strip().split()
    if len(tokens) >= 2:
        return " ".join(tokens[:2])
    return command.strip()


def build_match_candidate(
    tool_name: str,
    tool_input: dict[str, Any],
    workdir: Path,
) -> dict[str, Any]:
    if tool_name == "Bash":
        return {
            "tool_name": tool_name,
            "kind": "command_prefix",
            "value": _normalized_command_prefix(tool_input.get("command", "")),
        }

    if tool_name == "Write":
        resolved = _resolve_path(tool_input["path"], workdir)
        kind = "exact_file" if resolved.exists() else "parent_dir"
        value = str(resolved if kind == "exact_file" else resolved.parent)
        return {"tool_name": tool_name, "kind": kind, "value": value}

    if tool_name == "Edit":
        return {
            "tool_name": tool_name,
            "kind": "exact_file",
            "value": str(_resolve_path(tool_input["path"], workdir)),
        }

    key_fields = sorted(
        (key, repr(value))
        for key, value in tool_input.items()
        if key in {"path", "command", "url"}
    )
    return {
        "tool_name": tool_name,
        "kind": "fallback",
        "value": tuple(key_fields),
    }


def session_rule_matches(
    candidate: dict[str, Any],
    tool_name: str,
    tool_input: dict[str, Any],
    workdir: Path,
) -> bool:
    return candidate == build_match_candidate(tool_name, tool_input, workdir)
