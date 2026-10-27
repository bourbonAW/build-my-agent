import { homedir } from "node:os";
import { basename, join, resolve } from "node:path";
import { inferCapabilities } from "../access_control/capabilities";
import { PolicyEngine, type PolicyDecision } from "../access_control/policy";
import { AuditEvent, AuditLogger } from "../audit";
import { activeProvider } from "../config";
import type { BourbonConfig } from "../config";
import { debugLog, promptFields } from "../debug";
import type {
  AssistantBlock,
  LLMClient,
  Message,
  TextBlock,
  ToolDefinition,
  ToolResultBlock,
  ToolUseBlock,
} from "../llm";
import { createLLMClient, isToolUse } from "../llm";
import { MCPManager } from "../mcp";
import type { MemoryActor, MemoryManager } from "../memory";
import { MemoryManager as MemoryManagerImpl, sanitizeProjectKey } from "../memory";
import { ObservabilityManager } from "../observability/manager";
import type { BourbonTracer } from "../observability/tracer";
import { ContextInjector, buildSystemPrompt } from "../prompt";
import type { PromptContext } from "../prompt/types";
import type {
  PermissionChoice,
  PermissionDecision,
  PermissionRequest,
} from "../permissions/runtime";
import { SessionPermissionStore, type SuspendedToolRound } from "../permissions/runtime";
import { buildPermissionRequest } from "../permissions/presentation";
import { SandboxManager } from "../sandbox";
import { createTranscriptMessage } from "../session/types";
import type { Session } from "../session/manager";
import { SessionManager } from "../session/manager";
import { TranscriptStore } from "../session/storage";
import { SkillManager } from "../skills";
import { SubagentManager } from "../subagent";
import { TASK_V2_TOOLS } from "../tasks/constants";
import { TaskService } from "../tasks/service";
import { TaskStore } from "../tasks/store";
import type { AgentDefinition, SubagentMode } from "../subagent";
import type { ToolFilter } from "../subagent";
import { createToolRegistry } from "../tools";
import type { Tool, ToolContext, ToolRegistry } from "../tools";
import { truncate } from "../tools/base";
import { TodoManager } from "../todos";

const MAX_TOOL_FAILURES = 3;
const MAX_TOOL_RESULT_CHARS = 50_000;
const TASK_NUDGE_THRESHOLD = 10;

export interface AgentCallbacks {
  onText?: (text: string) => void;
  onToolStart?: (name: string, input: Record<string, unknown>) => void;
  onToolEnd?: (name: string, output: string, isError: boolean) => void;
}

export interface AgentOptions {
  config: BourbonConfig;
  workdir: string;
  llm?: LLMClient;
  registry?: ToolRegistry;
  callbacks?: AgentCallbacks;
  systemPrompt?: string;
  session?: Session;
  sessionId?: string;
  resumeLast?: boolean;
  sessionDir?: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
}

interface PreflightResult {
  kind: "execute" | "result" | "ask";
  tool?: Tool;
  result?: ToolResultBlock;
  decision?: PermissionDecision;
}

export class Agent {
  readonly config: BourbonConfig;
  readonly workdir: string;
  readonly callbacks: AgentCallbacks;
  readonly registry: ToolRegistry;
  readonly todos = new TodoManager();
  readonly skills: SkillManager;
  readonly mcp: MCPManager;
  readonly audit: AuditLogger;
  readonly sandbox: SandboxManager;
  readonly accessController: PolicyEngine;
  readonly session: Session;
  readonly sessionManager: SessionManager;
  readonly subagentManager: SubagentManager;
  readonly usage: TokenUsage = { inputTokens: 0, outputTokens: 0 };
  toolFilter: ToolFilter | null = null;
  systemPrompt = "";
  maxToolRounds: number;
  subagentMode: SubagentMode = "normal";
  subagentAgentDef: AgentDefinition | null = null;
  taskListIdOverride: string | null = null;
  toolCallCount = 0;

  private readonly llm: LLMClient;
  private readonly sessionPermissions = new SessionPermissionStore();
  private readonly discoveredTools = new Set<string>();
  private readonly consecutiveFailures = new Map<string, number>();
  private readonly contextInjector = new ContextInjector();
  private readonly observability: ObservabilityManager;
  private readonly tracer: BourbonTracer;
  private readonly memoryManager: MemoryManager | null;
  private readonly memoryActor: MemoryActor;
  private readonly promptContext: PromptContext;
  private readonly customSystemPrompt: string | undefined;
  private activePermissionRequestValue: PermissionRequest | null = null;
  private suspendedToolRoundValue: SuspendedToolRound | null = null;
  private roundsWithoutTask = 0;

