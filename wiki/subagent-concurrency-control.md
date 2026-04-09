# Subagent 并发控制机制深度解析

> 本文档详细解析 Claude Code 中 Subagent 的并发控制机制，包括工具过滤、执行限制和取消机制。

---

## 1. 并发控制概览

Claude Code 的并发控制是**多层次的防御体系**，在应用层、代理层和执行层都有相应的控制机制：

```
┌─────────────────────────────────────────────────────────────────┐
│                     并发控制体系                                 │
├─────────────────────────────────────────────────────────────────┤
│  Level 1: 应用层控制                                              │
│  ├── 用户配置的最大并发数限制 (CLAI_MAX_PARALLEL_AGENTS)          │
│  ├── 系统资源监控 (内存、CPU)                                      │
│  └── 任务队列管理                                                 │
├─────────────────────────────────────────────────────────────────┤
│  Level 2: 代理层控制                                              │
│  ├── 工具集白名单/黑名单                                           │
│  ├── 最大轮数限制 (maxTurns)                                       │
│  ├── 权限模式限制 (permissionMode)                                 │
│  └── MCP 服务器访问控制                                            │
├─────────────────────────────────────────────────────────────────┤
│  Level 3: 执行层控制                                              │
│  ├── AbortController 信号传递                                      │
│  ├── 超时控制                                                     │
│  └── 死锁检测                                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 工具过滤系统

### 2.1 工具分类定义

```typescript
// src/constants/tools.ts

/**
 * 所有子代理都禁止使用的工具
 * 这些工具可能导致递归、安全问题或用户体验问题
 */
export const ALL_AGENT_DISALLOWED_TOOLS = new Set([
  TASK_OUTPUT_TOOL_NAME,           // 防止递归调用 TaskOutput
  EXIT_PLAN_MODE_V2_TOOL_NAME,     // 子代理不能退出父代理的计划模式
  ENTER_PLAN_MODE_TOOL_NAME,       // 子代理不能进入计划模式
  ASK_USER_QUESTION_TOOL_NAME,     // 子代理不能直接询问用户
  TASK_STOP_TOOL_NAME,             // 子代理不能停止其他任务
  AGENT_TOOL_NAME,                 // 防止递归嵌套 (ant 用户除外)
  WORKFLOW_TOOL_NAME,              // 子代理不能执行工作流脚本
]);

/**
 * 异步代理允许使用的工具集 (受限)
 * 异步代理在后台运行，无法显示 UI，因此限制为"安全"的工具
 */
export const ASYNC_AGENT_ALLOWED_TOOLS = new Set([
  // 文件操作
  FILE_READ_TOOL_NAME,
  FILE_EDIT_TOOL_NAME,
  FILE_WRITE_TOOL_NAME,
  NOTEBOOK_EDIT_TOOL_NAME,
  GLOB_TOOL_NAME,
  
  // 代码搜索
  GREP_TOOL_NAME,
  
  // Web 工具
  WEB_SEARCH_TOOL_NAME,
  WEB_FETCH_TOOL_NAME,
  
  // Shell (受权限系统控制)
  ...SHELL_TOOL_NAMES,
  
  // 其他
  TODO_WRITE_TOOL_NAME,
  SKILL_TOOL_NAME,
  SYNTHETIC_OUTPUT_TOOL_NAME,
  TOOL_SEARCH_TOOL_NAME,
  ENTER_WORKTREE_TOOL_NAME,
  EXIT_WORKTREE_TOOL_NAME,
]);

/**
 * 自定义代理额外禁止的工具
 * 自定义代理的安全限制更严格
 */
export const CUSTOM_AGENT_DISALLOWED_TOOLS = new Set([
  TASK_LIST_TOOL_NAME,
  TASK_OUTPUT_TOOL_NAME,
  TASK_STOP_TOOL_NAME,
]);

/**
 * 进程内团队成员允许的工具 (Agent Swarms 特性)
 */
