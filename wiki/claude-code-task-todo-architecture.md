# Claude Code Task/Todo 管理架构深度解析

本文档深入分析 Claude Code 中的任务（Task）和待办事项（Todo）管理系统，包括两个版本的架构设计、存储机制、并发控制和集成模式。

## 1. 架构概览

Claude Code 实现了**两套独立的任务管理系统**，通过功能标志进行切换：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Claude Code Task/Todo 架构                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────┐          ┌─────────────────────────────────┐  │
│   │      Todo V1 (Legacy)    │          │         Task V2 (New)            │  │
│   ├─────────────────────────┤          ├─────────────────────────────────┤  │
│   │ • TodoWriteTool          │          │ • TaskCreateTool                │  │
│   │ • 内存存储               │          │ • TaskUpdateTool                │  │
│   │ • 简单状态               │          │ • TaskListTool                  │  │
│   │ • 单个代理               │          │ • TaskGetTool                   │  │
│   │                          │          │                                 │  │
│   │ 存储: AppState.todos     │          │ 存储: 文件系统 (~/.claude/tasks) │  │
│   │ 切换: !isTodoV2Enabled() │          │ 切换: isTodoV2Enabled()          │  │
│   │                          │          │                                 │  │
│   │ 适用: 简单清单           │          │ 适用: 复杂工作流、团队协        │  │
│   └─────────────────────────┘          └─────────────────────────────────┘  │
│                                                                              │
│   切换条件: isTodoV2Enabled()                                                │
│   - 非交互式模式: CLAUDE_CODE_ENABLE_TASKS=true                              │
│   - 交互式模式: 默认启用                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. Todo V1 架构

### 2.1 数据模型

```typescript
// src/utils/todo/types.ts
interface TodoItem {
  content: string        // 任务内容
  status: 'pending' | 'in_progress' | 'completed'
  activeForm: string     // 进行时的显示形式 (如 "Running tests")
}

type TodoList = TodoItem[]
```

### 2.2 存储位置

```typescript
// AppState.todos: { [agentId: string]: TodoList }
// Key: agentId 或 sessionId
// Value: 待办事项数组
```

### 2.3 工具实现

```typescript
// src/tools/TodoWriteTool/TodoWriteTool.ts
export const TodoWriteTool = buildTool({
  name: 'TodoWrite',
  isEnabled() { return !isTodoV2Enabled() },  // V2 禁用时启用
  
  async call({ todos }, context) {
    const todoKey = context.agentId ?? getSessionId()
    const oldTodos = appState.todos[todoKey] ?? []
    const allDone = todos.every(_ => _.status === 'completed')
    const newTodos = allDone ? [] : todos  // 全部完成时清空
    
    context.setAppState(prev => ({
      ...prev,
      todos: { ...prev.todos, [todoKey]: newTodos }
    }))
    
    return { data: { oldTodos, newTodos } }
  }
})
```

### 2.4 特点

| 特性 | 说明 |
|------|------|
| 存储 | 内存（AppState） |
| 持久化 | 会话级别，不跨会话保留 |
| 并发 | 单进程安全，无文件锁 |
| 适用范围 | 单代理 |
| 依赖关系 | 不支持 |
| 所有权 | 不支持 |

## 3. Task V2 架构

### 3.1 数据模型

```typescript
// src/utils/tasks.ts
interface Task {
  id: string                    // 任务ID（数字字符串，自增）
  subject: string               // 简短标题
  description: string           // 详细描述
  activeForm?: string           // 进行时的显示形式
  owner?: string                // 所有者（代理名称）
  status: 'pending' | 'in_progress' | 'completed'
  blocks: string[]              // 此任务阻塞的任务ID列表
  blockedBy: string[]           // 阻塞此任务的任务ID列表
  metadata?: Record<string, unknown>  // 任意元数据
}
```

### 3.2 文件系统存储

```
~/.claude/
└── tasks/
    └── {taskListId}/              # 任务列表ID（sessionId 或 teamName）
        ├── 1.json                 # 任务文件
        ├── 2.json
        ├── 3.json
        └── .highwatermark         # 最高ID水位标记
        └── .lock                  # 任务列表锁文件
```