  constructor(options: AgentOptions) {
    this.config = options.config;
    this.workdir = resolve(options.workdir);
    this.callbacks = options.callbacks ?? {};
    this.customSystemPrompt = options.systemPrompt;
    this.systemPrompt = options.systemPrompt ?? "";
    this.maxToolRounds = options.config.ui.maxToolRounds;

    const provider = activeProvider(options.config);
    if (!provider.apiKey) {
      throw new Error(`No API key configured for provider '${options.config.defaultProvider}'`);
    }
    this.llm = options.llm ?? createLLMClient(options.config);
    this.registry =
      options.registry ?? createToolRegistry();

    this.skills = new SkillManager(this.workdir);
    this.mcp = new MCPManager(options.config.mcp, this.registry);

    this.audit = new AuditLogger(
      expandHome(options.config.audit.logDir),
      options.config.audit.enabled,
    );
    this.accessController = new PolicyEngine(
      options.config.accessControl.defaultAction,
      options.config.accessControl,
      this.workdir,
    );
    this.sandbox = new SandboxManager(options.config.sandbox, this.workdir, this.audit);

    this.memoryManager = options.config.memory.enabled
      ? new MemoryManagerImpl(
          options.config.memory,
          sanitizeProjectKey(this.workdir),
          this.workdir,
          this.audit,
        )
      : null;
    this.memoryActor = { kind: "agent" };

    const sessionDir = options.sessionDir ?? join(homedir(), ".bourbon", "sessions");
    this.sessionManager = new SessionManager(
      new TranscriptStore(sessionDir),
      basename(this.workdir) || "default",
      this.workdir,
      options.config.ui.tokenThreshold,
    );

    if (options.session) {
      this.session = options.session;
    } else if (options.sessionId) {
      this.session =
        this.sessionManager.resumeSession(options.sessionId) ??
        this.sessionManager.createSession(options.sessionId);
    } else if (options.resumeLast) {
      this.session =
        this.sessionManager.resumeLatest() ?? this.sessionManager.createSession();
    } else {
      this.session = this.sessionManager.createSession();
    }

    this.promptContext = {
      workdir: this.workdir,
      skillManager: this.skills,
      mcpManager: this.mcp,
      ...(this.memoryManager ? { memoryManager: this.memoryManager } : {}),
      memoryConfig: {
        memoryMdTokenLimit: options.config.memory.memoryMdTokenLimit,
        userMdTokenLimit: options.config.memory.userMdTokenLimit,
      },
    };

    if (this.memoryManager) {
      this.memoryActor = {
        kind: "agent",
        sessionId: this.session.sessionId,
      };
    }

    this.observability = new ObservabilityManager(options.config.observability);
    this.tracer = this.observability.getTracer();

    this.subagentManager = new SubagentManager(
      options.config,
      this.workdir,
      this,
    );
  }

  get model(): string {
    return this.llm.model;
  }

  get totalTokens(): number {
    return this.usage.inputTokens + this.usage.outputTokens;
  }

  get history(): readonly Message[] {
    return this.session.getMessagesForLlm();
  }

  get activePermissionRequest(): PermissionRequest | null {
    return this.activePermissionRequestValue;
  }

  get suspendedToolRound(): SuspendedToolRound | null {
    return this.suspendedToolRoundValue;
  }

  async initializeMCP(): Promise<Record<string, unknown>> {
    const results = await this.mcp.connectAll();
    return results as unknown as Record<string, unknown>;
  }

  async shutdownMCP(): Promise<void> {
    await this.mcp.disconnectAll();
  }

  async shutdown(): Promise<void> {
    await this.shutdownMCP();
    this.subagentManager.shutdown();
    await this.observability.shutdown();
  }

  clearHistory(): void {
    this.session.chain.clear();
    this.session.contextManager.resetTokenEstimate();
    this.session.metadata.messageCount = 0;
    this.session.save();
  }

  getSessionTokens(): number {
    return this.session.contextManager.estimateTokens();
  }

  getTodos(): string {
    return this.todos.render();
  }

  manualCompact() {
    return this.session.maybeCompact("manual");
  }

