# Subagent 结果处理机制深度解析

> 本文档详细解析 Claude Code 中 Subagent 的结果处理流程，包括结果收集、终结处理、通知机制和错误恢复。

---

## 1. 结果处理架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          子代理结果处理流程                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. 消息收集                                                                │
│     ├── 实时 yield 消息块                                                   │
│     ├── 存储到 agentMessages 数组                                           │
│     └── 更新进度状态                                                        │
│                             │                                               │
│                             ▼                                               │
│  2. 终结处理 (finalizeAgentTool)                                            │
│     ├── 提取最后一条助手消息                                                 │
│     ├── 回溯查找文本内容 (如需要)                                            │
│     ├── 计算统计数据 (token 数、工具调用数)                                   │
│     └── 记录分析事件                                                        │
│                             │                                               │
│                             ▼                                               │
│  3. 状态更新                                                                │
│     ├── completeAsyncAgent() / failAsyncAgent()                             │
│     ├── 更新 AppState                                                       │
│     └── 触发 UI 重新渲染                                                     │
│                             │                                               │
│                             ▼                                               │
│  4. 通知机制                                                                │
│     ├── enqueueAgentNotification()                                          │
│     ├── 显示桌面通知 (可选)                                                  │
│     └── 更新任务列表 UI                                                      │
│                             │                                               │
│                             ▼                                               │
│  5. 父代理接收                                                               │
│     ├── 同步: 直接返回结果                                                   │
│     └── 异步: 通过通知获取结果                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 消息收集机制

### 2.1 消息流处理

```typescript
// src/tools/AgentTool/agentToolUtils.ts

export async function runAsyncAgentLifecycle({
  taskId,
  makeStream,        // 消息流生成器
  metadata,
  description,
  toolUseContext,
  rootSetAppState,
  // ...
}): Promise<void> {
  const agentMessages: MessageType[] = [];
  
  try {
    // 创建进度追踪器
    const tracker = createProgressTracker();
    const resolveActivity = createActivityDescriptionResolver(
      toolUseContext.options.tools,
    );
    
    // 消息处理循环
    for await (const message of makeStream(onCacheSafeParams)) {
      // 收集消息
      agentMessages.push(message);
      
      // 更新进度状态
      updateProgressFromMessage(tracker, message, resolveActivity, tools);
      
      // 更新异步代理进度
      updateAsyncAgentProgress(
        taskId, 
        getProgressUpdate(tracker), 
        rootSetAppState
      );
      
      // 触发 SDK 进度事件
      const lastToolName = getLastToolUseName(message);
      if (lastToolName) {
        emitTaskProgress(tracker, taskId, toolUseContext.toolUseId, description);
      }
    }
    
    // 完成处理...
    
  } catch (error) {
    // 错误处理...
  }
}
```

### 2.2 进度追踪实现

```typescript
// 进度追踪器数据结构
interface ProgressTracker {
  // 工具调用统计
  toolCalls: Map<string, number>;  // 工具名 -> 调用次数
  
  // 当前活动
  currentActivity?: string;
  
  // 文件操作统计
  filesRead: Set<string>;
  filesWritten: Set<string>;
  
  // 时间统计
  startTime: number;
  lastUpdateTime: number;
}

function createProgressTracker(): ProgressTracker {
  return {
    toolCalls: new Map(),
    filesRead: new Set(),
    filesWritten: new Set(),
    startTime: Date.now(),
    lastUpdateTime: Date.now(),
  };
}

// 从消息更新进度
function updateProgressFromMessage(
  tracker: ProgressTracker,
  message: MessageType,
  resolveActivity: ActivityResolver,
  tools: Tools,
): void {
  if (message.type === 'assistant') {
    // 统计工具调用
    const toolUses = message.message.content.filter(
      c => c.type === 'tool_use'
    );
    
    for (const toolUse of toolUses) {
      const count = tracker.toolCalls.get(toolUse.name) || 0;
      tracker.toolCalls.set(toolUse.name, count + 1);
      
      // 解析当前活动描述
      tracker.currentActivity = resolveActivity(toolUse);
    }
  } else if (message.type === 'user') {
    // 统计文件操作
    const toolResults = message.message.content.filter(
      c => c.type === 'tool_result'
    );
    
    for (const result of toolResults) {
      // 解析文件路径...
    }
  }
  
  tracker.lastUpdateTime = Date.now();
}
```

---

## 3. 终结处理 (finalizeAgentTool)

### 3.1 终结处理流程

