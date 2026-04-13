# Claude Code Subagent 并发控制深度解析

> **研究日期**: 2026-04-13  
> **代码基线**: Claude Code `main` 分支（`src/` 目录）  
> 本文档深入分析 Claude Code 中 subagent 的并行/串行执行控制机制、async/sync 的区分、自动后台化策略，以及"应该开启多少个 subagent"的决策逻辑。

---

## 1. 核心概念澄清：并行 ≠ Async

在 Claude Code 中存在**两个维度**的并发控制，容易混淆：

| 维度 | 控制什么 | 关键属性 |
|------|---------|---------|
| **工具层并行** | 多个 Agent 工具调用是否同时执行 | `isConcurrencySafe` |
| **运行模式** | Agent 是否阻塞主循环/调用方 | `isAsync` |

### 1.1 工具层并行：StreamingToolExecutor

**文件**: `src/services/tools/StreamingToolExecutor.ts`  
**行号**: `34-151`

当 LLM 在单条消息中发起多个 `Agent` 工具调用时，`StreamingToolExecutor` 决定它们是否并行执行：

```typescript
private canExecuteTool(isConcurrencySafe: boolean): boolean {
  const executingTools = this.tools.filter(t => t.status === 'executing')
  return (
    executingTools.length === 0 ||
    (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe))
  )
}
```

**AgentTool 的并发属性**（`src/tools/AgentTool/AgentTool.tsx:1273`）：

```typescript
isConcurrencySafe() {
  return true;
},
```

这意味着：
- **多个 Agent 调用默认可以并行执行**
- 但如果队列中某个非并发安全工具（如文件编辑）正在执行，后续 Agent 调用需要等待
- 如果当前只有 concurrency-safe 工具在执行，新的 Agent 调用可以立即加入并行执行

### 1.2 运行模式：Sync vs Async

`isAsync` 决定的是 agent **是否阻塞调用方/主循环**，而不是是否能并行启动。

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `542-568`

```typescript
const metadata = {
  // ...
  isAsync: (run_in_background === true || selectedAgent.background === true) && !isBackgroundTasksDisabled
};

const forceAsync = isForkSubagentEnabled();
const assistantForceAsync = feature('KAIROS') ? appState.kairosEnabled : false;

const shouldRunAsync = (
  run_in_background === true ||
  selectedAgent.background === true ||
  isCoordinator ||
  forceAsync ||
  assistantForceAsync ||
  (proactiveModule?.isProactiveActive() ?? false)
) && !isBackgroundTasksDisabled;
```

| 模式 | 特点 | 使用场景 |
|------|------|---------|
| **Sync** | 阻塞当前 turn，实时看到进度和结果，完成后才继续 | 需要立即使用结果的 agent（如前置研究） |
| **Async** | 立即返回 `async_launched`，在后台运行，通过 notification 返回结果 | 独立工作、可以并行的任务 |

**关键洞察**：
- 多个 **Sync** agent 仍然可以通过 `StreamingToolExecutor` **并行启动**
- 但一旦启动，调用方（主 agent）必须等待它们全部完成后才能继续下一轮
- 多个 **Async** agent 不仅并行启动，而且主 agent 在收到 `async_launched` 后立即继续，实现真正的"后台并行"

---

## 2. Async 模式触发条件详解

### 2.1 LLM 显式请求

Agent 工具 schema 提供 `run_in_background` 参数：

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `87`

```typescript
run_in_background: z.boolean().optional().describe(
  'Set to true to run this agent in the background. You will be notified when it completes.'
)
```

当 LLM 设置 `run_in_background: true` 时，agent 以 async 模式运行。

### 2.2 Agent 定义强制后台化

Agent markdown 文件 frontmatter 可以设置 `background: true`：

**文件**: `src/tools/AgentTool/loadAgentsDir.ts`  
**行号**: `93`, `123`, `575-591`

```typescript
background: z.boolean().optional(),  // schema
background?: boolean // Always run as background task when spawned

// Parse background flag
const background =
  backgroundRaw === 'true' || backgroundRaw === true ? true : undefined
```

