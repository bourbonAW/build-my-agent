import type { BourbonConfig } from "../config";
import type { TranscriptStore } from "../session/storage";
import { AsyncExecutor } from "./executor";
import { ResourceManager } from "./cleanup";
import { RunRegistry } from "./registry";
import type { AgentToolResult } from "./result";
import { finalizeAgentTool, formatNotification } from "./result";
import { SubagentSessionAdapter } from "./session_adapter";
import { AGENT_TYPE_CONFIGS, ToolFilter } from "./tools";
import type {
  AgentDefinition,
  RunStatus,
  SubagentAgent,
  SubagentMode,
  SubagentRun,
} from "./types";
import { SubagentRun as Run } from "./types";

export interface ParentAgent {
  systemPrompt?: string;
  session?: { sessionId: string };
  sessionManager?: {
    store: TranscriptStore;
    projectName: string;
  };
}

export type AgentFactory = (
  run: SubagentRun,
  agentDef: AgentDefinition,
) => SubagentAgent | Promise<SubagentAgent>;

export interface SubagentManagerOptions {
  agentFactory?: AgentFactory;
  executor?: AsyncExecutor;
  registry?: RunRegistry;
  resourceManager?: ResourceManager;
}

export class SubagentManager {
  private readonly executor: AsyncExecutor;
  private readonly registry: RunRegistry;
  private readonly resourceManager: ResourceManager;
  private readonly toolFilter = new ToolFilter();

  constructor(
    private readonly config: BourbonConfig,
    private readonly workdir: string,
    private readonly parentAgent: ParentAgent | null = null,
    private readonly options: SubagentManagerOptions = {},
  ) {
    this.executor = options.executor ?? new AsyncExecutor();
    this.registry = options.registry ?? new RunRegistry();
    this.resourceManager = options.resourceManager ?? new ResourceManager();
  }

  async spawn(
    description: string,
    prompt: string,
    options: {
      agentType?: string;
      model?: string | null;
      maxTurns?: number | null;
      runInBackground?: boolean;
      signal?: AbortSignal;
      agentFactory?: AgentFactory;
    } = {},
  ): Promise<AgentToolResult | string> {
    const agentType = options.agentType ?? "default";
    const agentDef = this.agentDefinition(agentType);
    const runInBackground = options.runInBackground ?? false;

    let mode: SubagentMode = "normal";
    let parentTaskListId: string | null = null;
    if (agentType === "teammate") {
      mode = "teammate";
      parentTaskListId = this.parentAgent?.session?.sessionId ?? null;
    } else if (runInBackground) {
      mode = "async";
    }

    const controller = new AbortController();
    if (options.signal?.aborted) {
      controller.abort();
    } else {
      options.signal?.addEventListener("abort", () => controller.abort(), { once: true });
    }

    const run = new Run(
      description,
      prompt,
      agentType,
      options.model ?? agentDef.model,
      options.maxTurns ?? agentDef.maxTurns,
      runInBackground,
      controller,
      mode,
      parentTaskListId,
    );
    this.registry.register(run);
    this.resourceManager.register(run);

    const factory = options.agentFactory ?? this.options.agentFactory;
    if (runInBackground) {
      this.executor
        .submit(run.runId, () => this.runLifecycle(run, agentDef, factory))
        .catch(() => undefined);
      return run.runId;
    }
    return this.runLifecycle(run, agentDef, factory);
  }

  getRun(runId: string): SubagentRun | undefined {
    return this.registry.get(runId);
  }

  listRuns(filter: { status?: RunStatus; agentType?: string } = {}): SubagentRun[] {
    return this.registry.list(filter);
  }

  killRun(runId: string): string {
    const run = this.registry.get(runId);
    if (!run) return `Run not found: ${runId}`;
    run.abortController.abort();
    run.status = "killed";
    return `Stopped run: ${runId}`;
  }

  stopRun(runId: string): string {
    return this.killRun(runId);
  }

  getRunOutput(runId: string): string {
    const run = this.registry.get(runId);
    if (!run) return `Run not found: ${runId}`;
    if (run.result !== null) return run.result;
    if (run.error !== null) return `Error: ${run.error}`;
    return `Run ${runId} is ${run.status}.`;
  }