```typescript
// src/tools/AgentTool/agentToolUtils.ts

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
  // 1. 获取最后一条助手消息
  const lastAssistantMessage = getLastAssistantMessage(agentMessages);
  
  // 2. 提取文本内容
  let content = lastAssistantMessage.message.content.filter(
    c => c.type === 'text'
  );
  
  // 3. 如果没有文本，回溯查找之前的消息
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
  
  // 4. 计算统计数据
  const totalTokens = getTokenCountFromUsage(lastAssistantMessage.message.usage);
  const totalToolUseCount = countToolUses(agentMessages);
  
  // 5. 记录分析事件
  logEvent('tengu_agent_tool_completed', {
    agentType: metadata.agentType,
    description: metadata.description,
    totalTokens,
    totalToolUseCount,
    totalDurationMs: Date.now() - metadata.startTime,
    model: metadata.model,
  });
  
  // 6. 返回结果对象
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

### 3.2 结果类型定义

```typescript
// AgentToolResult 类型
export type AgentToolResult = {
  agentId: string;           // 代理唯一标识
  agentType: string;         // 代理类型
  content: TextBlock[];      // 返回的文本内容块
  totalDurationMs: number;   // 总执行时间
  totalTokens: number;       // 总 token 使用量
  totalToolUseCount: number; // 工具调用次数
  usage?: Usage;             // 详细的使用统计
};

// 使用统计
export type Usage = {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens?: number;
  cache_read_input_tokens?: number;
};
```

---

## 4. 状态更新机制

### 4.1 完成状态更新

```typescript
// src/tasks/LocalAgentTask/LocalAgentTask.tsx

export function completeAsyncAgent(
  result: AgentToolResult,
  setAppState: SetAppState,
): void {
  updateTaskState<LocalAgentTaskState>(
    result.agentId,
    setAppState,
    task => ({
      ...task,
      status: 'completed',
      result,
      completedAt: Date.now(),
      progress: undefined,  // 清除进度信息
    }),
  );
}
```

### 4.2 失败状态更新

```typescript
export function failAsyncAgent(
  agentId: string,
  error: string,
  setAppState: SetAppState,
): void {
  updateTaskState<LocalAgentTaskState>(
    agentId,
    setAppState,
    task => ({
      ...task,
      status: 'failed',
      error,
      failedAt: Date.now(),
    }),
  );
}
```

### 4.3 终止状态更新

```typescript
export function killAsyncAgent(
  agentId: string,
  setAppState: SetAppState,
): void {
  updateTaskState<LocalAgentTaskState>(
    agentId,
    setAppState,
    task => {
      // 如果任务已完成，不更改状态
      if (task.status === 'completed' || task.status === 'failed') {
        return task;
      }
      
      return {
        ...task,
        status: 'killed',
        killedAt: Date.now(),
      };
    },
  );
}
```

---

## 5. 通知机制

### 5.1 通知队列

```typescript
// src/utils/notifications.tsx

type AgentNotification = {
  taskId: string;
  description: string;
  status: 'completed' | 'failed' | 'killed';
  finalMessage: string;
  error?: string;
  usage?: {
    totalTokens: number;
    totalToolUseCount: number;
  };
  toolUseId?: string;
  timestamp: number;
};

// 通知队列
const notificationQueue: AgentNotification[] = [];

export function enqueueAgentNotification(
  notification: Omit<AgentNotification, 'timestamp'>,
): void {
  notificationQueue.push({
    ...notification,
    timestamp: Date.now(),
  });
  
  // 触发处理
  processNotificationQueue();
}
```

### 5.2 通知显示逻辑

```typescript
async function processNotificationQueue(): Promise<void> {
  while (notificationQueue.length > 0) {
    const notification = notificationQueue.shift()!;
    
    // 根据状态构建消息
    let message: string;
    let importance: 'info' | 'success' | 'error' = 'info';
    
    switch (notification.status) {
      case 'completed':
        message = `✅ ${notification.description}\n\n${notification.finalMessage}`;
        importance = 'success';
        
        // 添加使用统计
        if (notification.usage) {
          message += `\n\n📊 Tokens: ${notification.usage.totalTokens}, `;
          message += `Tools: ${notification.usage.totalToolUseCount}`;
        }
        break;
        
      case 'failed':
        message = `❌ ${notification.description}\n\nError: ${notification.error}`;
        importance = 'error';
        break;
        
      case 'killed':
        message = `🛑 ${notification.description}\n\n任务已终止`;
        if (notification.finalMessage) {
          message += `\n\n部分结果:\n${notification.finalMessage}`;
        }
        break;
    }
    
    // 显示通知
    await showNotification({
      title: `Agent ${notification.status}`,
      message,
      importance,
    });
    
    // 发送桌面通知 (如果启用)
    if (isDesktopNotificationsEnabled()) {
      sendDesktopNotification({
        title: notification.description,
        body: notification.status === 'completed' 
          ? '任务已完成' 
          : `任务${notification.status === 'failed' ? '失败' : '终止'}`,
      });
    }
  }
}
```

### 5.3 前台 vs 异步结果展示

| 场景 | 结果展示方式 |
|-----|------------|
| **同步前台子代理** | 直接内联显示在对话中 |
| **异步后台子代理** | 通过通知系统显示，用户可点击查看详情 |
| **Fork 子代理** | 结果合并回父对话上下文 |
| **多代理团队** | 通过 Mailbox 或共享状态传递 |

---

## 6. 错误处理与恢复

### 6.1 错误分类

```typescript
// 错误类型枚举
enum AgentErrorType {
  // 用户操作错误
  USER_ABORT = 'USER_ABORT',           // 用户主动终止
  
