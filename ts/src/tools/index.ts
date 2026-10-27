import { ToolRegistry } from "./types";
import { bashTool, editTool, readTool, writeTool } from "./base";
import { astGrepTool, globTool, grepTool } from "./search";
import { todoWriteTool } from "./todo_tool";
import {
  taskCreateTool,
  taskGetTool,
  taskListTool,
  taskUpdateTool,
} from "./task_tools";
import { skillResourceTool, skillTool } from "./skill_tools";
import {
  memoryDeleteTool,
  memorySearchTool,
  memoryStatusTool,
  memoryWriteTool,
} from "./memory_tools";
import { toolSearchTool } from "./tool_search";
import { webFetchTool } from "./web";
import { csvAnalyzeTool, jsonQueryTool } from "./data";
import { docxReadTool, pdfReadTool } from "./documents";
import { agentTool, agentWaitTool } from "./agent_tool";

export function createToolRegistry(): ToolRegistry {
  const registry = new ToolRegistry();

  registry.register(bashTool);
  registry.register(readTool);
  registry.register(writeTool);
  registry.register(editTool);
  registry.register(grepTool);
  registry.register(globTool);
  registry.register(astGrepTool);
  registry.register(todoWriteTool);
  registry.register(taskCreateTool);
  registry.register(taskUpdateTool);
  registry.register(taskListTool);
  registry.register(taskGetTool);
  registry.register(skillTool);
  registry.register(skillResourceTool);
  registry.register(memorySearchTool);
  registry.register(memoryWriteTool);
  registry.register(memoryDeleteTool);
  registry.register(memoryStatusTool);
  registry.register(toolSearchTool);
  registry.register(webFetchTool);
  registry.register(csvAnalyzeTool);
  registry.register(jsonQueryTool);
  registry.register(pdfReadTool);
  registry.register(docxReadTool);
  registry.register(agentTool);
  registry.register(agentWaitTool);

  return registry;
}

export type { Tool, ToolContext, RiskLevel } from "./types";
export { ToolRegistry } from "./types";