  async run(userInput: string, signal?: AbortSignal): Promise<string> {
    const span = this.tracer.startAgentStep(this.workdir, "run", null, null, userInput);
    try {
      const response = await this.runImpl(userInput, signal);
      this.tracer.recordAgentOutput(span, response);
      await this.observability.forceFlush();
      return response;
    } catch (error) {
      this.tracer.recordError(span, error);
      throw error;
    } finally {
      this.tracer.end(span);
    }
  }

  async step(userInput: string, signal?: AbortSignal): Promise<string> {
    return this.run(userInput, signal);
  }

  private async runImpl(userInput: string, signal?: AbortSignal): Promise<string> {
    await this.ensureSystemPrompt();

    if (this.activePermissionRequestValue) {
      return "Error: Permission request pending. Resolve it before sending new input.";
    }

    const enriched = await this.contextInjector.inject(userInput, this.promptContext);
    const userMessage = createTranscriptMessage("user", [
      { type: "text", text: enriched },
    ]);
    this.session.addMessage(userMessage);
    this.session.save();

    this.session.contextManager.microcompact();
    this.session.maybeCompact("auto_threshold");

    return this.conversationLoop(signal);
  }

  async resumePermission(
    choice: PermissionChoice,
    signal?: AbortSignal,
  ): Promise<string> {
    const request = this.activePermissionRequestValue;
    const suspended = this.suspendedToolRoundValue;
    if (!request || !suspended) {
      return "Error: No permission request pending.";
    }

    this.activePermissionRequestValue = null;
    this.suspendedToolRoundValue = null;

    if (choice === "allow_session" && request.matchCandidate) {
      this.sessionPermissions.add(request.matchCandidate);
    }

    const firstResult: ToolResultBlock =
      choice === "reject"
        ? {
            type: "tool_result",
            tool_use_id: request.toolUseId,
            content: `User rejected: ${request.reason}`,
            is_error: true,
          }
        : await this.runToolBlock(
            request.toolName,
            request.toolInput,
            request.toolUseId,
            signal,
          );

    const completed = [...suspended.completedResults, firstResult] as ToolResultBlock[];
    const rest = await this.executeToolUses(
      suspended.toolUseBlocks as ToolUseBlock[],
      suspended.nextToolIndex + 1,
      completed,
      signal,
    );

    if (rest.suspended) return "";

    this.addToolResults(
      this.withTaskNudge(rest.completed, suspended.toolUseBlocks as ToolUseBlock[]),
    );
    return this.conversationLoop(signal);
  }

  private async ensureSystemPrompt(): Promise<void> {
    if (this.customSystemPrompt !== undefined) {
      this.systemPrompt = this.customSystemPrompt;
      return;
    }
    this.systemPrompt = await buildSystemPrompt(this.promptContext);
  }

  private async conversationLoop(signal?: AbortSignal): Promise<string> {
    let accumulated = "";

    for (let round = 0; round < this.maxToolRounds; round += 1) {
      const toolDefinitions = this.toolDefinitions();
      let roundText = "";
      const messages = this.session.getMessagesForLlm();

      debugLog("agent.stream.llm_call.start", {
        tool_round: round,
        message_count: messages.length,
        tool_definition_count: toolDefinitions.length,
        ...promptFields(messages, this.systemPrompt, toolDefinitions),
      });

      const response = await this.callLlm(
        messages,
        toolDefinitions,
        (chunk) => {
          roundText += chunk;
          accumulated += chunk;
          this.emitText(chunk);
        },
        signal,
      );

      const content = response.content;
      if (content.length) {
        const assistantMessage = createTranscriptMessage("assistant", content, {
          usage: {
            inputTokens: response.usage.inputTokens,
            outputTokens: response.usage.outputTokens,
            totalTokens: response.usage.inputTokens + response.usage.outputTokens,
          },
        });
        this.session.addMessage(assistantMessage);
        this.session.save();
      }

      const toolUses = content.filter(isToolUse);
      if (response.stopReason !== "tool_use" || !toolUses.length) {
        return accumulated;
      }

      const outcome = await this.executeToolUses(toolUses, 0, [], signal);
      if (outcome.suspended) {
        return accumulated;
      }

      this.addToolResults(this.withTaskNudge(outcome.completed, toolUses));
      if (signal?.aborted) return accumulated;
    }

    const summary = await this.forceFinalSummary(signal);
    return accumulated + summary;
  }

  private addToolResults(results: Array<ToolResultBlock | TextBlock>): void {
    if (!results.length) return;
    this.session.addMessage(createTranscriptMessage("user", results));
    this.session.save();
  }

