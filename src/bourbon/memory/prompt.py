"""Prompt sections for memory anchor injection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bourbon.memory.files import read_file_anchor, render_merged_user_md_for_prompt

if TYPE_CHECKING:
    from bourbon.prompt.types import PromptContext


MEMORY_ANCHOR_ORDER = 15
_AGENTS_MD_TOKEN_LIMIT = 8000


async def memory_anchors_section(ctx: PromptContext) -> str:
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

    user_content = render_merged_user_md_for_prompt(
        global_path=Path("~/.bourbon/USER.md").expanduser(),
        project_path=ctx.workdir / "USER.md",
        token_limit=config.user_md_token_limit,
    )
    if user_content:
        parts.append(f"# User Preferences (USER.md)\n\n{user_content}")

    memory_content = read_file_anchor(
        memory_dir / "MEMORY.md",
        token_limit=config.memory_md_token_limit,
    )
    if memory_content:
        parts.append(f"# Memory Index (MEMORY.md)\n\n{memory_content}")

    return "\n\n---\n\n".join(parts)
