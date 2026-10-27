import type { AgentToolResult } from "../subagent";
import { formatAgentToolResult } from "../subagent";
import type { Tool, ToolContext } from "./types";

function managerFor(ctx: ToolContext) {
  const manager = ctx.agent?.subagentManager;
  if (!manager) throw new Error("Agent tool unavailable: no subagent manager in context");
  return manager;
}

export const agentTool: Tool = {
  name: "Agent",
  description:
    "Start a focused subagent run for isolated work. For parallel work whose results are needed before continuing, issue multiple foreground Agent tool calls in the same tool round; Bourbon waits for all results before the next reasoning step. Use background mode only for independent work.",
  inputSchema: {
    type: "object",
    properties: {
      description: { type: "string", description: "Short run description" },
      prompt: { type: "string", description: "Complete instructions" },
      subagent_type: {
        type: "string",
        enum: ["default", "coder", "explore", "plan", "quick_task", "teammate"],
        default: "default",
        description:
          "Subagent profile. explore is restricted to read-only tools and cannot write files, execute code, or call MCP tools.",
      },
      model: { type: ["string", "null"] },
      max_turns: { type: ["integer", "null"] },
      run_in_background: {
        type: "boolean",
        default: false,
        description:
          "When true, return a run_id immediately instead of waiting. Use only when the parent can proceed without the result; otherwise leave false.",
      },
    },
    required: ["description", "prompt"],
  },
  riskLevel: "medium",
  isConcurrencySafe: () => true,
  run: async (input, ctx) => {
    try {
      const manager = managerFor(ctx);
      const result = await manager.spawn(
        String(input.description ?? ""),
        String(input.prompt ?? ""),
        {
          agentType: typeof input.subagent_type === "string" ? input.subagent_type : "default",
          model: typeof input.model === "string" ? input.model : null,
          maxTurns: typeof input.max_turns === "number" ? input.max_turns : null,
          runInBackground: input.run_in_background === true,
          ...(ctx.signal ? { signal: ctx.signal } : {}),
        },
      );

      if (typeof result === "string") {
        return `Started background run: ${result}\nUse AgentWait with run_ids ["${result}"] if you need the result before continuing.`;
      }
      return formatAgentToolResult(result as AgentToolResult);
    } catch (error) {
      return `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};

export const agentWaitTool: Tool = {
  name: "AgentWait",
  description:
    "Wait for one or more background Agent runs to finish and return their outputs. Use this after run_in_background=true when the parent needs those results before continuing.",
  inputSchema: {
    type: "object",
    properties: {
      run_ids: {
        type: "array",
        items: { type: "string" },
        description: "Background run IDs returned by Agent. If omitted, wait for all active background runs.",
      },
      timeout_seconds: {
        type: ["number", "null"],
        default: null,
        description: "Maximum seconds to wait for each run.",
      },
    },
  },
  riskLevel: "low",
  isConcurrencySafe: () => false,
  run: async (input, ctx) => {
    try {
      const manager = managerFor(ctx);
      const runIds = Array.isArray(input.run_ids) ? input.run_ids.map(String) : null;
      const timeout =
        typeof input.timeout_seconds === "number" ? input.timeout_seconds : null;
      return await manager.waitForRuns(runIds, timeout);
    } catch (error) {
      return `Error: ${error instanceof Error ? error.message : String(error)}`;
    }
  },
};