### 2.3 Fork Subagent 实验强制 Async

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `555-557`

```typescript
// Fork subagent experiment: force ALL spawns async for a unified
// <task-notification> interaction model
const forceAsync = isForkSubagentEnabled();
```

当 `FORK_SUBAGENT` 功能开启时，**所有** subagent _spawn_ 都强制为 async。

### 2.4 Coordinator Mode 强制 Async

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `553`, `566`

```typescript
const isCoordinator = feature('COORDINATOR_MODE') ? isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE) : false;
// ...
const shouldRunAsync = (/* ... */ isCoordinator /* ... */) && !isBackgroundTasksDisabled;
```

### 2.5 KAIROS Assistant Mode 强制 Async

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `559-566`

```typescript
// Assistant mode: force all agents async. Synchronous subagents hold the
// main loop's turn open until they complete — the daemon's inputQueue
// backs up, and the first overdue cron catch-up on spawn becomes N
// serial subagent turns blocking all user input.
const assistantForceAsync = feature('KAIROS') ? appState.kairosEnabled : false;
```

### 2.6 Auto-Background：Sync Agent 自动转为 Async

即使 LLM 没有要求 `run_in_background`，sync agent 在运行一段时间后也可以自动转为 background。

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `70-76`, `818-833`

```typescript
function getAutoBackgroundMs(): number {
  if (isEnvTruthy(process.env.CLAUDE_AUTO_BACKGROUND_TASKS) ||
      getFeatureValue_CACHED_MAY_BE_STALE('tengu_auto_background_agents', false)) {
    return 120_000;  // 120 秒
  }
  return 0;
}

// Sync agent 注册为 foreground task，但带 auto-background 定时器
const registration = registerAgentForeground({
  agentId: syncAgentId,
  // ...
  autoBackgroundMs: getAutoBackgroundMs() || undefined
});
foregroundTaskId = registration.taskId;
backgroundPromise = registration.backgroundSignal.then(() => ({ type: 'background' as const }));
```

**机制**（`src/tasks/LocalAgentTask/LocalAgentTask.tsx:580-608`）：

```typescript
if (autoBackgroundMs !== undefined && autoBackgroundMs > 0) {
  const timer = setTimeout((setAppState, agentId) => {
    // Mark task as backgrounded and resolve the signal
    setAppState(prev => {
      const prevTask = prev.tasks[agentId];
      if (!isLocalAgentTask(prevTask) || prevTask.isBackgrounded) {
        return prev;
      }
      return {
        ...prev,
        tasks: {
          ...prev.tasks,
          [agentId]: { ...prevTask, isBackgrounded: true }
        }
      };
    });
    const resolver = backgroundSignalResolvers.get(agentId);
    if (resolver) {
      resolver();
      backgroundSignalResolvers.delete(agentId);
    }
  }, autoBackgroundMs, setAppState, agentId);
}
```

当定时器触发时：
1. 将 `AppState.tasks[agentId].isBackgrounded` 设为 `true`
2. 解析 `backgroundPromise`，中断 sync agent 的 `Promise.race`
3. Sync agent 的迭代器被关闭，后台 continuation 以 `isAsync: true` 重新启动 `runAgent`
4. 立即向父 agent 返回 `async_launched` 结果

### 2.7 用户手动 Background（Ctrl+B）

用户可以通过快捷键 Ctrl+B 将所有前景任务（包括 sync agent 和 bash 命令）转为后台：

**文件**: `src/tasks/LocalShellTask/LocalShellTask.tsx`  
**行号**: `390-410`

```typescript
export function backgroundAll(getAppState: () => AppState, setAppState: SetAppState): void {
  const state = getAppState();
  // Background all foreground bash tasks
  // ...
  // Background all foreground agent tasks
  const foregroundAgentTaskIds = Object.keys(state.tasks).filter(taskId => {
    const task = state.tasks[taskId];
    return isLocalAgentTask(task) && !task.isBackgrounded;
  });
  for (const taskId of foregroundAgentTaskIds) {
    backgroundAgentTask(taskId, getAppState, setAppState);
  }
}
```