  private withTaskNudge(
    results: ToolResultBlock[],
    toolUses: ToolUseBlock[],
  ): Array<ToolResultBlock | TextBlock> {
    if (!toolUses.length) return results;

    if (toolUses.some((block) => TASK_V2_TOOLS.has(block.name))) {
      this.roundsWithoutTask = 0;
      return results;
    }

    this.roundsWithoutTask += 1;
    if (this.roundsWithoutTask < TASK_NUDGE_THRESHOLD) return results;

    this.roundsWithoutTask = 0;
    const reminder = this.buildTaskReminder();
    return reminder ? [...results, reminder] : results;
  }

  private buildTaskReminder(): TextBlock | null {
    const storageDir = this.config.tasks.storageDir.replace(/^~(?=\/|$)/, homedir());
    const service = new TaskService(new TaskStore(storageDir));
    const taskListId =
      this.taskListIdOverride ??
      this.session.sessionId ??
      this.config.tasks.defaultListId;

    let pending;
    try {
      pending = service.listTasks(taskListId).filter((task) => task.status !== "completed");
    } catch {
      return null;
    }
    if (!pending.length) return null;

    const lines = pending
      .map(
        (task) =>
          `- [${task.status}] ${task.subject}` +
          (task.blockedBy.length ? ` (blocked by: ${task.blockedBy.join(", ")})` : ""),
      )
      .join("\n");

    return {
      type: "text",
      text: `<task_reminder>\nYou have ${pending.length} pending task(s). Please update with TaskUpdate or create with TaskCreate.\n\n${lines}\n</task_reminder>`,
    };
  }

  private async callLlm(
    messages: Message[],
    tools: ToolDefinition[],
    onText: (chunk: string) => void,
    signal?: AbortSignal,
  ) {
    const provider = activeProvider(this.config);
    const span = this.tracer.startLlmCall(
      this.llm.model,
      provider.maxTokens,
      this.config.defaultProvider,
    );
    try {
      const response = await this.llm.streamChat({
        messages,
        tools,
        system: this.systemPrompt,
        maxTokens: provider.maxTokens,
        signal,
        onText,
      });
      this.usage.inputTokens += response.usage.inputTokens;
      this.usage.outputTokens += response.usage.outputTokens;
      this.session.contextManager.recordResponseTokens(response.usage.inputTokens);
      this.tracer.recordLlmResponse(
        span,
        response.stopReason ?? "end_turn",
        response.usage.inputTokens,
        response.usage.outputTokens,
      );
      debugLog("agent.stream.llm_call.done", {
        stop_reason: response.stopReason,
        input_tokens: response.usage.inputTokens,
        output_tokens: response.usage.outputTokens,
      });
      return response;
    } catch (error) {
      this.tracer.recordError(span, error);
      throw error;
    } finally {
      this.tracer.end(span);
    }
  }

  private async forceFinalSummary(signal?: AbortSignal): Promise<string> {
    const nudge = `[System] You have reached the maximum tool execution rounds (${this.maxToolRounds}). You cannot make any more tool calls. Based on what you have already learned, provide a final answer to the user now.`;
    const messages: Message[] = [
      ...this.session.getMessagesForLlm(),
      { role: "user", content: [{ type: "text", text: nudge }] },
    ];

    try {
      let text = "";
      const response = await this.callLlm(
        messages,
        [],
        (chunk) => {
          text += chunk;
          this.emitText(chunk);
        },
        signal,
      );
      const summary = response.content
        .filter((block): block is Extract<AssistantBlock, { type: "text" }> => block.type === "text")
        .map((block) => block.text)
        .join("");
      this.session.addMessage(
        createTranscriptMessage("assistant", [{ type: "text", text: summary }], {
          usage: {
            inputTokens: response.usage.inputTokens,
            outputTokens: response.usage.outputTokens,
            totalTokens: response.usage.inputTokens + response.usage.outputTokens,
          },
        }),
      );
      this.session.save();
      return summary || text;
    } catch (error) {
      const message = `[LLM Error during max-rounds summary: ${
        error instanceof Error ? error.message : String(error)
      }]`;
      this.session.addMessage(createTranscriptMessage("assistant", [
        { type: "text", text: message },
      ]));
      this.session.save();
      this.emitText(message);
      return message;
    }
  }

  private toolDefinitions(): ToolDefinition[] {
    let definitions = this.registry.definitions(this.discoveredTools);
    if (this.subagentAgentDef && this.toolFilter) {
      definitions = this.toolFilter.filterTools(
        definitions,
        this.subagentAgentDef,
        this.subagentMode,
      );
    }
    return definitions;
  }

