from bourbon.prompt.types import PromptContext, PromptSection


async def skills_section(ctx: PromptContext) -> str:
    """Return skills catalog from SkillManager, or empty string if none."""
    if not ctx.skill_manager:
        return ""

    catalog = ctx.skill_manager.get_catalog()
    if not catalog:
        return ""

    return "\n".join(
        [
            "SKILLS",
            "======",
            "",
            "The following skills provide specialized instructions for specific tasks.",
            "When a task matches a skill's description, use the 'Skill' tool to load",
            "its full instructions before proceeding.",
            "",
            catalog,
        ]
    )


async def mcp_tools_section(ctx: PromptContext) -> str:
    """Return MCP tools listing grouped by server, or empty string if none."""
    if not ctx.mcp_manager:
        return ""

    summary = ctx.mcp_manager.get_connection_summary()
    if not summary.get("enabled") or summary.get("total_tools", 0) == 0:
        return ""

    mcp_tools = ctx.mcp_manager.list_mcp_tools()
    if not mcp_tools:
        return ""

    server_names = sorted(
        [server.name for server in ctx.mcp_manager.config.servers],
        key=len,
        reverse=True,
    )
    server_tools: dict[str, list[str]] = {}
    for tool_name in mcp_tools:
        matched_server = next(
            (server for server in server_names if tool_name.startswith(f"{server}-")),
            None,
        )
        if matched_server:
            tool = tool_name[len(matched_server) + 1 :]
            server_tools.setdefault(matched_server, []).append(tool)

    lines = [
        "MCP TOOLS",
        "=========",
        "",
        "The following external tools are available from MCP servers:",
        "",
    ]
    for server, tools in sorted(server_tools.items()):
        lines.append(f"  {server}:")
        for tool in sorted(tools):
            lines.append(f"    - {server}-{tool}")
        lines.append("")
    lines.append("Use these tools just like any other tool.")
    return "\n".join(lines)


DYNAMIC_SECTIONS: list[PromptSection] = [
    PromptSection(name="skills", order=60, content=skills_section),
    PromptSection(name="mcp_tools", order=70, content=mcp_tools_section),
]