**调用方**：
- `components/SessionBackgroundHint.tsx:45`
- `tools/BashTool/UI.tsx:49`

---

## 3. Sync Agent 的完整执行流程

虽然 sync agent 阻塞调用方，但它仍然可以与其他 sync agent **并行启动**。这是 `AgentTool.tsx` 中的 sync 路径：

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `765-1200`

```typescript
// Sync 路径
return runWithAgentContext(syncAgentContext, () => wrapWithCwd(async () => {
  const agentMessages: MessageType[] = [];
  const syncTracker = createProgressTracker();

  // 1. 注册为 foreground task（支持后续 background 转换）
  let foregroundTaskId: string | undefined;
  let backgroundPromise: Promise<{type: 'background'}> | undefined;
  if (!isBackgroundTasksDisabled) {
    const registration = registerAgentForeground({...});
    foregroundTaskId = registration.taskId;
    backgroundPromise = registration.backgroundSignal.then(() => ({ type: 'background' as const }));
  }

  // 2. 获取 agent iterator
  const agentIterator = runAgent({...runAgentParams, isAsync: false, ...})[Symbol.asyncIterator]();

  try {
    while (true) {
      const elapsed = Date.now() - agentStartTime;

      // 2秒后显示 BackgroundHint UI
      if (!isBackgroundTasksDisabled && !backgroundHintShown && elapsed >= PROGRESS_THRESHOLD_MS && toolUseContext.setToolJSX) {
        backgroundHintShown = true;
        toolUseContext.setToolJSX({ jsx: <BackgroundHint />, ... });
      }

      // 3. Race：下一条消息 vs background 信号
      const nextMessagePromise = agentIterator.next();
      const raceResult = backgroundPromise
        ? await Promise.race([nextMessagePromise.then(r => ({ type: 'message' as const, result: r })), backgroundPromise])
        : { type: 'message' as const, result: await nextMessagePromise };

      // 4. 如果被 backgrounded，停止前景迭代器，启动后台 continuation
      if (raceResult.type === 'background' && foregroundTaskId) {
        wasBackgrounded = true;
        stopForegroundSummarization?.();
        void runWithAgentContext(syncAgentContext, async () => {
          await Promise.race([agentIterator.return(undefined).catch(() => {}), sleep(1000)]);
          for await (const msg of runAgent({...runAgentParams, isAsync: true, ...})) {
            // 在后台继续执行...
          }
          completeAsyncAgent(agentResult, rootSetAppState);
          enqueueAgentNotification({...});
        });
        return { data: { isAsync: true, status: 'async_launched', agentId: backgroundedTaskId, ... } };
      }

      // 5. 正常处理消息
      if (raceResult.result.done) break;
      const message = raceResult.result.value;
      agentMessages.push(message);

      // 转发 progress 到父 agent UI
      updateProgressFromMessage(syncTracker, message, syncResolveActivity, toolUseContext.options.tools);
      if (foregroundTaskId) {
        emitTaskProgress(syncTracker, foregroundTaskId, ...);
      }
      // ...
    }
  } finally {
    // 清理 foreground task（如果未被 backgrounded）
    if (foregroundTaskId && !wasBackgrounded) {
      unregisterAgentForeground(foregroundTaskId, rootSetAppState);
    }
    // ...
  }
}));
```

---

## 4. Async Agent 的完整执行流程

Async agent 从启动就是后台运行：

**文件**: `src/tools/AgentTool/AgentTool.tsx`  
**行号**: `686-764`