export const IN_PROCESS_TEAMMATE_ALLOWED_TOOLS = new Set([
  AGENT_TOOL_NAME,           // 允许嵌套子代理
  TASK_CREATE_TOOL_NAME,     // 允许创建任务
  TASK_LIST_TOOL_NAME,       // 允许查看任务列表
  TASK_OUTPUT_TOOL_NAME,     // 允许获取任务输出
  TASK_STOP_TOOL_NAME,       // 允许停止任务
]);
```

### 2.2 动态工具过滤逻辑

```typescript
// src/tools/AgentTool/agentToolUtils.ts

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
    // MCP 工具始终允许 - 它们由 MCP 服务器管理权限
    if (tool.name.startsWith('mcp__')) {
      return true;
    }

    // 特殊处理: Plan 模式下允许退出计划模式工具
    if (
      toolMatchesName(tool, EXIT_PLAN_MODE_V2_TOOL_NAME) &&
      permissionMode === 'plan'
    ) {
      return true;
    }

    // 规则 1: 所有子代理禁用工具
    if (ALL_AGENT_DISALLOWED_TOOLS.has(tool.name)) {
      return false;
    }

    // 规则 2: 自定义代理额外禁用
    if (!isBuiltIn && CUSTOM_AGENT_DISALLOWED_TOOLS.has(tool.name)) {
      return false;
    }

    // 规则 3: 异步代理工具限制
    if (isAsync && !ASYNC_AGENT_ALLOWED_TOOLS.has(tool.name)) {
      // 进程内团队成员特殊处理
      if (isAgentSwarmsEnabled() && isInProcessTeammate()) {
        if (toolMatchesName(tool, AGENT_TOOL_NAME)) {
          return true;
        }
        if (IN_PROCESS_TEAMMATE_ALLOWED_TOOLS.has(tool.name)) {
          return true;
        }
      }
      return false;
    }

    return true;
  });
}
```

### 2.3 工具过滤流程图

```
输入: 完整工具集 + 代理配置
         │
         ▼
┌─────────────────────┐
│ 工具是否以 mcp__ 开头? │──YES──► 允许
└─────────────────────┘
         │ NO
         ▼
┌─────────────────────┐
│ 是否在全局禁用列表?   │──YES──► 拒绝
└─────────────────────┘
         │ NO
         ▼
┌─────────────────────┐
│ 是否自定义代理且在     │──YES──► 拒绝
│ 自定义禁用列表中?     │
└─────────────────────┘
         │ NO
         ▼
┌─────────────────────┐
│ 是否异步代理?         │──NO──► 允许
└─────────────────────┘
         │ YES
         ▼
┌─────────────────────┐
│ 是否在异步允许列表?   │──YES──► 允许
└─────────────────────┘
         │ NO
         ▼
┌─────────────────────┐
│ 是否进程内团队成员     │
│ 且在特殊允许列表?     │──YES──► 允许
└─────────────────────┘
         │ NO
         ▼
       拒绝
```

---

## 3. 最大轮数限制 (maxTurns)

### 3.1 轮数限制配置

```typescript
// AgentDefinition 中的 maxTurns 配置
export type BaseAgentDefinition = {
  // ... 其他字段
  maxTurns?: number;  // 默认: 200
};

// 内置代理的典型配置
export const DEFAULT_AGENT = {
  agentType: 'default',
  maxTurns: 200,  // 默认 200 轮
  // ...
};

export const QUICK_TASK_AGENT = {
  agentType: 'quick-task',
  maxTurns: 50,   // 快速任务 50 轮
  // ...
};