  // 系统错误
  SYSTEM_ERROR = 'SYSTEM_ERROR',       // 系统级错误
  NETWORK_ERROR = 'NETWORK_ERROR',     // 网络/API 错误
  TIMEOUT_ERROR = 'TIMEOUT_ERROR',     // 超时错误
  
  // 资源限制错误
  MAX_TURNS_EXCEEDED = 'MAX_TURNS_EXCEEDED',  // 达到最大轮数
  RATE_LIMIT_ERROR = 'RATE_LIMIT_ERROR',      // API 限流
  TOKEN_LIMIT_ERROR = 'TOKEN_LIMIT_ERROR',    // Token 限制
  
  // 业务逻辑错误
  INVALID_INPUT = 'INVALID_INPUT',     // 输入参数错误
  PERMISSION_DENIED = 'PERMISSION_DENIED',  // 权限拒绝
}
```

### 6.2 错误处理流程

```typescript
// 在 runAsyncAgentLifecycle 中的错误处理
} catch (error) {
  stopSummarization?.();
  
  if (error instanceof AbortError) {
    // 用户终止处理
    handleUserAbort(agentMessages, taskId, metadata);
    
  } else if (error instanceof MaxTurnsExceededError) {
    // 最大轮数超出处理
    handleMaxTurnsExceeded(agentMessages, taskId, metadata, error.maxTurns);
    
  } else if (error.name === 'APIError') {
    // API 错误处理
    handleAPIError(error, taskId, metadata);
    
  } else {
    // 一般错误处理
    const errorMsg = errorMessage(error);
    
    // 记录错误
    logError(error);
    logEvent('tengu_agent_tool_error', {
      agentType: metadata.agentType,
      error: errorMsg,
    });
    
    // 更新任务状态
    failAsyncAgent(taskId, errorMsg, rootSetAppState);
    
    // 发送错误通知
    enqueueAgentNotification({
      taskId,
      description: metadata.description,
      status: 'failed',
      error: errorMsg,
      toolUseId: toolUseContext.toolUseId,
    });
  }
} finally {
  // 资源清理
  clearInvokedSkillsForAgent(agentIdForCleanup);
  clearDumpState(agentIdForCleanup);
}
```

### 6.3 部分结果提取

```typescript
function extractPartialResult(agentMessages: MessageType[]): string {
  // 查找最后一条有内容的助手消息
  for (let i = agentMessages.length - 1; i >= 0; i--) {
    const message = agentMessages[i]!;
    
    if (message.type === 'assistant') {
      const textContent = message.message.content
        .filter(c => c.type === 'text')
        .map(c => c.text)
        .join('\n');
      
      if (textContent.trim()) {
        // 截断过长的内容
        const maxLength = 2000;
        if (textContent.length > maxLength) {
          return textContent.slice(0, maxLength) + '... (truncated)';
        }
        return textContent;
      }
    }
  }
  
  return '(无可用部分结果)';
}

