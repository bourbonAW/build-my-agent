# Claude Code Subagent 架构总览

> 本文档详细解析 Claude Code 中 Subagent（子代理）系统的整体架构设计，包括并发控制、结果处理和状态管理机制。

---

## 1. 架构分层概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AgentTool (主入口层)                                  │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  call() 方法 - 统一的子代理调用接口                                      │  │
│  │  ├── 输入参数解析 (description, prompt, subagent_type, model...)        │  │
│  │  ├── 多代理团队路由 (team_name + name)                                  │  │
│  │  ├── Fork 子代理判断 (isForkSubagentEnabled)                            │  │
│  │  ├── MCP 服务器依赖检查                                                  │  │
│  │  └── 同步/异步执行路径决策                                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
           ┌──────────────────────────┼──────────────────────────┐
           ▼                          ▼                          ▼
┌─────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│   Teammate Spawn    │  │      Async Agent        │  │       Sync Agent        │
│   (多代理团队成员)    │  │      (后台异步)          │  │       (前台同步)         │
│                     │  │                         │  │                         │
│  • 进程内/进程外      │  │  • 受限工具集            │  │  • 完整工具集            │
│  • Mailbox 通信      │  │  • 自动后台化            │  │  • 阻塞执行              │
│  • tmux/iTerm2 面板  │  │  • 通知机制              │  │  • 即时返回结果          │
└─────────────────────┘  └─────────────────────────┘  └─────────────────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │       runAgent()        │
                         │      子代理执行核心      │
                         │                         │
                         │  • 消息循环处理          │
                         │  • 工具调用执行          │
                         │  • 进度状态更新          │
                         └─────────────────────────┘
```

---

## 2. 核心组件职责

### 2.1 AgentTool - 统一入口

**文件位置**: `src/tools/AgentTool/AgentTool.tsx`

AgentTool 是所有子代理调用的统一入口，负责：

| 职责 | 说明 |
|-----|------|
| **参数解析** | 解析 description, prompt, subagent_type, model 等参数 |
| **路由决策** | 根据参数决定走多代理团队、Fork 子代理还是普通子代理 |
| **模式选择** | 决定同步执行还是异步后台执行 |
| **工具过滤** | 根据代理类型过滤可用工具集 |

### 2.2 LocalAgentTask - 异步任务管理

**文件位置**: `src/tasks/LocalAgentTask/LocalAgentTask.tsx`

负责异步子代理的生命周期管理：

- 任务注册与状态初始化
- AbortController 父子关系管理
- 进度消息处理与状态更新
- 任务完成/失败/终止处理

### 2.3 Task Framework - 统一任务框架

**文件位置**: `src/utils/task/framework.ts`

提供所有任务类型的通用状态管理功能：

- `registerTask()` - 注册新任务到 AppState
- `updateTaskState()` - 更新任务状态
- `completeTask()` / `failTask()` / `killTask()` - 状态流转

---

## 3. 并发模型设计

### 3.1 并发控制策略

Claude Code 采用**多层次并发控制**策略：

```
┌────────────────────────────────────────┐
│          应用级别并发控制                │
│  • 后台任务数量限制 (通过配置控制)        │
│  • 资源监控与自动清理                     │
└────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│          代理级别并发控制                │
│  • 工具集限制 (异步代理受限工具集)         │
│  • 最大轮数限制 (maxTurns)               │
│  • 权限模式控制                          │
└────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│          执行级别并发控制                │
│  • AbortController 父子层级             │
│  • 任务状态机 (pending → running → done) │
└────────────────────────────────────────┘
```

### 3.2 工具集权限矩阵

| 工具类别 | 同步代理 | 异步代理 | 进程内团队成员 | 进程外团队成员 |
|---------|---------|---------|--------------|--------------|
| 文件读写 | ✅ | ✅ | ✅ | ✅ |
| Shell 命令 | ✅ | ✅ | ✅ | ✅ |
| Web 搜索 | ✅ | ✅ | ✅ | ✅ |
| Grep/Glob | ✅ | ✅ | ✅ | ✅ |
| Agent 工具 (递归) | ✅ (ant 用户) | ❌ | ✅ | ❌ |
| Task 管理工具 | ✅ | ❌ | ✅ | ❌ |
| 计划模式工具 | ❌ | ❌ | ❌ | ❌ |
| MCP 工具 | ✅ | ✅ | ✅ | ✅ |

---

## 4. 状态管理架构

### 4.1 任务状态机

```
                    ┌─────────────┐
         ┌─────────►│   pending   │◄────────┐
         │          │   (待定)     │         │
         │          └──────┬──────┘         │
         │                 │ registerTask() │
         │                 ▼                │
    kill  │          ┌─────────────┐         │ retry
         │          │   running   │─────────┘
         │     ┌───►│   (运行中)   │◄───┐
         │     │    └──────┬──────┘    │
         │     │           │           │
         │  kill      complete      fail
         │     │           │           │
         │     │           ▼           │
         │     │    ┌─────────────┐    │
         │     └────┤  completed  ├────┘
         │          │   (已完成)   │
         │          └─────────────┘
         │
         └────────────►┌─────────────┐
                       │    killed   │
                       │   (已终止)   │
                       └─────────────┘

         fail ─────────►┌─────────────┐
                       │    failed   │
                       │   (已失败)   │
                       └─────────────┘
```

### 4.2 AppState 集成

```typescript
// AppState 中的任务存储结构
type AppState = {
  // ... 其他状态
  tasks?: {
    [taskId: string]: TaskState;
  };
  teamContext?: {
    teamName: string;
    role: 'lead' | 'teammate';
  };
};

