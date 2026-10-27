import type { Tool } from "./types";
import { requireString } from "./types";

function scoreTool(
  tool: Tool,
  tokens: string[],
): number {
  let score = 0;
  const name = tool.name.toLowerCase();
  const description = tool.description.toLowerCase();
  const hint = (tool.searchHint ?? "").toLowerCase();

  for (const token of tokens) {
    if (name.includes(token)) score += 10;
    if (hint && hint.includes(token)) score += 4;
    if (description.includes(token)) score += 2;
  }
  return score;
}

export const toolSearchTool: Tool = {
  name: "ToolSearch",
  description:
    "Discover and load additional tools by keyword. Use when you need capabilities not in the current tool list (e.g., web fetching, CSV analysis, PDF reading).",
  inputSchema: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description: "Keywords describing the capability you need (e.g., 'fetch web page', 'analyze csv')",
      },
      max_results: {
        type: "integer",
        description: "Maximum number of tools to return (default: 5)",
      },
    },
    required: ["query"],
  },
  riskLevel: "low",
  isReadOnly: true,
  isConcurrencySafe: () => true,
  searchHint: "discover find tools capabilities load enable",
  run: async (input, ctx) => {
    const registry = ctx.registry;
    if (!registry) return "No additional tools available.";

    const deferred = registry.listTools().filter((tool) => tool.shouldDefer);
    if (!deferred.length) return "No additional tools available.";

    const query = requireString(input, "query");
    const tokens = query
      .toLowerCase()
      .split(/\s+/)
      .filter((token) => token.length > 1);
    if (!tokens.length) return `No tools found matching '${query}'`;

    const maxResults = typeof input.max_results === "number" ? input.max_results : 5;
    const matches = deferred
      .map((tool) => ({ tool, score: scoreTool(tool, tokens) }))
      .filter((entry) => entry.score > 0)
      .sort((left, right) => right.score - left.score)
      .slice(0, maxResults)
      .map((entry) => entry.tool);

    if (!matches.length) return `No tools found matching '${query}'`;
    ctx.onToolsDiscovered?.(new Set(matches.map((tool) => tool.name)));

    const lines = [`Found ${matches.length} tool(s) matching '${query}':\n`];
    for (const tool of matches) lines.push(`- ${tool.name}: ${tool.description}`);
    lines.push("\nThese tools are now available for use.");
    return lines.join("\n");
  },
};