### 3.3 任务列表ID解析

```typescript
// src/utils/tasks.ts
export function getTaskListId(): string {
  // 1. 环境变量显式指定
  if (process.env.CLAUDE_CODE_TASK_LIST_ID) {
    return process.env.CLAUDE_CODE_TASK_LIST_ID
  }
  
  // 2. 进程内队友使用 leader 的团队名
  const teammateCtx = getTeammateContext()
  if (teammateCtx) {
    return teammateCtx.teamName
  }
  
  // 3. 环境变量中的团队名
  // 4. Leader 设置的团队名
  // 5. 默认使用 sessionId
  return getTeamName() || leaderTeamName || getSessionId()
}
```

### 3.4 并发控制机制

Task V2 使用 **proper-lockfile** 库实现文件级并发控制：

```typescript
const LOCK_OPTIONS = {
  retries: {
    retries: 30,           // 最多重试30次
    minTimeout: 5,         // 最小等待5ms
    maxTimeout: 100,       // 最大等待100ms
  },
}

// 创建任务时的锁使用
export async function createTask(taskListId: string, taskData: Omit<Task, 'id'>): Promise<string> {
  const lockPath = await ensureTaskListLockFile(taskListId)
  let release: (() => Promise<void>) | undefined
  
  try {
    // 获取独占锁
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)
    
    // 读取当前最高ID（在锁保护下）
    const highestId = await findHighestTaskId(taskListId)
    const id = String(highestId + 1)
    
    // 写入任务文件
    const task: Task = { id, ...taskData }
    await writeFile(getTaskPath(taskListId, id), JSON.stringify(task, null, 2))
    
    notifyTasksUpdated()
    return id
  } finally {
    if (release) await release()
  }
}
```

### 3.5 任务声明与抢占

```typescript
export type ClaimTaskResult = {
  success: boolean
  reason?: 
    | 'task_not_found' 
    | 'already_claimed' 
    | 'already_resolved' 
    | 'blocked' 
    | 'agent_busy'
  task?: Task
  busyWithTasks?: string[]      // agent_busy 时返回
  blockedByTasks?: string[]     // blocked 时返回
}

export async function claimTask(
  taskListId: string,
  taskId: string,
  claimantAgentId: string,
  options: { checkAgentBusy?: boolean } = {},
): Promise<ClaimTaskResult> {
  // 检查流程：
  // 1. 任务是否存在
  // 2. 是否已被其他代理声明
  // 3. 是否已完成
  // 4. 是否有未解决的阻塞任务
  // 5. （可选）代理是否已忙碌
  
  // 使用任务列表级锁保证原子性
  // 更新任务 owner 字段
}
```

## 4. Task V2 工具详解

### 4.1 TaskCreateTool

```typescript
const inputSchema = z.strictObject({
  subject: z.string(),           // 任务标题
  description: z.string(),       // 任务描述
  activeForm: z.string().optional(),  // 进行时显示形式
  metadata: z.record(z.unknown()).optional(),  // 元数据
})

// 创建流程：
// 1. 生成任务ID（自增）
// 2. 执行 TaskCreated hooks
// 3. 如果 hooks 返回阻塞错误，删除任务并抛出异常
// 4. 自动展开任务列表面板
```

### 4.2 TaskUpdateTool

```typescript
const inputSchema = z.strictObject({
  taskId: z.string(),
  subject: z.string().optional(),
  description: z.string().optional(),
  status: TaskStatus.or(z.literal('deleted')).optional(),
  addBlocks: z.array(z.string()).optional(),      // 添加阻塞关系
  addBlockedBy: z.array(z.string()).optional(),   // 添加被阻塞关系
  owner: z.string().optional(),
  metadata: z.record(z.unknown()).optional(),
})

// 特殊功能：
// - status: 'deleted' 时物理删除任务
// - 自动清理已解决任务的阻塞关系
// - 完成任务时执行 TaskCompleted hooks
// - 更改 owner 时通过 mailbox 通知新所有者
```