export const FORK_AGENT = {
  agentType: 'fork',
  maxTurns: 200,
  // ...
};
```

### 3.2 轮数检查实现

```typescript
// 在 runAgent 循环中
async function* runAgent(config: AgentConfig): AsyncGenerator<...> {
  let turnCount = 0;
  const maxTurns = config.maxTurns ?? 200;
  
  while (turnCount < maxTurns) {
    turnCount++;
    
    // 检查取消信号
    if (config.abortController.signal.aborted) {
      throw new AbortError();
    }
    
    // 执行一轮
    const response = await queryLLM(messages);
    yield response;
    
    // 检查是否完成
    if (isComplete(response)) {
      return finalizeResult(messages);
    }
  }
  
  // 达到最大轮数
  throw new MaxTurnsExceededError(maxTurns);
}
```

---

## 4. 取消机制 (AbortController)

### 4.1 AbortController 层级结构

```typescript
// src/utils/abortController.ts

/**
 * 创建带有父子关系的 AbortController
 * 当父控制器被取消时，子控制器会自动取消
 */
export function createChildAbortController(
  parent: AbortController
): AbortController {
  const child = new AbortController();
  
  // 监听父信号
  parent.signal.addEventListener('abort', () => {
    child.abort();
  });
  
  return child;
}

/**
 * 创建可组合多个信号的 AbortController
 */
export function createComposedAbortController(
  signals: AbortSignal[]
): AbortController {
  const controller = new AbortController();
  
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort();
      return controller;
    }
    
    signal.addEventListener('abort', () => {
      controller.abort();
    });
  }
  
  return controller;
}
```

### 4.2 实际使用场景

```
场景 1: 用户终止前台子代理
┌─────────────────┐
│ 用户按下 Ctrl+C  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 调用 abort()    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│ runAgent 循环检测到取消信号  │
│ throw new AbortError()      │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ 清理资源，返回部分结果       │
└─────────────────────────────┘

场景 2: 父代理终止，级联取消子代理
┌─────────────────┐
│ 父代理被终止    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│ 父 AbortController.abort()  │
└────────┬────────────────────┘
         │
    ┌────┼────┬────────┐
    ▼    ▼    ▼        ▼
┌─────┐┌───┐┌─────┐ ┌─────┐
│子1  ││子2││子3  │ │子4  │
└─────┘└───┘└─────┘ └─────┘
(全部自动取消)
```

### 4.3 取消处理代码示例

```typescript
// 在异步代理生命周期中
export async function runAsyncAgentLifecycle({
  abortController,
  // ...
}): Promise<void> {
  try {
    for await (const message of makeStream()) {
      // 检查取消信号
      if (abortController.signal.aborted) {
        throw new AbortError();
      }
      
      // 处理消息...
    }
    
    // 正常完成
    completeAsyncAgent(result, setAppState);
    
  } catch (error) {
    if (error instanceof AbortError || 
        error.name === 'AbortError') {
      // 用户终止处理
      killAsyncAgent(taskId, setAppState);
      
      // 尝试提取部分结果
      const partialResult = extractPartialResult(agentMessages);
      
      // 发送终止通知
      enqueueAgentNotification({
        taskId,
        status: 'killed',
        finalMessage: `任务被终止。部分结果:\n${partialResult}`,
        // ...
      });
    } else {
      // 其他错误处理
      failAsyncAgent(taskId, errorMessage(error), setAppState);
    }
  }
}
```

---

## 5. 权限模式控制

### 5.1 权限模式类型

```typescript
type PermissionMode = 
  | 'default'      // 默认模式：根据工具设置决定是否提示
  | 'bypass'       // 绕过权限：自动批准所有工具调用
  | 'plan'         // 计划模式：特殊处理，允许退出计划模式
  | 'bubble';      // 冒泡模式：权限提示冒泡到父终端
```

### 5.2 不同模式的应用场景

| 模式 | 应用场景 | 行为 |
|-----|---------|------|
| `default` | 前台同步子代理 | 根据用户设置显示权限提示 |
| `bypass` | 可信的内部操作 | 自动批准，不提示用户 |
| `plan` | 计划模式的子代理 | 允许使用退出计划模式工具 |
| `bubble` | Fork 子代理 | 权限提示显示在父终端 |

### 5.3 权限冒泡实现

```typescript
// Fork 子代理使用 bubble 模式
export const FORK_AGENT = {
  agentType: FORK_SUBAGENT_TYPE,
  permissionMode: 'bubble',
  // 权限提示会冒泡到父终端显示
};

