"""Capability inference for access control."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class CapabilityType(StrEnum):
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
    "Read": CapabilityType.FILE_READ,
    "Write": CapabilityType.FILE_WRITE,
    "Edit": CapabilityType.FILE_WRITE,
    "Grep": CapabilityType.FILE_READ,
    "AstGrep": CapabilityType.FILE_READ,
    "Glob": CapabilityType.FILE_READ,
    "CsvAnalyze": CapabilityType.FILE_READ,
    "JsonQuery": CapabilityType.FILE_READ,
    "PdfRead": CapabilityType.FILE_READ,
    "DocxRead": CapabilityType.FILE_READ,
}

_SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH = {"Grep", "AstGrep"}

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
_BASH_FILE_READ_PATTERNS = (
    "cat ",
    "less ",
    "head ",
    "tail ",
    "grep ",
    "rg ",
    "sed ",
    "find ",
    "ls ",
)
_BASH_FILE_WRITE_PATTERNS = (
    # NOTE: bare ">" is a substring match, so it will flag shell arithmetic like
    # `[ $x > 0 ]` as FILE_WRITE.  This produces false positives but is acceptable
    # for Phase 1 (over-approximation of capabilities is safe; under-approximation
    # would be a security gap).  Phase 2 can switch to a real shell parser.
    ">",
    "tee ",
    "touch ",
    "mkdir ",
    "cp ",
    "mv ",
)


def infer_capabilities(
    tool_name: str,
    tool_input: object,
    base_capabilities: Sequence[CapabilityType],
) -> InferredContext:
    capabilities = list(base_capabilities)
    file_paths: list[str] = []

    if tool_name == "Bash":
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
        elif tool_name in _SEARCH_TOOLS_WITH_WORKDIR_DEFAULT_PATH:
            file_paths.append(".")
    else:
        return InferredContext(capabilities, file_paths)

    return InferredContext(_dedupe(capabilities), file_paths)


def _contains_any(value: str, patterns: Sequence[str]) -> bool:
    return any(pattern in value for pattern in patterns)


def _bash_command(tool_input: object) -> str:
    if isinstance(tool_input, Mapping):
        command = tool_input.get("command", "")
        return command if isinstance(command, str) else ""
    return ""


def _extract_path(tool_input: object) -> str | None:
    if isinstance(tool_input, Mapping):
        path = tool_input.get("path")
        if isinstance(path, str) and path:
            return path
        file_path = tool_input.get("file_path")
        if isinstance(file_path, str) and file_path:
            return file_path
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
