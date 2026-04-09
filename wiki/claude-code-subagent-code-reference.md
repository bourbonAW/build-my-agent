# Claude Code Subagent 核心代码参考

> 本文档列出 Claude Code 中 Subagent 系统的核心源代码文件及其关键代码位置，便于深入研究。

---

## 1. 核心文件索引

### 1.1 主入口文件

| 文件路径 | 说明 | 关键代码行数 |
|---------|------|------------|
| `src/tools/AgentTool/AgentTool.tsx` | AgentTool 主实现 | ~1000 行 |
| `src/tools/AgentTool/agentToolUtils.ts` | 子代理工具函数 | ~700 行 |
| `src/tools/AgentTool/loadAgentsDir.ts` | 代理定义加载 | ~300 行 |

### 1.2 任务管理文件

| 文件路径 | 说明 | 关键代码行数 |
|---------|------|------------|
| `src/tasks/LocalAgentTask/LocalAgentTask.tsx` | 异步任务管理 | ~680 行 |
| `src/utils/task/framework.ts` | 任务框架通用函数 | ~200 行 |
| `src/tasks/types.ts` | 任务类型定义 | ~100 行 |

### 1.3 Fork 子代理文件

| 文件路径 | 说明 | 关键代码行数 |
|---------|------|------------|
| `src/tools/AgentTool/forkSubagent.ts` | Fork 子代理实现 | ~150 行 |
| `src/tools/AgentTool/buildForkedMessages.ts` | Fork 消息构建 | ~100 行 |

### 1.4 多代理团队文件

| 文件路径 | 说明 | 关键代码行数 |
|---------|------|------------|
| `src/tools/shared/spawnMultiAgent.ts` | 团队成员生成 | ~300 行 |
| `src/utils/team.ts` | 团队管理工具 | ~200 行 |

### 1.5 常量与配置

| 文件路径 | 说明 |
|---------|------|
| `src/constants/tools.ts` | 工具过滤常量 |
| `src/constants/agents.ts` | 内置代理定义 |

---

## 2. 关键代码位置详解

### 2.1 AgentTool.call() 方法

**文件**: `src/tools/AgentTool/AgentTool.tsx`
**行数**: 200-600

```typescript
// 核心决策逻辑
async function* call(input, context) {
  // 1. 参数解析 (第 200-250 行)
  const { 
    description, 
    prompt, 
    subagent_type, 
    model,
    run_in_background,
    team_name,
    name,
    isolation 
  } = input;
  
  // 2. 多代理团队路由 (第 284-316 行)
  if (teamName && name) {
    const result = await spawnTeammate({...}, toolUseContext);
    return { data: spawnResult };
  }
  
  // 3. 代理类型选择 (第 318-356 行)
  const effectiveType = subagent_type ?? GENERAL_PURPOSE_AGENT.agentType;
  const selectedAgent = agents.find(a => a.agentType === effectiveType);
  
  // 4. 同步/异步决策 (第 566-567 行)
  const shouldRunAsync = (
    run_in_background === true || 
    selectedAgent.background === true || 
    isCoordinator || 
    forceAsync
  ) && !isBackgroundTasksDisabled;
  
  // 5. 执行分支 (第 570-700 行)
  if (shouldRunAsync) {
    // 异步执行路径
    return yield* runAsyncPath(...);
  } else {
    // 同步执行路径
    return yield* runSyncPath(...);
  }
}
```

### 2.2 异步代理生命周期

**文件**: `src/tools/AgentTool/agentToolUtils.ts`
**行数**: 508-686