// 权限检查逻辑
async function checkPermission(toolCall: ToolCall, context: ToolUseContext) {
  const permissionMode = context.permissionMode ?? 'default';
  
  if (permissionMode === 'bypass') {
    return { allowed: true };
  }
  
  if (permissionMode === 'bubble') {
    // 将权限请求发送到父终端
    const response = await sendPermissionRequestToParent(toolCall);
    return response;
  }
  
  // 默认模式：本地处理
  return await showPermissionPrompt(toolCall);
}
```

---

## 6. 资源限制与监控

### 6.1 内存监控

```typescript
// 在 runAsyncAgentLifecycle 中的内存检查
async function checkMemoryUsage() {
  const usage = process.memoryUsage();
  const heapUsedMB = usage.heapUsed / 1024 / 1024;
  
  // 如果内存使用超过阈值，触发警告或清理
  if (heapUsedMB > MEMORY_WARNING_THRESHOLD_MB) {
    logWarning(`High memory usage: ${heapUsedMB.toFixed(2)} MB`);
    
    // 可选：触发垃圾回收 (如果可用)
    if (global.gc) {
      global.gc();
    }
  }
}
```

### 6.2 任务清理机制

```typescript
// 注册清理处理器
const unregisterCleanup = registerCleanup(async () => {
  // 终止子代理
  killAsyncAgent(agentId, setAppState);
  
  // 清理临时文件
  await cleanupTempFiles(agentId);
  
  // 释放资源
  clearInvokedSkillsForAgent(agentId);
  clearDumpState(agentId);
});

// 自动清理过期的后台任务
function scheduleEviction(taskId: string, ttlMs: number) {
  const evictAfter = Date.now() + ttlMs;
  
  updateTaskState(taskId, setAppState, task => ({
    ...task,
    evictAfter,
  }));
}
```

---

## 7. 并发限制配置

### 7.1 环境变量配置

```bash
# 最大并行子代理数
export CLAI_MAX_PARALLEL_AGENTS=10

# 是否禁用后台任务
export CLAI_DISABLE_BACKGROUND_TASKS=1

# 是否启用 Agent Swarms
export CLAI_AGENT_SWARMS=1

# 是否启用 Fork Subagent
export CLAI_FORK_SUBAGENT=1
```

### 7.2 运行时检查

```typescript
// 检查是否允许创建新的后台任务
function canCreateBackgroundTask(appState: AppState): boolean {
  // 检查全局禁用标志
  if (isBackgroundTasksDisabled()) {
    return false;
  }
  
  // 检查当前后台任务数量
  const backgroundTasks = Object.values(appState.tasks || {})
    .filter(t => t.type === 'local_agent' && t.isBackgrounded);
  
  const maxParallel = getMaxParallelAgents();
  
  return backgroundTasks.length < maxParallel;
}

// 获取最大并行数
function getMaxParallelAgents(): number {
  const envValue = process.env.CLAI_MAX_PARALLEL_AGENTS;
  if (envValue) {
    const parsed = parseInt(envValue, 10);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return 10; // 默认值
}
```

---

## 8. 总结

Claude Code 的并发控制机制通过以下策略实现了安全、可控的子代理并发执行：

1. **工具过滤**: 基于白名单/黑名单的动态工具集过滤，防止危险操作
2. **轮数限制**: maxTurns 防止无限循环和资源耗尽
3. **取消机制**: AbortController 层级结构支持优雅的级联取消
4. **权限模式**: 灵活的权限控制策略，适应不同场景
5. **资源监控**: 内存和任务数量的运行时监控
6. **配置灵活**: 通过环境变量允许用户自定义限制

这套机制确保了即使在大量子代理并发执行的情况下，系统也能保持稳定和可控。