  private async executeToolUses(
    blocks: ToolUseBlock[],
    startIndex: number,
    initialResults: ToolResultBlock[],
    signal?: AbortSignal,
  ): Promise<{ completed: ToolResultBlock[]; suspended: boolean }> {
    const results: Array<ToolResultBlock | undefined> = new Array(blocks.length);
    initialResults.forEach((result, index) => {
      results[index] = result;
    });

    let index = startIndex;
    while (index < blocks.length) {
      const block = blocks[index]!;
      const preflight = this.preflight(block);

      if (preflight.kind === "ask") {
        this.suspendedToolRoundValue = {
          toolUseBlocks: blocks,
          completedResults: results.filter(
            (result): result is ToolResultBlock => result !== undefined,
          ),
          nextToolIndex: index,
          activeRequest: buildPermissionRequest({
            toolName: block.name,
            toolInput: block.input,
            toolUseId: block.id,
            decision: preflight.decision!,
            workdir: this.workdir,
          }),
        };
        this.activePermissionRequestValue = this.suspendedToolRoundValue.activeRequest;
        return { completed: results.filter((r): r is ToolResultBlock => r !== undefined), suspended: true };
      }

      if (preflight.kind === "result") {
        this.emitToolStart(block.name, block.input);
        this.emitToolEnd(block.name, preflight.result!.content, preflight.result!.is_error === true);
        results[index] = preflight.result!;
        index += 1;
        continue;
      }

      const batch: number[] = [];
      let cursor = index;
      while (cursor < blocks.length) {
        const candidate = blocks[cursor]!;
        const candidatePreflight = this.preflight(candidate);
        if (candidatePreflight.kind !== "execute") break;
        if (!candidatePreflight.tool?.isConcurrencySafe?.(candidate.input)) break;
        batch.push(cursor);
        cursor += 1;
      }

      if (batch.length) {
        const batchResults = await Promise.all(
          batch.map((batchIndex) =>
            this.runToolBlock(
              blocks[batchIndex]!.name,
              blocks[batchIndex]!.input,
              blocks[batchIndex]!.id,
              signal,
            ),
          ),
        );
        batch.forEach((batchIndex, offset) => {
          results[batchIndex] = batchResults[offset]!;
        });
        index = cursor;
        continue;
      }

      results[index] = await this.runToolBlock(block.name, block.input, block.id, signal);
      index += 1;
    }

    return {
      completed: results.filter((result): result is ToolResultBlock => result !== undefined),
      suspended: false,
    };
  }

  private preflight(block: ToolUseBlock): PreflightResult {
    if (this.subagentAgentDef && this.toolFilter) {
      if (!this.toolFilter.isAllowed(block.name, this.subagentAgentDef, this.subagentMode)) {
        return {
          kind: "result",
          result: {
            type: "tool_result",
            tool_use_id: block.id,
            content: `Denied: Tool '${block.name}' is not available to ${this.subagentAgentDef.agentType} subagents.`,
            is_error: true,
          },
        };
      }
    }

    const tool = this.registry.get(block.name);
    if (!tool) {
      return {
        kind: "result",
        result: {
          type: "tool_result",
          tool_use_id: block.id,
          content: `Unknown tool: ${block.name}`,
          is_error: true,
        },
      };
    }

    const decision = this.permissionDecision(tool, block.input);
    if (decision.action === "deny") {
      return {
        kind: "result",
        result: {
          type: "tool_result",
          tool_use_id: block.id,
          content: `Denied: ${decision.reason}`,
          is_error: true,
        },
      };
    }
    if (decision.action === "ask") {
      return { kind: "ask", decision };
    }
    return { kind: "execute", tool };
  }

  private permissionDecision(
    tool: Tool,
    input: Record<string, unknown>,
  ): PermissionDecision {
    const inferred = inferCapabilities(
      tool.name,
      input,
      tool.requiredCapabilities ?? [],
    );
    let decision: PolicyDecision;
    if (tool.name === "Bash") {
      decision = this.accessController.evaluateCommand(String(input.command ?? ""), inferred);
    } else {
      decision = this.accessController.evaluate(inferred);
    }

    this.audit.record(
      AuditEvent.policyDecision(tool.name, JSON.stringify(input).slice(0, 200), {
        decision: decision.action,
        matched_rule: decision.reason,
        capabilities_required: decision.decisions.map((item) => item.capability),
      }),
    );

    if (decision.action === "deny") {
      return { action: "deny", reason: decision.reason };
    }
    if (decision.action === "need_approval") {
      if (this.sessionPermissions.hasMatch(tool.name, input, this.workdir)) {
        return { action: "allow", reason: "session rule matched" };
      }
      return { action: "ask", reason: decision.reason };
    }
    return { action: "allow", reason: decision.reason };
  }

