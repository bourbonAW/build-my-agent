"""Todo tool registration."""

from bourbon.tools import ToolContext, register_tool


@register_tool(
    name="TodoWrite",
    description="Update the current task list for multi-step work.",
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                        "activeForm": {"type": "string"},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["items"],
    },
)
def todo_write_handler(items: list[dict], *, ctx: ToolContext) -> str:
    """Update the active agent's todo manager."""
    agent = ctx.agent
    if agent is None or getattr(agent, "todos", None) is None:
        return "Error: Todo manager unavailable"

    result = agent.todos.update(items)
    ctx.execution_markers.add("todo")
    return result