```typescript
// runAsyncAgentLifecycle 函数
export async function runAsyncAgentLifecycle({
  taskId,
  abortController,
  makeStream,
  metadata,
  description,
  toolUseContext,
  rootSetAppState,
  // ...
}): Promise<void> {
  const agentMessages: MessageType[] = [];
  
  try {
    // 进度追踪器 (第 530-535 行)
    const tracker = createProgressTracker();
    const resolveActivity = createActivityDescriptionResolver(
      toolUseContext.options.tools,
    );
    
    // 消息处理循环 (第 537-580 行)
    for await (const message of makeStream(onCacheSafeParams)) {
      agentMessages.push(message);
      
      // 更新进度 (第 550-560 行)
      updateProgressFromMessage(tracker, message, resolveActivity, tools);
      updateAsyncAgentProgress(taskId, getProgressUpdate(tracker), rootSetAppState);
      
      // 触发 SDK 事件 (第 565-575 行)
      emitTaskProgress(tracker, taskId, toolUseContext.toolUseId, description);
    }
    
    // 完成处理 (第 582-620 行)
    const agentResult = finalizeAgentTool(agentMessages, taskId, metadata);
    completeAsyncAgent(agentResult, rootSetAppState);
    
    // 发送通知 (第 625-640 行)
    enqueueAgentNotification({
      taskId,
      description,
      status: 'completed',
      finalMessage: extractFinalMessage(agentResult),
      // ...
    });
    
  } catch (error) {
    // 错误处理 (第 645-686 行)
    if (error instanceof AbortError) {
      killAsyncAgent(taskId, rootSetAppState);
      // ...
    } else {
      failAsyncAgent(taskId, errorMessage(error), rootSetAppState);
    }
  }
}
```

### 2.3 任务注册

**文件**: `src/tasks/LocalAgentTask/LocalAgentTask.tsx`
**行数**: 100-200 (registerAsyncAgent)

```typescript
export function registerAsyncAgent({
  agentId,
  description,
  prompt,
  selectedAgent,
  setAppState,
  parentAbortController,
  toolUseId,
}): LocalAgentTaskState {
  // 创建 AbortController (第 120-125 行)
  const abortController = parentAbortController 
    ? createChildAbortController(parentAbortController) 
    : createAbortController();
  
  // 初始化任务状态 (第 127-145 行)
  const taskState: LocalAgentTaskState = {
    type: 'local_agent',
    id: agentId,
    agentId,
    prompt,
    selectedAgent,
    agentType: selectedAgent?.agentType ?? 'default',
    status: 'running',
    isBackgrounded: true,
    pendingMessages: [],
    retain: false,
    diskLoaded: false,
    abortController,
    startTime: Date.now(),
  };
  
  // 注册清理处理器 (第 147-150 行)
  const unregisterCleanup = registerCleanup(async () => {
    killAsyncAgent(agentId, setAppState);
  });
  
  // 注册到 AppState (第 152-155 行)
  registerTask(taskState, setAppState);
  
  return taskState;
}
```

### 2.4 工具过滤

**文件**: `src/tools/AgentTool/agentToolUtils.ts`
**行数**: 70-116

```typescript
export function filterToolsForAgent({
  tools,
  isBuiltIn,
  isAsync = false,
  permissionMode,
}: {
  tools: Tools;
  isBuiltIn: boolean;
  isAsync?: boolean;
  permissionMode?: PermissionMode;
}): Tools {
  return tools.filter(tool => {
    // MCP 工具始终允许
    if (tool.name.startsWith('mcp__')) return true;
    
    // Plan 模式特殊处理
    if (toolMatchesName(tool, EXIT_PLAN_MODE_V2_TOOL_NAME) && 
        permissionMode === 'plan') {
      return true;
    }
    
    // 全局禁用列表
    if (ALL_AGENT_DISALLOWED_TOOLS.has(tool.name)) return false;
    
    // 自定义代理额外禁用
    if (!isBuiltIn && CUSTOM_AGENT_DISALLOWED_TOOLS.has(tool.name)) {
      return false;
    }
    
    // 异步代理工具限制
    if (isAsync && !ASYNC_AGENT_ALLOWED_TOOLS.has(tool.name)) {
      // 进程内团队成员特殊处理
      if (isAgentSwarmsEnabled() && isInProcessTeammate()) {
        if (toolMatchesName(tool, AGENT_TOOL_NAME)) return true;
        if (IN_PROCESS_TEAMMATE_ALLOWED_TOOLS.has(tool.name)) return true;
      }
      return false;
    }
    return true;
  });
}
```

### 2.5 结果终结处理

**文件**: `src/tools/AgentTool/agentToolUtils.ts`
**行数**: 400-470