// 用户终止时的处理
function handleUserAbort(
  agentMessages: MessageType[],
  taskId: string,
  metadata: AgentMetadata,
): void {
  killAsyncAgent(taskId, setAppState);
  
  // 提取部分结果
  const partialResult = extractPartialResult(agentMessages);
  
  // 发送通知
  enqueueAgentNotification({
    taskId,
    description: metadata.description,
    status: 'killed',
    finalMessage: partialResult,
    toolUseId: metadata.toolUseId,
  });
}
```

---

## 7. 同步 vs 异步结果处理对比

### 7.1 流程对比

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              同步子代理                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Parent Agent                                                               │
│       │                                                                     │
│       │ 1. 调用 AgentTool                                                   │
│       ▼                                                                     │
│  ┌─────────────┐                                                           │
│  │  runAgent() │◄─────────────────────┐                                    │
│  └──────┬──────┘                      │                                    │
│         │                             │                                    │
│         │ 2. yield 消息               │                                    │
│         ▼                             │                                    │
│  Parent sees real-time output         │                                    │
│         │                             │                                    │
│         │ 3. 完成                     │                                    │
│         ▼                             │                                    │
│  ┌─────────────┐                      │                                    │
│  │ finalize()  │──────────────────────┘                                    │
│  └──────┬──────┘                                                           │
│         │                                                                   │
│         │ 4. return result                                                  │
│         ▼                                                                   │
│  Result directly in conversation                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              异步子代理                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Parent Agent                                    Background Task            │
│       │                                               │                     │
│       │ 1. 调用 AgentTool (run_in_background=true)    │                     │
│       ▼                                               │                     │
│  ┌─────────────┐                              ┌───────────────┐             │
│  │ register    │                              │ runAsyncAgent │             │
│  │ AsyncAgent()│─────────────────────────────►│ Lifecycle()   │             │
│  └──────┬──────┘                              └───────┬───────┘             │
│         │                                             │                     │
│         │ 2. 立即返回 { taskId }                      │ 3. 消息循环         │
│         │                                             │    (后台运行)       │
│         ▼                                             │                     │
│  Parent continues...                                  ▼                     │
│         │                                    ┌───────────────┐             │
│         │                                    │ finalize()    │             │
│         │                                    └───────┬───────┘             │
│         │                                            │                      │
│         │ 4. 通知 ◄──────────────────────────────────┘                      │
│         ▼                                                                   │
│  ┌─────────────┐                                                            │
│  │ Notification│                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                   │
│         ▼                                                                   │
│  User sees notification                                                     │
│  (can view full result)                                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 关键差异

| 特性 | 同步子代理 | 异步子代理 |
|-----|-----------|-----------|
| **执行方式** | 阻塞父代理 | 后台独立运行 |
| **实时输出** | 直接显示 | 通过进度状态更新 |
| **结果获取** | 直接返回 | 通过通知/状态查询 |
| **取消方式** | 直接中断 | 通过 AbortController |
| **错误处理** | 直接抛出 | 记录状态并通知 |
| **资源占用** | 占用父代理线程 | 独立调度 |

---

## 8. 多代理团队结果传递

### 8.1 Mailbox 机制

```typescript
// 进程外团队成员使用 Mailbox 文件通信

// 写入消息到 Mailbox
export async function writeToMailbox(
  agentName: string,
  message: MailboxMessage,
  teamName: string,
): Promise<void> {
  const mailboxPath = getMailboxPath(agentName, teamName);
  
  const entry: MailboxEntry = {
    ...message,
    timestamp: Date.now(),
    id: randomUUID(),
  };
  
  await appendFile(mailboxPath, JSON.stringify(entry) + '\n');
}

// 读取 Mailbox
export async function readMailbox(
  agentName: string,
  teamName: string,
  since?: number,
): Promise<MailboxEntry[]> {
  const mailboxPath = getMailboxPath(agentName, teamName);
  
  const content = await readFile(mailboxPath, 'utf-8');
  const lines = content.split('\n').filter(Boolean);
  
  return lines
    .map(line => JSON.parse(line) as MailboxEntry)
    .filter(entry => !since || entry.timestamp > since);
}
```

### 8.2 进程内团队成员结果传递

```typescript
// 进程内团队成员通过 AsyncLocalStorage 共享状态

// 定义存储
const agentContextStore = new AsyncLocalStorage<AgentContext>();

// 在团队成员中访问结果
export function getTeammateResult(teammateId: string): Promise<AgentToolResult> {
  return new Promise((resolve, reject) => {
    const checkInterval = setInterval(() => {
      const context = agentContextStore.getStore();
      
      if (context?.teammateResults.has(teammateId)) {
        clearInterval(checkInterval);
        resolve(context.teammateResults.get(teammateId)!);
      }
      
      if (context?.failedTeammates.has(teammateId)) {
        clearInterval(checkInterval);
        reject(new Error(context.failedTeammates.get(teammateId)));
      }
    }, 100);
  });
}
```

---

## 9. 总结

Claude Code 的 Subagent 结果处理机制具有以下特点：

1. **统一的消息收集**: 无论同步还是异步，都采用统一的生成器模式收集消息
2. **可靠的终结处理**: `finalizeAgentTool` 确保从完整对话中提取有效结果
3. **灵活的状态管理**: 函数式状态更新确保 UI 与内部状态一致
4. **完善的通知机制**: 异步任务完成后主动通知用户
5. **优雅的错误恢复**: 即使任务失败或终止，也能提取部分结果
6. **多样的结果传递**: 支持直接返回、通知、Mailbox、共享状态等多种方式

这套机制确保了在各种复杂场景下，子代理的结果都能被可靠地收集、处理和传递给用户或父代理。