// 任务状态联合类型
type TaskState = 
  | LocalAgentTaskState    // 本地代理任务
  | BashTaskState          // Bash 命令任务
  | ServerTaskState        // 服务器任务
  | OutOfProcessTeammateTaskState;  // 进程外团队成员任务
```

### 4.3 状态更新机制

```typescript
// 函数式状态更新模式
function updateTaskState<T extends TaskState>(
  taskId: string,
  setAppState: SetAppState,
  updater: (task: T) => T,
): void {
  setAppState(prev => {
    const task = prev.tasks?.[taskId] as T | undefined;
    if (!task) return prev;  // 任务不存在，不更新
    
    const updated = updater(task);
    if (updated === task) return prev;  // 无变化优化
    
    return {
      ...prev,
      tasks: {
        ...prev.tasks,
        [taskId]: updated,
      },
    };
  });
}
```

---

## 5. 执行流程详解

### 5.1 同步子代理执行流程

```
1. 用户调用 Agent 工具
         │
         ▼
2. AgentTool.call() 解析参数
         │
         ▼
3. 决策: run_in_background=false
         │ 且非 coordinator 模式
         │ 且非 proactive 模式
         ▼
4. 注册前台任务 (registerAgentForeground)
         │ - 创建 AbortController
         │ - 可选: 设置自动后台化定时器
         ▼
5. 直接执行 runAgent()
         │ - 创建迭代器
         │ - 循环处理消息
         ▼
6. 实时 yield 进度
         │ - 用户可在 UI 看到实时输出
         ▼
7. 执行完成
         │ - finalizeAgentTool() 提取结果
         ▼
8. 返回结果给父 Agent
```

### 5.2 异步子代理执行流程

```
1. 用户调用 Agent 工具 (run_in_background=true)
         │
         ▼
2. AgentTool.call() 解析参数
         │
         ▼
3. 决策: 需要异步执行
         │
         ▼
4. 注册异步任务 (registerAsyncAgent)
         │ - 创建 AbortController
         │ - 标记 isBackgrounded=true
         │ - 注册清理处理器
         ▼
5. 启动 runAsyncAgentLifecycle()
         │ - 在 Promise 中执行
         │ - 立即返回 { taskId }
         ▼
6. 后台消息循环
         │ - 独立处理消息流
         │ - 更新进度状态
         ▼
7. 完成时发送通知
         │ - enqueueAgentNotification()
         │ - 通过 notify.tsx 显示
         ▼
8. 更新任务状态为 completed/failed/killed
```

---

## 6. 关键设计模式

### 6.1 生成器模式 (Generator Pattern)

子代理执行采用生成器模式实现渐进式结果返回：

```typescript
async function* runAgent(
  config: AgentConfig,
  context: ToolUseContext,
): AsyncGenerator<AgentMessage, AgentResult, unknown> {
  // 初始化
  const messages: Message[] = [];
  
  // 消息处理循环
  while (true) {
    // 调用 LLM API
    const response = await queryLLM(messages);
    
    // yield 每条消息
    for (const message of response.messages) {
      yield message;
    }
    
    // 检查是否完成
    if (isComplete(response)) {
      return finalizeResult(messages);
    }
    
    // 处理工具调用
    const toolResults = await executeTools(response.toolCalls);
    messages.push(...toolResults);
  }
}
```

### 6.2 AbortController 层级结构

支持父子取消信号的传播：

```
Parent AbortController
         │
         ├──► Child AbortController (Subagent 1)
         │
         ├──► Child AbortController (Subagent 2)
         │
         └──► Child AbortController (Subagent 3)
         
// 取消父控制器会自动取消所有子控制器
parentAbortController.abort();  // 级联取消
```

### 6.3 函数式状态更新

所有状态更新都遵循不可变数据模式：

```typescript
// 错误的 mutable 更新
state.tasks[taskId].status = 'completed';  // ❌

// 正确的 immutable 更新
setAppState(prev => ({
  ...prev,
  tasks: {
    ...prev.tasks,
    [taskId]: {
      ...prev.tasks[taskId],
      status: 'completed',
    },
  },
}));  // ✅
```

---

## 7. 扩展性设计

### 7.1 自定义代理支持

用户可以通过配置文件定义自定义代理：

```typescript
// ~/.claude/agents/my-agent.json
{
  "agentType": "my-custom-agent",
  "whenToUse": "用于特定的代码审查任务",
  "tools": ["FileReadTool", "GrepTool"],
  "disallowedTools": ["BashTool"],
  "skills": ["code-review"],
  "model": "claude-sonnet-4-20250514",
  "maxTurns": 50,
  "background": true,
  "permissionMode": "bubble"
}
```

### 7.2 MCP 服务器集成

子代理可以继承父代理的 MCP 服务器连接：

```typescript
// 在 AgentTool 中传递 MCP 客户端
const mcpClients = toolUseContext.options.mcpClients;

// 子代理可以使用相同的 MCP 工具
const mcpTools = mcpClients.flatMap(client => client.tools);
```

---

## 8. 总结

Claude Code 的 Subagent 架构通过以下设计实现了高效、可靠的并发子代理管理：

1. **分层架构**: 清晰的职责分离（入口层 → 任务管理层 → 执行层）
2. **灵活的模式**: 支持同步/异步、进程内/进程外多种执行模式
3. **精细的权限控制**: 基于代理类型的动态工具过滤
4. **可靠的状态管理**: 统一的状态机和函数式更新
5. **优雅的取消机制**: AbortController 层级结构支持级联取消
6. **完善的错误处理**: 多层捕获、部分结果保留、优雅降级

这个架构设计使得 Claude Code 能够同时管理数十个子代理任务，同时保持稳定性和可观测性。