### 4.3 TaskListTool

```typescript
// 过滤内部任务（metadata._internal = true）
// 过滤已解决任务的阻塞关系（已完成的不显示为阻塞）
const tasks = allTasks.map(task => ({
  id: task.id,
  subject: task.subject,
  status: task.status,
  owner: task.owner,
  blockedBy: task.blockedBy.filter(id => !resolvedTaskIds.has(id)),
}))
```

### 4.4 TaskGetTool

```typescript
// 获取单个任务的完整信息
// 包括 blocks 和 blockedBy 关系
```

## 5. 任务依赖关系

### 5.1 阻塞关系建立

```typescript
export async function blockTask(
  taskListId: string,
  fromTaskId: string,    // A
  toTaskId: string,      // B
): Promise<boolean> {
  // A blocks B 表示：A 阻塞 B
  // - fromTask.blocks 添加 toTaskId
  // - toTask.blockedBy 添加 fromTaskId
  
  // 示例：部署任务被测试任务阻塞
  // deployTask.blockedBy = ['2']  // 测试任务ID为2
  // testTask.blocks = ['3']       // 部署任务ID为3
}
```

### 5.2 抢占时的阻塞检查

```typescript
const unresolvedTaskIds = new Set(
  allTasks.filter(t => t.status !== 'completed').map(t => t.id)
)
const blockedByTasks = task.blockedBy.filter(id => unresolvedTaskIds.has(id))

if (blockedByTasks.length > 0) {
  return { success: false, reason: 'blocked', task, blockedByTasks }
}
```

## 6. 团队集成

### 6.1 任务列表共享

在多代理团队（Agent Swarms）中，所有团队成员共享同一个任务列表：

```typescript
// Leader 创建团队时设置团队名
setLeaderTeamName(teamName)

// 队友通过环境变量获取
process.env.CLAUDE_CODE_TEAM_NAME

// 所有成员使用相同的 taskListId = teamName
```

### 6.2 代理状态跟踪

```typescript
export type AgentStatus = {
  agentId: string
  name: string
  agentType?: string
  status: 'idle' | 'busy'
  currentTasks: string[]  // 当前拥有的未完成任务
}

// 根据任务所有权计算代理状态
const unresolvedTasksByOwner = new Map<string, string[]>()
for (const task of allTasks) {
  if (task.status !== 'completed' && task.owner) {
    const existing = unresolvedTasksByOwner.get(task.owner) || []
    existing.push(task.id)
    unresolvedTasksByOwner.set(task.owner, existing)
  }
}

// 有未完成任务 = busy，否则 = idle
```

### 6.3 任务分配通知

```typescript
// TaskUpdateTool 中更改 owner 时
if (updates.owner && isAgentSwarmsEnabled()) {
  const assignmentMessage = JSON.stringify({
    type: 'task_assignment',
    taskId,
    subject: existingTask.subject,
    description: existingTask.description,
    assignedBy: senderName,
    timestamp: new Date().toISOString(),
  })
  
  await writeToMailbox(updates.owner, { ... }, taskListId)
}
```

### 6.4 团队成员退出处理

```typescript
export async function unassignTeammateTasks(
  teamName: string,
  teammateId: string,
  teammateName: string,
  reason: 'terminated' | 'shutdown',
): Promise<UnassignTasksResult> {
  // 1. 找到该成员所有未完成的任务
  const unresolvedAssignedTasks = tasks.filter(
    t => t.status !== 'completed' && (t.owner === teammateId || t.owner === teammateName)
  )
  
  // 2. 取消分配并重置状态为 pending
  for (const task of unresolvedAssignedTasks) {
    await updateTask(teamName, task.id, { owner: undefined, status: 'pending' })
  }
  
  // 3. 返回通知消息给其他成员
}
```

## 7. Hooks 集成

Task V2 支持在任务生命周期事件中执行 hooks：

### 7.1 TaskCreated Hooks

