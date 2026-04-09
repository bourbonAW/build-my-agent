"""ToolSearch: deferred tool discovery for Bourbon agent."""

from bourbon.tools import RiskLevel, Tool, ToolContext, get_registry, register_tool


def _score(tool: Tool, tokens: list[str]) -> int:
    """Score a tool against query tokens."""
    score = 0
    name_lower = tool.name.lower()
    description_lower = tool.description.lower()
    hint_lower = (tool.search_hint or "").lower()

    for token in tokens:
        if token in name_lower:
            score += 10
        if hint_lower and token in hint_lower:
            score += 4
        if token in description_lower:
            score += 2

    return score


@register_tool(
    name="ToolSearch",
    description=(
        "Discover and load additional tools by keyword. "
        "Use when you need capabilities not in the current tool list "
        "(e.g., web fetching, CSV analysis, PDF reading)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Keywords describing the capability you need "
                    "(e.g., 'fetch web page', 'analyze csv')"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of tools to return (default: 5)",
            },
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.LOW,
    is_read_only=True,
    is_concurrency_safe=True,
    always_load=True,
    search_hint="discover find tools capabilities load enable",
)
def tool_search_handler(query: str, max_results: int = 5, *, ctx: ToolContext) -> str:
    """Discover deferred tools matching a free-text query."""
    registry = get_registry()
    deferred_tools = [tool for tool in registry.list_tools() if tool.should_defer]

    if not deferred_tools:
        return "No additional tools available."

    tokens = [token for token in query.lower().split() if len(token) > 1]
    if not tokens:
        return f"No tools found matching '{query}'"

    scores = {tool.name: _score(tool, tokens) for tool in deferred_tools}
    scored_tools = sorted(deferred_tools, key=lambda tool: scores[tool.name], reverse=True)
    matches = [tool for tool in scored_tools if scores[tool.name] > 0][:max_results]

    if ctx.on_tools_discovered and matches:
        ctx.on_tools_discovered({tool.name for tool in matches})

    if not matches:
        return f"No tools found matching '{query}'"

    lines = [f"Found {len(matches)} tool(s) matching '{query}':\n"]
    for tool in matches:
        lines.append(f"- {tool.name}: {tool.description}")
    lines.append("\nThese tools are now available for use.")
    return "\n".join(lines)
