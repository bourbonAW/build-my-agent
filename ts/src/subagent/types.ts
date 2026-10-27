import { randomUUID } from "node:crypto";

export type SubagentMode = "normal" | "teammate" | "async";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "killed";

export interface AgentDefinition {
  agentType: string;
  description: string;
  allowedTools: string[] | null;
  disallowedTools: string[];
  maxTurns: number;
  model: string | null;
  systemPromptSuffix: string | null;
}

export interface SubagentAgent {
  run(prompt: string, signal?: AbortSignal): Promise<string>;
  usage?: { inputTokens: number; outputTokens: number };
  toolCallCount?: number;
  session?: { sessionId: string };
  subagentMode?: SubagentMode;
  maxToolRounds?: number;
  subagentAgentDef?: AgentDefinition | null;
  toolFilter?: unknown;
  taskListIdOverride?: string | null;
  shutdownMCP?(): Promise<void> | void;
}

export class SubagentRun {
  readonly runId = randomUUID().slice(0, 8);
  status: RunStatus = "pending";
  readonly createdAt = new Date().toISOString();
  startedAt: string | null = null;
  completedAt: string | null = null;
  result: string | null = null;
  error: string | null = null;
  toolCallCount = 0;
  totalTokens = 0;
  inputTokens = 0;
  outputTokens = 0;
  currentActivity: string | null = null;
  subagent: SubagentAgent | null = null;

  constructor(
    readonly description: string,
    readonly prompt: string,
    readonly agentType: string,
    readonly model: string | null,
    readonly maxTurns: number,
    readonly isAsync: boolean,
    readonly abortController: AbortController,
    readonly subagentMode: SubagentMode,
    readonly parentTaskListId: string | null,
  ) {}

  toDict(): Record<string, unknown> {
    const description =
      this.description.length > 50
        ? `${this.description.slice(0, 50)}...`
        : this.description;
    return {
      run_id: this.runId,
      description,
      agent_type: this.agentType,
      status: this.status,
      is_async: this.isAsync,
      created_at: this.createdAt,
      completed_at: this.completedAt,
      tool_calls: this.toolCallCount,
    };
  }
}