```typescript
export function finalizeAgentTool(
  agentMessages: MessageType[],
  agentId: string,
  metadata: {
    agentType: string;
    description: string;
    startTime: number;
    model?: string;
  },
): AgentToolResult {
  // 获取最后一条助手消息 (第 410 行)
  const lastAssistantMessage = getLastAssistantMessage(agentMessages);
  
  // 提取文本内容 (第 412-415 行)
  let content = lastAssistantMessage.message.content.filter(c => c.type === 'text');
  
  // 回溯查找 (第 417-430 行)
  if (content.length === 0) {
    for (let i = agentMessages.length - 1; i >= 0; i--) {
      const m = agentMessages[i]!;
      if (m.type !== 'assistant') continue;
      const textBlocks = m.message.content.filter(c => c.type === 'text');
      if (textBlocks.length > 0) {
        content = textBlocks;
        break;
      }
    }
  }
  
  // 计算统计 (第 432-435 行)
  const totalTokens = getTokenCountFromUsage(lastAssistantMessage.message.usage);
  const totalToolUseCount = countToolUses(agentMessages);
  
  // 记录分析事件 (第 437-445 行)
  logEvent('tengu_agent_tool_completed', {
    agentType: metadata.agentType,
    description: metadata.description,
    totalTokens,
    totalToolUseCount,
    totalDurationMs: Date.now() - metadata.startTime,
    model: metadata.model,
  });
  
  // 返回结果 (第 447-460 行)
  return {
    agentId,
    agentType: metadata.agentType,
    content,
    totalDurationMs: Date.now() - metadata.startTime,
    totalTokens,
    totalToolUseCount,
    usage: lastAssistantMessage.message.usage,
  };
}
```

### 2.6 Fork 子代理消息构建

**文件**: `src/tools/AgentTool/buildForkedMessages.ts`
**行数**: 1-100

```typescript
export function buildForkedMessages(
  directive: string,
  assistantMessage: AssistantMessage,
): MessageType[] {
  // 克隆完整的父助手消息 (第 20-35 行)
  const fullAssistantMessage: AssistantMessage = {
    ...assistantMessage,
    uuid: randomUUID(),
    message: { 
      ...assistantMessage.message, 
      content: [...assistantMessage.message.content] 
    },
  };
  
  // 提取 tool_use 块 (第 37 行)
  const toolUseBlocks = assistantMessage.message.content.filter(
    c => c.type === 'tool_use'
  );
  
  // 创建占位结果 (第 40-50 行)
  const toolResultBlocks = toolUseBlocks.map(block => ({
    type: 'tool_result' as const,
    tool_use_id: block.id,
    content: [{ type: 'text' as const, text: FORK_PLACEHOLDER_RESULT }],
  }));
  
  // 构建子代理指令 (第 52-65 行)
  const toolResultMessage = createUserMessage({
    content: [
      ...toolResultBlocks,
      { type: 'text' as const, text: buildChildMessage(directive) },
    ],
  });
  
  return [fullAssistantMessage, toolResultMessage];
}
```

### 2.7 任务状态更新

**文件**: `src/utils/task/framework.ts`
**行数**: 50-120

```typescript
export function updateTaskState<T extends TaskState>(
  taskId: string,
  setAppState: SetAppState,
  updater: (task: T) => T,
): void {
  setAppState(prev => {
    // 查找任务 (第 55 行)
    const task = prev.tasks?.[taskId] as T | undefined;
    if (!task) return prev;
    
    // 应用更新器 (第 58 行)
    const updated = updater(task);
    
    // 无变化优化 (第 60 行)
    if (updated === task) return prev;
    
    // 返回新状态 (第 62-70 行)
    return {
      ...prev,
      tasks: {
        ...prev.tasks,
        [taskId]: updated,
      },
    };
  });
}

export function completeTask(
  taskId: string,
  result: TaskResult,
  setAppState: SetAppState,
): void {
  updateTaskState(taskId, setAppState, task => ({
    ...task,
    status: 'completed',
    result,
    completedAt: Date.now(),
  }));
}
```

---

## 3. 关键类型定义

### 3.1 AgentDefinition

**文件**: `src/tools/AgentTool/loadAgentsDir.ts`

```typescript
export type BaseAgentDefinition = {
  agentType: string;
  whenToUse: string;
  tools?: string[];
  disallowedTools?: string[];
  skills?: string[];
  mcpServers?: AgentMcpServerSpec[];
  hooks?: HooksSettings;
  color?: AgentColorName;
  model?: string;
  effort?: EffortValue;
  permissionMode?: PermissionMode;
  maxTurns?: number;
  background?: boolean;
  isolation?: 'worktree' | 'remote';
};

export type BuiltInAgentDefinition = BaseAgentDefinition & {
  source: 'built-in';
  getSystemPrompt: (params: { toolUseContext: ToolUseContext }) => string;
};
```

