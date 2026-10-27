import { TASK_V2_TOOLS } from "../tasks/constants";
import type { AgentDefinition, SubagentMode } from "./types";

export const ALL_AGENT_DISALLOWED_TOOLS = new Set([
  "Agent",
  "AgentWait",
  "TodoWrite",
  "compress",
]);

export const READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "AstGrep", "WebFetch"];

export const AGENT_TYPE_CONFIGS: Record<string, AgentDefinition> = {
  default: {
    agentType: "default",
    description: "General purpose agent for most tasks",
    allowedTools: null,
    disallowedTools: [],
    maxTurns: 50,
    model: null,
    systemPromptSuffix: null,
  },
  coder: {
    agentType: "coder",
    description: "Code refactoring and implementation specialist",
    allowedTools: null,
    disallowedTools: [],
    maxTurns: 100,
    model: null,
    systemPromptSuffix: "Focus on code quality and test coverage.",
  },
  explore: {
    agentType: "explore",
    description: "Read-only codebase exploration",
    allowedTools: [...READ_ONLY_TOOLS],
    disallowedTools: [],
    maxTurns: 30,
    model: null,
    systemPromptSuffix: "You are in READ-ONLY mode. Do not modify files.",
  },
  plan: {
    agentType: "plan",
    description: "Architecture and design planning",
    allowedTools: [...READ_ONLY_TOOLS],
    disallowedTools: [],
    maxTurns: 30,
    model: null,
    systemPromptSuffix: "Focus on architecture, tradeoffs, and implementation planning.",
  },
  quick_task: {
    agentType: "quick_task",
    description: "Fast execution for simple, bounded tasks",
    allowedTools: null,
    disallowedTools: [],
    maxTurns: 20,
    model: null,
    systemPromptSuffix: null,
  },
  teammate: {
    agentType: "teammate",
    description: "In-process teammate for task claiming and parallel execution",
    allowedTools: null,
    disallowedTools: [],
    maxTurns: 100,
    model: null,
    systemPromptSuffix: null,
  },
};

export class ToolFilter {
  isAllowed(
    toolName: string,
    agentDef: AgentDefinition,
    subagentMode: SubagentMode = "normal",
  ): boolean {
    if (ALL_AGENT_DISALLOWED_TOOLS.has(toolName)) return false;
    if (agentDef.disallowedTools.includes(toolName)) return false;
    if (subagentMode === "async" && TASK_V2_TOOLS.has(toolName)) return false;
    if (subagentMode === "teammate" && TASK_V2_TOOLS.has(toolName)) return true;
    if (agentDef.allowedTools !== null) return agentDef.allowedTools.includes(toolName);
    return true;
  }

  filterTools<T extends { name: string }>(
    tools: T[],
    agentDef: AgentDefinition,
    subagentMode: SubagentMode = "normal",
  ): T[] {
    return tools.filter((tool) => this.isAllowed(tool.name, agentDef, subagentMode));
  }
}
