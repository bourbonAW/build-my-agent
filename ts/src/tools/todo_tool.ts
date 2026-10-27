import type { Tool } from "./types";

export const todoWriteTool: Tool = {
  name: "TodoWrite",
  description: "Update the current task list for multi-step work.",
  inputSchema: {
    type: "object",
    properties: {
      items: {
        type: "array",
        items: {
          type: "object",
          properties: {
            content: { type: "string" },
            status: {
              type: "string",
              enum: ["pending", "in_progress", "completed"],
            },
            activeForm: { type: "string" },
          },
          required: ["content", "status"],
        },
      },
    },
    required: ["items"],
  },
  riskLevel: "low",
  isConcurrencySafe: () => false,
  run: async (input, ctx) => {
    const agent = ctx.agent;
    if (!agent?.todos) return "Error: Todo manager unavailable";
    const items = Array.isArray(input.items)
      ? (input.items as Array<Record<string, unknown>>)
      : [];
    const result = agent.todos.update(items);
    ctx.executionMarkers?.add("todo");
    return result;
  },
};
