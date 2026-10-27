import { MEMORY_ANCHOR_ORDER, memoryAnchorsSection } from "../memory/prompt";
import type { PromptContext, PromptSection } from "./types";

export function skillsSection(ctx: PromptContext): string {
  const catalog = ctx.skillManager?.getCatalog();
  if (!catalog) return "";

  return [
    "SKILLS",
    "======",
    "",
    "The following skills provide specialized instructions for specific tasks.",
    "When a task matches a skill's description, use the 'Skill' tool to load",
    "its full instructions before proceeding.",
    "",
    catalog,
  ].join("\n");
}

export function mcpToolsSection(ctx: PromptContext): string {
  const manager = ctx.mcpManager;
  if (!manager) return "";

  const summary = manager.getConnectionSummary();
  if (!summary.enabled || summary.totalTools === 0) return "";

  const tools = manager.listMcpTools();
  if (!tools.length) return "";

  const serverNames = [...manager.serverNames()].sort((left, right) => right.length - left.length);
  const grouped = new Map<string, string[]>();

  for (const toolName of tools) {
    const server = serverNames.find((name) => toolName.startsWith(`${name}-`));
    if (!server) continue;
    const tool = toolName.slice(server.length + 1);
    const bucket = grouped.get(server) ?? [];
    bucket.push(tool);
    grouped.set(server, bucket);
  }

  const lines = [
    "MCP TOOLS",
    "=========",
    "",
    "The following external tools are available from MCP servers:",
    "",
  ];
  for (const [server, serverTools] of [...grouped.entries()].sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    lines.push(`  ${server}:`);
    for (const tool of serverTools.sort()) {
      lines.push(`    - ${server}-${tool}`);
    }
    lines.push("");
  }
  lines.push("Use these tools just like any other tool.");
  return lines.join("\n");
}

export const DYNAMIC_SECTIONS: PromptSection[] = [
  { name: "memory_anchors", order: MEMORY_ANCHOR_ORDER, content: memoryAnchorsSection },
  { name: "skills", order: 60, content: skillsSection },
  { name: "mcp_tools", order: 70, content: mcpToolsSection },
];