### 3.2 LocalAgentTaskState

**文件**: `src/tasks/LocalAgentTask/LocalAgentTask.tsx`

```typescript
export type LocalAgentTaskState = TaskStateBase & {
  type: 'local_agent';
  agentId: string;
  prompt: string;
  selectedAgent?: AgentDefinition;
  agentType: string;
  model?: string;
  abortController?: AbortController;
  error?: string;
  result?: AgentToolResult;
  progress?: AgentProgress;
  isBackgrounded: boolean;
  pendingMessages: string[];
  retain: boolean;
  diskLoaded: boolean;
  evictAfter?: number;
};
```

### 3.3 ToolUseContext

**文件**: `src/Tool.ts`

```typescript
export type ToolUseContext = {
  options: {
    commands: Command[];
    tools: Tools;
    mainLoopModel: string;
    thinkingConfig: ThinkingConfig;
    mcpClients: MCPServerConnection[];
    agentDefinitions: AgentDefinitionsResult;
    // ...
  };
  abortController: AbortController;
  readFileState: FileStateCache;
  getAppState(): AppState;
  setAppState(f: (prev: AppState) => AppState): void;
  agentId?: AgentId;
  agentType?: string;
  queryTracking?: QueryChainTracking;
  // ...
};
```

---

## 4. 工具过滤常量

**文件**: `src/constants/tools.ts`

```typescript
// 所有子代理禁用工具
export const ALL_AGENT_DISALLOWED_TOOLS = new Set([
  TASK_OUTPUT_TOOL_NAME,
  EXIT_PLAN_MODE_V2_TOOL_NAME,
  ENTER_PLAN_MODE_TOOL_NAME,
  ASK_USER_QUESTION_TOOL_NAME,
  TASK_STOP_TOOL_NAME,
  AGENT_TOOL_NAME,  // ant 用户除外
  WORKFLOW_TOOL_NAME,
]);

// 异步代理允许工具
export const ASYNC_AGENT_ALLOWED_TOOLS = new Set([
  FILE_READ_TOOL_NAME,
  FILE_EDIT_TOOL_NAME,
  FILE_WRITE_TOOL_NAME,
  GREP_TOOL_NAME,
  GLOB_TOOL_NAME,
  WEB_SEARCH_TOOL_NAME,
  WEB_FETCH_TOOL_NAME,
  TODO_WRITE_TOOL_NAME,
  SKILL_TOOL_NAME,
  ...SHELL_TOOL_NAMES,
]);

// 自定义代理额外禁用
export const CUSTOM_AGENT_DISALLOWED_TOOLS = new Set([
  TASK_LIST_TOOL_NAME,
  TASK_OUTPUT_TOOL_NAME,
  TASK_STOP_TOOL_NAME,
]);
```

---

## 5. 调试技巧

### 5.1 日志事件

Claude Code 使用 `logEvent` 函数记录关键事件：

```typescript
// 子代理完成事件
logEvent('tengu_agent_tool_completed', {
  agentType,
  description,
  totalTokens,
  totalToolUseCount,
  totalDurationMs,
  model,
});

// 子代理错误事件
logEvent('tengu_agent_tool_error', {
  agentType,
  error: errorMessage,
});
```

### 5.2 调试标志

```bash
# 启用调试日志
export CLAI_DEBUG=1

# 启用子代理详细日志
export CLAI_DEBUG_AGENT=1

# 查看任务状态
# 在 Claude Code 中使用 /task list
```

### 5.3 关键断点位置

| 功能 | 文件 | 行数 |
|-----|------|------|
| AgentTool 入口 | `AgentTool.tsx` | 200 |
| 异步代理启动 | `agentToolUtils.ts` | 508 |
| 任务注册 | `LocalAgentTask.tsx` | 100 |
| 结果终结 | `agentToolUtils.ts` | 400 |
| 状态更新 | `framework.ts` | 50 |

---

## 6. 相关阅读

- [subagent-architecture-overview.md](./subagent-architecture-overview.md) - 架构总览
- [subagent-concurrency-control.md](./subagent-concurrency-control.md) - 并发控制
- [subagent-result-handling.md](./subagent-result-handling.md) - 结果处理
- [subagent-implementation-guide.md](./subagent-implementation-guide.md) - 实现指南
