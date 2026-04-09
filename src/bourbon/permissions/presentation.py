"""Builders for user-facing permission request content."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from bourbon.permissions.matching import build_match_candidate
from bourbon.permissions.runtime import PermissionDecision, PermissionRequest


def build_permission_request(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_use_id: str,
    decision: PermissionDecision,
    workdir: Path,
) -> PermissionRequest:
    if tool_name == "Bash":
        title = "Bash command"
        description = tool_input.get("command", "")
    elif tool_name == "Write":
        title = "Write file"
        description = f"{tool_input.get('path')} ({len(tool_input.get('content', ''))} chars)"
    elif tool_name == "Edit":
        title = "Edit file"
        description = tool_input.get("path", "")
    else:
        title = f"{tool_name} request"
        description = repr(tool_input)

    return PermissionRequest(
        request_id=f"perm-{uuid.uuid4().hex[:8]}",
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        tool_input=tool_input,
        title=title,
        description=description,
        reason=decision.reason,
        match_candidate=build_match_candidate(tool_name, tool_input, workdir),
    )
