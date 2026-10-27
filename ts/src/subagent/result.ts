import type { SubagentRun } from "./types";

export interface AgentToolResult {
  runId: string;
  agentType: string;
  content: string;
  totalDurationMs: number;
  totalTokens: number;
  totalToolCalls: number;
  description: string | null;
  usage: { inputTokens: number; outputTokens: number };
}

export function finalizeAgentTool(
  run: SubagentRun,
  finalContent: string,
  startTimeMs: number,
): AgentToolResult {
  return {
    runId: run.runId,
    agentType: run.agentType,
    description: run.description,
    content: finalContent,
    totalDurationMs: Date.now() - startTimeMs,
    totalTokens: run.totalTokens,
    totalToolCalls: run.toolCallCount,
    usage: {
      inputTokens: run.inputTokens,
      outputTokens: run.outputTokens,
    },
  };
}

export function formatAgentToolResult(result: AgentToolResult): string {
  const duration = result.totalDurationMs / 1000;
  return `Subagent completed in ${duration.toFixed(1)}s
Tokens: ${result.totalTokens}, Tool calls: ${result.totalToolCalls}

Result:
${result.content}`;
}

export function formatNotification(result: AgentToolResult): string {
  const preview =
    result.content.length > 500 ? `${result.content.slice(0, 500)}...` : result.content;
  return `[Run ${result.runId}] Completed

Description: ${result.description ?? result.runId}
Status: Completed
Duration: ${(result.totalDurationMs / 1000).toFixed(1)}s
Tokens: ${result.totalTokens}
Tool Calls: ${result.totalToolCalls}

Result:
${preview}

Use AgentWait with run_ids ["${result.runId}"] for full details.
`;
}