```typescript
if (shouldRunAsync) {
  const asyncAgentId = earlyAgentId;

  // 1. 注册为后台任务
  const agentBackgroundTask = registerAsyncAgent({
    agentId: asyncAgentId,
    description,
    prompt,
    selectedAgent,
    setAppState: rootSetAppState,
    toolUseId: toolUseContext.toolUseId
  });

  // 2. 注册 name -> agentId 映射（供 SendMessage 路由）
  if (name) {
    rootSetAppState(prev => {
      const next = new Map(prev.agentNameRegistry);
      next.set(name, asAgentId(asyncAgentId));
      return { ...prev, agentNameRegistry: next };
    });
  }

  // 3. 启动 runAsyncAgentLifecycle（ detached 执行）
  void runWithAgentContext(asyncAgentContext, () => wrapWithCwd(() => runAsyncAgentLifecycle({
    taskId: agentBackgroundTask.agentId,
    abortController: agentBackgroundTask.abortController!,
    makeStream: onCacheSafeParams => runAgent({
      ...runAgentParams,
      override: {
        ...runAgentParams.override,
        agentId: asAgentId(agentBackgroundTask.agentId),
        abortController: agentBackgroundTask.abortController!
      },
      onCacheSafeParams
    }),
    metadata,
    description,
    toolUseContext,
    rootSetAppState,
    agentIdForCleanup: asyncAgentId,
    enableSummarization: isCoordinator || isForkSubagentEnabled() || getSdkAgentProgressSummariesEnabled(),
    getWorktreeResult: cleanupWorktreeIfNeeded
  })));

  // 4. 立即返回 async_launched
  return {
    data: {
      isAsync: true as const,
      status: 'async_launched' as const,
      agentId: agentBackgroundTask.agentId,
      description,
      prompt,
      outputFile: getTaskOutputPath(agentBackgroundTask.agentId),
      canReadOutputFile
    }
  };
}
```

`runAsyncAgentLifecycle`（`src/tools/AgentTool/agentToolUtils.ts:505`）负责：
1. 驱动 `runAgent` 的 async iterator
2. 收集结果
3. 完成后通过 `enqueueAgentNotification` 将结果以 user message 形式注入父会话
4. 清理 worktree、记录 analytics

---

## 5. 并发数量限制："应该开启多少个 subagent？"

### 5.1 没有全局硬编码上限

在 Claude Code 的核心代码中，**不存在对 subagent 并发数量的硬编码限制**（如 "最多 5 个"）。`StreamingToolExecutor` 的并发控制基于工具的安全属性，而不是数量上限：

```typescript
// 只要工具是 concurrency-safe 的，就可以无限并行（仅受系统资源限制）
executingTools.every(t => t.isConcurrencySafe)
```

### 5.2 实际限制来自哪里？

| 限制来源 | 说明 |
|---------|------|
| **API 速率限制** | Anthropic API 的并发请求限制 |
| **Token 预算/成本** | 每个并行 agent 都在消耗 token |
| **终端性能** | 大量并行的进度更新会压垮 Ink UI |
| **文件锁竞争** | 如果多个 agent 同时写入同一文件或争夺 Task V2 锁，会串行化 |
| **Worktree/磁盘** | 每个 `isolation: worktree` 的 agent 都需要独立的 git worktree |

### 5.3 Batch Skill 的软性建议

**文件**: `src/skills/bundled/batch.ts`  
**行号**: `9-10`, `34-39`

```typescript
const MIN_AGENTS = 5
const MAX_AGENTS = 30

// Prompt 中指导 LLM：
2. **Decompose into independent units.** Break the work into ${MIN_AGENTS}–${MAX_AGENTS} self-contained units.
   Scale the count to the actual work: few files → closer to ${MIN_AGENTS}; hundreds of files → closer to ${MAX_AGENTS}.
```

这是代码中**唯一明确提出 subagent 数量范围**的地方：
- **最小**：5 个（避免过度拆分）
- **最大**：30 个（避免资源耗尽）
- **实际数量**：根据工作量动态调整，少量文件用少量 agent，大量文件可接近 30

### 5.4 System Prompt 的并行教导

Claude Code 的 system prompt 明确鼓励 LLM 在独立任务上使用并行：

**文件**: `src/constants/prompts.ts`  
**行号**: `310`

```typescript
`You can call multiple tools in a single response. If you intend to call multiple tools and there are no dependencies between them, make all independent tool calls in parallel. Maximize use of parallel tool calls where possible to increase efficiency.`
```

**文件**: `src/tools/AgentTool/prompt.ts`  
**行号**: `248`, `271`

```typescript
`- Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses`

`- If the user specifies that they want you to run agents 