  async waitForRuns(
    runIds: string[] | null = null,
    timeoutSeconds?: number | null,
  ): Promise<string> {
    let runs: Array<SubagentRun | undefined>;
    if (runIds?.length) {
      runs = runIds.map((runId) => this.registry.get(runId));
    } else {
      runs = this.registry
        .list()
        .filter(
          (run) => run.isAsync && (run.status === "pending" || run.status === "running"),
        );
    }

    if (!runs.length) return "No active background runs.";

    const outputs: string[] = [];
    for (const run of runs) {
      if (!run) {
        outputs.push("Run not found.");
        continue;
      }
      const outcome = await this.executor.wait(run.runId, timeoutSeconds);
      const header = `Run ${run.runId} [${run.status}] ${run.description} (${run.agentType})`;
      const output = this.getRunOutput(run.runId);
      outputs.push(
        outcome === "timeout" && timeoutSeconds != null
          ? `${header}\nTimed out waiting after ${timeoutSeconds}s.\n${output}`
          : `${header}\n${output}`,
      );
    }
    return outputs.join("\n\n");
  }

  renderRunList(): string {
    const runs = this.registry.list();
    if (!runs.length) return "No runtime jobs.";
    return runs
      .map(
        (run) =>
          `${run.runId} [${run.status}] ${run.description} (${run.agentType})`,
      )
      .join("\n");
  }

  shutdown(): void {
    this.executor.shutdown();
  }

  private agentDefinition(agentType: string): AgentDefinition {
    const definition = AGENT_TYPE_CONFIGS[agentType];
    if (!definition) {
      throw new Error(
        `Unknown subagent type '${agentType}'. Known types: ${Object.keys(AGENT_TYPE_CONFIGS)
          .sort()
          .join(", ")}`,
      );
    }
    return definition;
  }

  private async runLifecycle(
    run: SubagentRun,
    agentDef: AgentDefinition,
    factory?: AgentFactory,
  ): Promise<AgentToolResult> {
    const startedAt = Date.now();
    this.registry.updateStatus(run.runId, "running");

    try {
      const subagent = await this.createSubagent(run, agentDef, factory);
      run.subagent = subagent;
      this.configureRuntime(subagent, run, agentDef);

      const finalContent = await subagent.run(run.prompt, run.abortController.signal);
      this.copyUsage(subagent, run);

      const result = finalizeAgentTool(run, finalContent, startedAt);
      run.result = result.content;
      run.status = run.abortController.signal.aborted ? "killed" : "completed";
      if (run.status === "completed") {
        this.registry.complete(run.runId, result.content);
      } else {
        run.completedAt = new Date().toISOString();
      }
      return result;
    } catch (error) {
      if (run.abortController.signal.aborted) {
        run.status = "killed";
        run.completedAt = new Date().toISOString();
        return finalizeAgentTool(run, run.result ?? "Run was cancelled", startedAt);
      }
      const message = error instanceof Error ? error.message : String(error);
      this.registry.fail(run.runId, message);
      throw error;
    }
  }

  private async createSubagent(
    run: SubagentRun,
    agentDef: AgentDefinition,
    factory?: AgentFactory,
  ): Promise<SubagentAgent> {
    if (factory) return factory(run, agentDef);

    const { Agent } = await import("../agent/agent");
    const systemPrompt = this.composeSystemPrompt(agentDef);
    const session = this.createSession(run);
    const agent = new Agent({
      config: this.config,
      workdir: this.workdir,
      systemPrompt,
      ...(session ? { session } : {}),
      callbacks: {},
    });
    return agent;
  }

  private composeSystemPrompt(agentDef: AgentDefinition): string | undefined {
    const parentPrompt = this.parentAgent?.systemPrompt;
    if (agentDef.systemPromptSuffix) {
      return parentPrompt
        ? `${parentPrompt}\n\n${agentDef.systemPromptSuffix}`
        : agentDef.systemPromptSuffix;
    }
    return parentPrompt;
  }

  private createSession(run: SubagentRun) {
    const manager = this.parentAgent?.sessionManager;
    if (!manager) return undefined;
    return new SubagentSessionAdapter(
      manager.store,
      manager.projectName,
      this.workdir,
      run.runId,
    ).createSession();
  }

  private configureRuntime(
    subagent: SubagentAgent,
    run: SubagentRun,
    agentDef: AgentDefinition,
  ): void {
    subagent.subagentMode = run.subagentMode;
    subagent.maxToolRounds = run.maxTurns;
    subagent.subagentAgentDef = agentDef;
    subagent.taskListIdOverride = run.parentTaskListId;
    if (subagent instanceof Object) {
      subagent.toolFilter = this.toolFilter;
    }
  }

  private copyUsage(subagent: SubagentAgent, run: SubagentRun): void {
    const usage = subagent.usage ?? { inputTokens: 0, outputTokens: 0 };
    run.inputTokens = usage.inputTokens;
    run.outputTokens = usage.outputTokens;
    run.totalTokens = usage.inputTokens + usage.outputTokens;
    run.toolCallCount = subagent.toolCallCount ?? 0;
  }
}

export { formatNotification };