  private async runToolBlock(
    toolName: string,
    input: Record<string, unknown>,
    toolUseId: string,
    signal?: AbortSignal,
  ): Promise<ToolResultBlock> {
    const tool = this.registry.get(toolName);
    this.emitToolStart(toolName, input);
    this.toolCallCount += 1;

    if (!tool) {
      const output = `Unknown tool: ${toolName}`;
      this.emitToolEnd(toolName, output, true);
      return { type: "tool_result", tool_use_id: toolUseId, content: output, is_error: true };
    }

    const failures = this.consecutiveFailures.get(tool.name) ?? 0;
    if (failures >= MAX_TOOL_FAILURES) {
      this.consecutiveFailures.delete(tool.name);
      const output = `Error: Tool '${tool.name}' has failed ${failures} consecutive times. Do not retry this tool. Try a different approach or tool.`;
      this.emitToolEnd(tool.name, output, true);
      return { type: "tool_result", tool_use_id: toolUseId, content: output, is_error: true };
    }

    const span = this.tracer.startToolCall(
      tool.name,
      toolUseId,
      tool.isConcurrencySafe?.(input) ?? false,
    );

    try {
      let output: string;
      let isError = false;

      if (tool.isDestructive && this.sandbox.enabled && typeof input.command === "string") {
        const result = await this.sandbox.execute(input.command, tool.name);
        output = this.sandbox.formatOutput(result);
        isError = result.timedOut || result.exitCode !== 0;
      } else {
        output = await tool.run(input, this.makeToolContext(signal));
        this.audit.record(
          AuditEvent.toolCall(tool.name, JSON.stringify(input).slice(0, 200)),
        );
      }

      output = truncate(output, MAX_TOOL_RESULT_CHARS);
      this.tracer.markToolResult(span, isError, isError ? "tool_error" : "", isError ? output : "");
      this.tracer.recordToolIo(span, input, output);
      if (!isError) this.consecutiveFailures.delete(tool.name);
      this.emitToolEnd(tool.name, output, isError);
      return {
        type: "tool_result",
        tool_use_id: toolUseId,
        content: output,
        ...(isError ? { is_error: true } : {}),
      };
    } catch (error) {
      this.consecutiveFailures.set(tool.name, failures + 1);
      this.tracer.recordError(span, error);
      const output = `Error executing ${tool.name}: ${
        error instanceof Error ? error.message : String(error)
      }`;
      this.emitToolEnd(tool.name, output, true);
      return { type: "tool_result", tool_use_id: toolUseId, content: output, is_error: true };
    } finally {
      this.tracer.end(span);
    }
  }

  private makeToolContext(signal?: AbortSignal): ToolContext {
    const memoryActor: MemoryActor = this.subagentAgentDef
      ? {
          kind: "subagent",
          sessionId: this.session.sessionId,
          agentType: this.subagentAgentDef.agentType,
        }
      : this.memoryActor;

    return {
      workdir: this.workdir,
      ...(signal ? { signal } : {}),
      agent: this,
      config: this.config,
      executionMarkers: new Set(),
      skillManager: this.skills,
      onToolsDiscovered: (names) => {
        for (const name of names) this.discoveredTools.add(name);
      },
      registry: this.registry,
      ...(this.memoryManager ? { memoryManager: this.memoryManager } : {}),
      memoryActor,
    };
  }

  private emitText(text: string): void {
    try {
      this.callbacks.onText?.(text);
    } catch {
      // UI callback failures must not break the agent loop.
    }
  }

  private emitToolStart(name: string, input: Record<string, unknown>): void {
    try {
      this.callbacks.onToolStart?.(name, input);
    } catch {
      // ignore
    }
  }

  private emitToolEnd(name: string, output: string, isError: boolean): void {
    try {
      this.callbacks.onToolEnd?.(name, output, isError);
    } catch {
      // ignore
    }
  }
}

function expandHome(path: string): string {
  return path.replace(/^~(?=\/|$)/, homedir());
}
