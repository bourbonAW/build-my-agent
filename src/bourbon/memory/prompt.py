"""Prompt sections for memory anchor injection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bourbon.memory.files import _truncate_to_tokens, merge_user_md, read_file_anchor

if TYPE_CHECKING:
    from bourbon.prompt.types import PromptContext


MEMORY_ANCHOR_ORDER = 15
_AGENTS_MD_TOKEN_LIMIT = 8000


async def memory_anchors_section(ctx: "PromptContext") -> str:
    """Render AGENTS.md, USER.md, and MEMORY.md anchors into the prompt."""
    if ctx.memory_manager is None:
        return ""

    manager = ctx.memory_manager
    config = manager.config
    memory_dir = manager.get_memory_dir()
    parts: list[str] = []

    agents_content = read_file_anchor(ctx.workdir / "AGENTS.md", token_limit=_AGENTS_MD_TOKEN_LIMIT)
    if agents_content:
        parts.append(f"# Project Instructions (AGENTS.md)\n\n{agents_content}")

    user_content = merge_user_md(
        global_path=Path("~/.bourbon/USER.md").expanduser(),
        project_path=ctx.workdir / "USER.md",
    )
    if user_content:
        parts.append(
            "# User Preferences (USER.md)\n\n"
            f"{_truncate_to_tokens(user_content, config.user_md_token_limit)}"
        )

    memory_content = read_file_anchor(
        memory_dir / "MEMORY.md",
        token_limit=config.memory_md_token_limit,
    )
    if memory_content:
        parts.append(f"# Memory Index (MEMORY.md)\n\n{memory_content}")

    return "\n\n---\n\n".join(parts)