```typescript
const generator = executeTaskCreatedHooks(
  taskId,
  subject,
  description,
  getAgentName(),
  getTeamName(),
  undefined,
  context?.abortController?.signal,
  undefined,
  context,
)

for await (const result of generator) {
  if (result.blockingError) {
    blockingErrors.push(getTaskCreatedHookMessage(result.blockingError))
  }
}

// 如果有阻塞错误，删除任务并抛出异常
if (blockingErrors.length > 0) {
  await deleteTask(getTaskListId(), taskId)
  throw new Error(blockingErrors.join('\n'))
}
```

### 7.2 TaskCompleted Hooks

```typescript
const generator = executeTaskCompletedHooks(
  taskId,
  existingTask.subject,
  existingTask.description,
  getAgentName(),
  getTeamName(),
  ...
)
```

## 8. 与 AppState 的关系

### 8.1 运行时任务状态

Task V2 的任务主要存储在文件系统，但 AppState 中也有相关状态：

```typescript
// AppStateStore.ts
type AppState = {
  // 运行中的任务（内存中），用于 UI 显示和轮询
  tasks: { [taskId: string]: TaskState }
  
  // Todo V1 的待办事项
  todos: { [agentId: string]: TodoList }
  
  // 当前展开的面板
  expandedView: 'none' | 'tasks' | 'teammates'
  
  // 前景化任务ID（其消息显示在主视图）
  foregroundedTaskId?: string
  
  // 正在查看的队友任务ID
  viewingAgentTaskId?: string
}
```

### 8.2 TaskState 类型

```typescript
// src/Task.ts
type TaskType = 
  | 'local_bash' 
  | 'local_agent' 
  | 'remote_agent' 
  | 'in_process_teammate'
  | 'local_workflow'
  | 'monitor_mcp'
  | 'dream'

type TaskStatus = 
  | 'pending' 
  | 'running' 
  | 'completed' 
  | 'failed' 
  | 'killed'

interface TaskStateBase {
  id: string
  type: TaskType
  status: TaskStatus
  description: string
  toolUseId?: string
  startTime: number
  endTime?: number
  outputFile: string
  outputOffset: number
  notified: boolean
}
```

注意：TaskState 用于运行时任务（如后台 bash、子代理），而 Task（Task V2）用于工作流管理。两者是不同的概念。

## 9. 验证代理集成

当启用 VERIFICATION_AGENT 功能时，系统会在完成多个任务后提醒调用验证代理：

```typescript
// TaskUpdateTool 中的验证提醒
if (
  feature('VERIFICATION_AGENT') &&
  getFeatureValue_CACHED_MAY_BE_STALE('tengu_hive_evidence', false) &&
  !context.agentId &&           // 仅主线程代理
  updates.status === 'completed'
) {
  const allTasks = await listTasks(taskListId)
  const allDone = allTasks.every(t => t.status === 'completed')
  
  if (
    allDone &&
    allTasks.length >= 3 &&
    !allTasks.some(t => /verif/i.test(t.subject))  // 没有验证任务
  ) {
    verificationNudgeNeeded = true
  }
}
```

## 10. 总结

| 特性 | Todo V1 | Task V2 |
|------|---------|---------|
| **存储** | 内存 (AppState) | 文件系统 |
| **持久化** | 会话级 | 跨会话保留 |
| **并发控制** | 单进程 | 文件锁 (proper-lockfile) |
| **团队支持** | 无 | 完整支持 |
| **依赖关系** | 无 | blocks/blockedBy |
| **所有权** | 无 | owner 字段 |
| **Hooks** | 无 | TaskCreated/TaskCompleted |
| **工具** | TodoWrite | Create/Update/List/Get |
| **启用条件** | `!isTodoV2Enabled()` | `isTodoV2Enabled()` |
| **适用场景** | 简单清单 | 复杂工作流、团队协作 |

Task V2 的设计目标是支持**多代理协作**的复杂工作流，提供了完整的任务生命周期管理、依赖关系、所有权和团队集成能力。文件系统存储和锁机制确保了跨进程、跨会话的数据一致性和持久性。
