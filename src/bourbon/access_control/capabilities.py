"""Capability inference for access control."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from collections.abc import Mapping, Sequence


class CapabilityType(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    EXEC = "exec"
    NET = "net"
    SKILL = "skill"
    MCP = "mcp"


@dataclass
class InferredContext:
    capabilities: list[CapabilityType] = field(default_factory=list)
    file_paths: list[str] = field(default_factory=list)


_FILE_TOOL_CAPABILITIES = {
    "read_file": CapabilityType.FILE_READ,
    "write_file": CapabilityType.FILE_WRITE,
    "edit_file": CapabilityType.FILE_WRITE,
}

_BASH_NET_PATTERNS = (
    "curl ",
    "wget ",
    "http://",
    "https://",
    "pip install ",
    "pip3 install ",
    "git clone ",
    "git pull ",
    "git push ",
)
_BASH_FILE_READ_PATTERNS = ("cat ", "less ", "head ", "tail ", "grep ", "rg ", "sed ", "find ", "ls ")
_BASH_FILE_WRITE_PATTERNS = (">", "tee ", "touch ", "mkdir ", "cp ", "mv ")


def infer_capabilities(
    tool_name: str,
    tool_input: object,
    base_capabilities: Sequence[CapabilityType],
) -> InferredContext:
    capabilities = list(base_capabilities)
    file_paths: list[str] = []

    if tool_name == "bash":
        command = _bash_command(tool_input)
        if _contains_any(command, _BASH_NET_PATTERNS):
            capabilities.append(CapabilityType.NET)
        if _contains_any(command, _BASH_FILE_READ_PATTERNS):
            capabilities.append(CapabilityType.FILE_READ)
        if _contains_any(command, _BASH_FILE_WRITE_PATTERNS):
            capabilities.append(CapabilityType.FILE_WRITE)
    elif tool_name in _FILE_TOOL_CAPABILITIES:
        capabilities.append(_FILE_TOOL_CAPABILITIES[tool_name])
        path = _extract_path(tool_input)
        if path is not None:
            file_paths.append(path)

    return InferredContext(_dedupe(capabilities), file_paths)


def _contains_any(value: str, patterns: Sequence[str]) -> bool:
    return any(pattern in value for pattern in patterns)


def _bash_command(tool_input: object) -> str:
    if isinstance(tool_input, Mapping):
        command = tool_input.get("command", "")
        return command if isinstance(command, str) else ""
    if isinstance(tool_input, str):
        return tool_input
    return ""


def _extract_path(tool_input: object) -> str | None:
    if isinstance(tool_input, Mapping):
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            return path
        return None
    if isinstance(tool_input, str) and tool_input:
        return tool_input
    return None


def _dedupe(values: Sequence[CapabilityType]) -> list[CapabilityType]:
    seen: set[CapabilityType] = set()
    deduped: list[CapabilityType] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
