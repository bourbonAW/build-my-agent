# Claude Code Task/Todo 管理架构深度解析

> **研究日期**: 2026-04-13  
> **代码基线**: Claude Code `main` 分支（`src/` 目录）  
> 本文档深入分析 Claude Code 中的任务（Task）和待办事项（Todo）管理系统，包括两个版本的架构设计、存储机制、并发控制、触发时机和集成模式，并标注了关键代码的精确文件路径与行号。

---

## 1. 架构概览

Claude Code 实现了**两套互斥的任务管理系统**，通过运行时开关 `isTodoV2Enabled()` 决定启用哪一套：

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
│   切换条件: isTodoV2Enabled() 在程序启动时一次性决定                           │
│   - 交互式模式 (TTY): 默认启用 V2                                             │
│   - 非交互式模式 (-p/--print/--sdk-url): 默认启用 V1                          │
│   - 环境变量 CLAUDE_CODE_ENABLE_TASKS=1 可强制启用 V2                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 触发时机：什么时候用 V1，什么时候用 V2？

### 2.1 主开关判定（会话级，启动时决定）

**文件**: `src/utils/tasks.ts`  
**行号**: `133-139`

```typescript
export function isTodoV2Enabled(): boolean {
  // 环境变量可强制覆盖所有逻辑
  if (isEnvTruthy(process.env.CLAUDE_CODE_ENABLE_TASKS)) {
    return true
  }
  // 交互式会话启用 V2；非交互式启用 V1
  return !getIsNonInteractiveSession()
}
```

**文件**: `src/bootstrap/state.ts`  
**行号**: `1057-1059`

```typescript
export function getIsNonInteractiveSession(): boolean {
  return !STATE.isInteractive
}
```

### 2.2 交互式 vs 非交互式的判定时机

**文件**: `src/main.tsx`  
**行号**: `797-812`

```typescript
const cliArgs = process.argv.slice(2);
const hasPrintFlag = cliArgs.includes('-p') || cliArgs.includes('--print');
const hasInitOnlyFlag = cliArgs.includes('--init-only');
const hasSdkUrl = cliArgs.some(arg => arg.startsWith('--sdk-url'));
const isNonInteractive = hasPrintFlag || hasInitOnlyFlag || hasSdkUrl || !process.stdout.isTTY;

// ...
const isInteractive = !isNonInteractive;
setIsInteractive(isInteractive);
```

| 启动条件 | `isInteractive` | `isTodoV2Enabled()` | 启用的系统 |
|---------|-----------------|---------------------|-----------|
| 普通 TTY 启动（`claude`） | `true` | `true` | **Task V2**（磁盘持久化） |
| `-p` / `--print` | `false` | `false` | **TodoWrite V1**（内存） |
| `--init-only` | `false` | `false` | **TodoWrite V1**（内存） |
| `--sdk-url` | `false` | `false` | **TodoWrite V1**（内存） |
| stdout 不是 TTY（CI/管道） | `false` | `false` | **TodoWrite V1**（内存） |
| `CLAUDE_CODE_ENABLE_TASKS=1` | 任意 | `true`（强制） | **Task V2** |

> **核心结论**：日常在终端里交互使用时默认走 Task V2；当做脚本/SDK/headless 跑时默认走 TodoWrite V1。

---

## 3. 工具注册：LLM 什么时候能看到哪套工具？

### 3.1 全局工具列表组装

**文件**: `src/tools.ts`  
**行号**: `208-220`

```typescript
TodoWriteTool,  // 始终注册，但内部通过 isEnabled() 自过滤
// ...
...(isTodoV2Enabled()
  ? [TaskCreateTool, TaskGetTool, TaskUpdateTool, TaskListTool]
  : []),
```

### 3.2 TodoWriteTool 的自过滤

**文件**: `src/tools/TodoWriteTool/TodoWriteTool.ts`  
**行号**: `51-54`

```typescript
isEnabled() {
  return !isTodoV2Enabled()
},
```

### 3.3 Task 工具的自过滤

以 `TaskCreateTool` 为例（其余三个相同逻辑）：

**文件**: `src/tools/TaskCreateTool/TaskCreateTool.ts`  
**行号**: `67-70`

```typescript
isEnabled() {
  return isTodoV2Enabled()
},
```

因此：
- **V2 模式**：LLM 只能看到 `TaskCreate` / `TaskGet` / `TaskUpdate` / `TaskList`
- **V1 模式**：LLM 只能看到 `TodoWrite`

---

## 4. 不同 Agent/子进程中的触发差异

### 4.1 主线程（Main Thread）

完全跟随上述会话级开关。交互式 CLI 主线程使用 Task V2；非交互式主线程使用 TodoWrite V1。

### 4.2 同步 Subagent

通过 `runAgent` 启动的**同步**子 agent（`isAsync = false`）继承父会话的 `resolvedTools`，因此：
- 父是 V2 → 子 agent 也能调用 Task 工具
- 父是 V1 → 子 agent 也能调用 `TodoWrite`

但 V1 模式下子 agent 的 todo 数据通过 `agentId` 做 key 隔离：

**文件**: `src/tools/TodoWriteTool/TodoWriteTool.ts`  
**行号**: `66-68`

```typescript
const todoKey = context.agentId ?? getSessionId()
const oldTodos = appState.todos[todoKey] ?? []
```

这意味着主线程和子 agent 拥有**独立的内存槽位**（`appState.todos[sessionId]` vs `appState.todos[agentId]`）。

### 4.3 普通异步 Subagent（Background Agent）

异步 subagent 的工具会经过 `filterToolsForAgent` 过滤。

**文件**: `src/tools/AgentTool/agentToolUtils.ts`  
**行号**: `70-116`

```typescript
export function filterToolsForAgent({ tools, isBuiltIn, isAsync = false, permissionMode }): Tools {
  return tools.filter(tool => {
    // ...
    if (isAsync && !ASYNC_AGENT_ALLOWED_TOOLS.has(tool.name)) {
      // in-process teammate 有额外放行逻辑
      return false
    }
    return true
  })
}
```

**文件**: `src/constants/tools.ts`  
**行号**: `55-71`

```typescript
export const ASYNC_AGENT_ALLOWED_TOOLS = new Set([
  FILE_READ_TOOL_NAME,
  // ...
  TODO_WRITE_TOOL_NAME,  // V1 工具在允许列表中
  // 注意：Task V2 四件套不在此集合中！
])
```

- **V1 模式**：异步 subagent 可用 `TodoWrite`（内存）
- **V2 模式**：普通异步 subagent **没有任务管理工具**（Task 工具被过滤掉了）

### 4.4 In-Process Teammate（Agent Swarm）—— 强制 V2

这是最特殊的一类。`inProcessRunner.ts` 在构造 agent definition 时**显式注入** Task V2 四件套：

**文件**: `src/utils/swarm/inProcessRunner.ts`  
**行号**: `982-995`

```typescript
const resolvedAgentDefinition: CustomAgentDefinition = {
  // ...
  tools: agentDefinition?.tools
    ? [
        ...new Set([
          ...agentDefinition.tools,
          SEND_MESSAGE_TOOL_NAME,
          TEAM_CREATE_TOOL_NAME,
          TEAM_DELETE_TOOL_NAME,
          TASK_CREATE_TOOL_NAME,
          TASK_GET_TOOL_NAME,
          TASK_LIST_TOOL_NAME,
          TASK_UPDATE_TOOL_NAME,
        ]),
      ]
    : ['*'],
  // ...
}
```

同时 `filterToolsForAgent` 对 in-process teammate 有特殊放行：

**文件**: `src/tools/AgentTool/agentToolUtils.ts`  
**行号**: `100-111`

```typescript
if (isAgentSwarmsEnabled() && isInProcessTeammate()) {
  if (toolMatchesName(tool, AGENT_TOOL_NAME)) {
    return true
  }
  if (IN_PROCESS_TEAMMATE_ALLOWED_TOOLS.has(tool.name)) {
    return true  // 此处包含 Task V2 工具
  }
}
```

**文件**: `src/constants/tools.ts`  
**行号**: `77-88`

```typescript
export const IN_PROCESS_TEAMMATE_ALLOWED_TOOLS = new Set([
  TASK_CREATE_TOOL_NAME,
  TASK_GET_TOOL_NAME,
  TASK_LIST_TOOL_NAME,
  TASK_UPDATE_TOOL_NAME,
  SEND_MESSAGE_TOOL_NAME,
  // ...
])
```

因此**无论主会话处于 V1 还是 V2 模式**，in-process teammate 都**强制使用 Task V2**，通过磁盘文件与 leader 共享任务列表、抢任务（`claimTask`）、更新进度。

 teammate 启动后立即尝试 claim 任务：

**文件**: `src/utils/swarm/inProcessRunner.ts`  
**行号**: `1015-1019`

```typescript
// Try to claim an available task immediately so the UI can show activity
// from the very start.
await tryClaimNextTask(identity.parentSessionId, identity.agentName)
```

---

## 5. Todo V1 架构详解

### 5.1 数据模型

**文件**: `src/utils/todo/types.ts`  
**行号**: `4-18`

```typescript
const TodoStatusSchema = lazySchema(() =>
  z.enum(['pending', 'in_progress', 'completed']),
)

export const TodoItemSchema = lazySchema(() =>
  z.object({
    content: z.string().min(1, 'Content cannot be empty'),
    status: TodoStatusSchema(),
    activeForm: z.string().min(1, 'Active form cannot be empty'),
  }),
)

export type TodoItem = z.infer<ReturnType<typeof TodoItemSchema>>
export const TodoListSchema = lazySchema(() => z.array(TodoItemSchema()))
```

### 5.2 存储与更新逻辑

**文件**: `src/tools/TodoWriteTool/TodoWriteTool.ts`  
**行号**: `65-94`

```typescript
async call({ todos }, context) {
  const appState = context.getAppState()
  const todoKey = context.agentId ?? getSessionId()
  const oldTodos = appState.todos[todoKey] ?? []
  const allDone = todos.every(_ => _.status === 'completed')
  const newTodos = allDone ? [] : todos  // 全部完成时清空列表

  context.setAppState(prev => ({
    ...prev,
    todos: {
      ...prev.todos,
      [todoKey]: newTodos,
    },
  }))

  return {
    data: { oldTodos, newTodos: todos, verificationNudgeNeeded },
  }
}
```

### 5.3 内存存储位置

**文件**: `src/state/AppStateStore.ts`  
**行号**: `220`

```typescript
todos: { [agentId: string]: TodoList }
```

### 5.4 会话恢复

**文件**: `src/utils/sessionRestore.ts`  
**行号**: `138-149`

```typescript
// Restore TodoWrite state from transcript (SDK/non-interactive only).
// Interactive mode uses file-backed v2 tasks, so AppState.todos is unused there.
if (!isTodoV2Enabled() && result.messages && result.messages.length > 0) {
  const todos = extractTodosFromTranscript(result.messages)
  if (todos.length > 0) {
    const agentId = getSessionId()
    setAppState(prev => ({
      ...prev,
      todos: { ...prev.todos, [agentId]: todos },
    }))
  }
}
```

- **V1 模式恢复**：从历史消息里提取最后一次 `TodoWrite` 的内容，写回内存 `AppState.todos`
- **V2 模式恢复**：不需要，任务数据已经在磁盘 JSON 里

---

## 6. Task V2 架构详解

### 6.1 数据模型

**文件**: `src/utils/tasks.ts`  
**行号**: `76-89`

```typescript
export const TaskSchema = lazySchema(() =>
  z.object({
    id: z.string(),
    subject: z.string(),
    description: z.string(),
    activeForm: z.string().optional(),
    owner: z.string().optional(),     // agent ID / teammate name
    status: TaskStatusSchema(),
    blocks: z.array(z.string()),      // 阻塞哪些任务
    blockedBy: z.array(z.string()),   // 被哪些任务阻塞
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
)
```

### 6.2 文件系统存储布局

**文件**: `src/utils/tasks.ts`  
**行号**: `221-227` / `229-231`

```typescript
export function getTasksDir(taskListId: string): string {
  return join(
    getClaudeConfigHomeDir(),
    'tasks',
    sanitizePathComponent(taskListId),
  )
}

export function getTaskPath(taskListId: string, taskId: string): string {
  return join(getTasksDir(taskListId), `${sanitizePathComponent(taskId)}.json`)
}
```

实际路径：

```
~/.claude/
└── tasks/
    └── {taskListId}/
        ├── 1.json
        ├── 2.json
        ├── .highwatermark    // 最高ID水位标记
        └── .lock             // 列表级锁文件
```

### 6.3 任务列表 ID 解析

**文件**: `src/utils/tasks.ts`  
**行号**: `199-210`

```typescript
export function getTaskListId(): string {
  if (process.env.CLAUDE_CODE_TASK_LIST_ID) {
    return process.env.CLAUDE_CODE_TASK_LIST_ID
  }
  const teammateCtx = getTeammateContext()
  if (teammateCtx) {
    return teammateCtx.teamName
  }
  return getTeamName() || leaderTeamName || getSessionId()
}
```

优先级：
1. `CLAUDE_CODE_TASK_LIST_ID` 环境变量
2. In-process teammate 的 `teamName`
3. `CLAUDE_CODE_TEAM_NAME` 环境变量
4. Leader 设置的 `leaderTeamName`
5. 默认 `sessionId`

### 6.4 并发控制与文件锁

**文件**: `src/utils/lockfile.ts`  
**行号**: `1-43`

这是 `proper-lockfile` 的懒加载包装器，避免启动时加载开销。

**文件**: `src/utils/tasks.ts`  
**行号**: `94-108`

```typescript
const LOCK_OPTIONS = {
  retries: {
    retries: 30,
    minTimeout: 5,
    maxTimeout: 100,
  },
}
```

创建任务时使用**列表级锁**：

**文件**: `src/utils/tasks.ts`  
**行号**: `284-308`

```typescript
export async function createTask(taskListId: string, taskData: Omit<Task, 'id'>): Promise<string> {
  const lockPath = await ensureTaskListLockFile(taskListId)
  let release: (() => Promise<void>) | undefined
  try {
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)
    const highestId = await findHighestTaskId(taskListId)
    const id = String(highestId + 1)
    const task: Task = { id, ...taskData }
    await writeFile(getTaskPath(taskListId, id), jsonStringify(task, null, 2))
    notifyTasksUpdated()
    return id
  } finally {
    if (release) await release()
  }
}
```

更新任务时使用**任务级锁**：

**文件**: `src/utils/tasks.ts`  
**行号**: `370-391`

```typescript
export async function updateTask(taskListId: string, taskId: string, updates: Partial<Omit<Task, 'id'>>): Promise<Task | null> {
  const path = getTaskPath(taskListId, taskId)
  const taskBeforeLock = await getTask(taskListId, taskId)
  if (!taskBeforeLock) return null

  let release: (() => Promise<void>) | undefined
  try {
    release = await lockfile.lock(path, LOCK_OPTIONS)
    return await updateTaskUnsafe(taskListId, taskId, updates)
  } finally {
    await release?.()
  }
}
```

### 6.5 任务抢占（Claim Task）

**文件**: `src/utils/tasks.ts`  
**行号**: `541-612`

```typescript
export async function claimTask(
  taskListId: string,
  taskId: string,
  claimantAgentId: string,
  options: ClaimTaskOptions = {},
): Promise<ClaimTaskResult> {
  // 1. 检查任务是否存在
  // 2. 是否已被其他代理声明
  // 3. 是否已完成
  // 4. 是否有未解决的阻塞任务
  // 5. （可选）代理是否已忙碌（checkAgentBusy）
  // 使用任务级锁或列表级锁保证原子性
}
```

带 `checkAgentBusy` 的原子抢占：

**文件**: `src/utils/tasks.ts`  
**行号**: `618-692`

```typescript
async function claimTaskWithBusyCheck(...): Promise<ClaimTaskResult> {
  const lockPath = await ensureTaskListLockFile(taskListId)
  let release: (() => Promise<void>) | undefined
  try {
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)
    // 在锁保护下读取所有任务并原子性判断 busy 状态
    // ...
  } finally {
    if (release) await release()
  }
}
```

---

## 7. Task V2 工具详解

### 7.1 TaskCreateTool

**文件**: `src/tools/TaskCreateTool/TaskCreateTool.ts`  
**行号**: `18-33`

```typescript
const inputSchema = lazySchema(() =>
  z.strictObject({
    subject: z.string().describe('A brief title for the task'),
    description: z.string().describe('What needs to be done'),
    activeForm: z.string().optional().describe('Present continuous form shown in spinner when in_progress'),
    metadata: z.record(z.string(), z.unknown()).optional().describe('Arbitrary metadata to attach to the task'),
  }),
)
```

创建流程（**文件**同前，**行号** `80-129`）：
1. 生成任务ID（自增）
2. 执行 `executeTaskCreatedHooks`
3. 如果 hooks 返回阻塞错误，调用 `deleteTask` 回滚并抛出异常
4. 自动将 `expandedView` 设为 `'tasks'`，展开 UI 面板

### 7.2 TaskUpdateTool

**文件**: `src/tools/TaskUpdateTool/TaskUpdateTool.ts`  
**行号**: `33-66`

```typescript
const inputSchema = lazySchema(() => {
  const TaskUpdateStatusSchema = TaskStatusSchema().or(z.literal('deleted'))
  return z.strictObject({
    taskId: z.string(),
    subject: z.string().optional(),
    description: z.string().optional(),
    activeForm: z.string().optional(),
    status: TaskUpdateStatusSchema.optional(),  // 'deleted' 表示物理删除
    addBlocks: z.array(z.string()).optional(),
    addBlockedBy: z.array(z.string()).optional(),
    owner: z.string().optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
  })
})
```

特殊逻辑（**文件**同前，**行号** `123-363`）：
- `status === 'deleted'` 时调用 `deleteTask` 物理删除文件
- 自动清理已解决任务的阻塞关系（`TaskListTool` 中过滤）
- `status === 'completed'` 时执行 `TaskCompleted hooks`
- 更改 `owner` 时通过 `writeToMailbox` 通知新所有者
- In-process teammate 将 `in_progress` 状态自动设置 `owner` 为自己

### 7.3 TaskListTool

**文件**: `src/tools/TaskListTool/TaskListTool.ts`  
**行号**: `65-90`

```typescript
async call() {
  const taskListId = getTaskListId()
  const allTasks = (await listTasks(taskListId)).filter(
    t => !t.metadata?._internal  // 过滤内部任务
  )

  const resolvedTaskIds = new Set(
    allTasks.filter(t => t.status === 'completed').map(t => t.id),
  )

  const tasks = allTasks.map(task => ({
    id: task.id,
    subject: task.subject,
    status: task.status,
    owner: task.owner,
    blockedBy: task.blockedBy.filter(id => !resolvedTaskIds.has(id)),  // 已完成的不算阻塞
  }))

  return { data: { tasks } }
}
```

### 7.4 TaskGetTool

**文件**: `src/tools/TaskGetTool/TaskGetTool.ts`  
**行号**: `73-97`

获取单个任务的完整信息，包括 `blocks` 和 `blockedBy` 关系。

---

## 8. 催促/提醒机制（Nudge）

两套系统都有"LLM 太久没更新任务就提醒"的机制，共享同一组阈值：

**文件**: `src/utils/attachments.ts`  
**行号**: `254-257`

```typescript
export const TODO_REMINDER_CONFIG = {
  TURNS_SINCE_WRITE: 10,
  TURNS_BETWEEN_REMINDERS: 10,
} as const
```

### 8.1 Todo V1 提醒

**文件**: `src/utils/attachments.ts`  
**行号**: `3266-3317`

```typescript
async function getTodoReminderAttachments(messages, toolUseContext): Promise<Attachment[]> {
  // 检查工具是否可用、是否处于 Brief 模式等
  const { turnsSinceLastTodoWrite, turnsSinceLastReminder } = getTodoReminderTurnCounts(messages)

  if (
    turnsSinceLastTodoWrite >= TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE &&
    turnsSinceLastReminder >= TODO_REMINDER_CONFIG.TURNS_BETWEEN_REMINDERS
  ) {
    const todoKey = toolUseContext.agentId ?? getSessionId()
    const appState = toolUseContext.getAppState()
    const todos = appState.todos[todoKey] ?? []
    return [{ type: 'todo_reminder', content: todos, itemCount: todos.length }]
  }
  return []
}
```

消息渲染：

**文件**: `src/utils/messages.ts`  
**行号**: `3663-3672`

```typescript
case 'todo_reminder': {
  let message = `The TodoWrite tool hasn't been used recently...`
  // 列出当前 todo 内容
}
```

### 8.2 Task V2 提醒

**文件**: `src/utils/attachments.ts`  
**行号**: `3375-3432`

```typescript
async function getTaskReminderAttachments(messages, toolUseContext): Promise<Attachment[]> {
  if (!isTodoV2Enabled()) return []
  // ant 用户跳过
  if (process.env.USER_TYPE === 'ant') return []
  // Brief 模式跳过
  // ...
  const { turnsSinceLastTaskManagement, turnsSinceLastReminder } = getTaskReminderTurnCounts(messages)

  if (
    turnsSinceLastTaskManagement >= TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE &&
    turnsSinceLastReminder >= TODO_REMINDER_CONFIG.TURNS_BETWEEN_REMINDERS
  ) {
    const tasks = await listTasks(getTaskListId())
    return [{ type: 'task_reminder', content: tasks, itemCount: tasks.length }]
  }
  return []
}
```

消息渲染：

**文件**: `src/utils/messages.ts`  
**行号**: `3680-3699`

```typescript
case 'task_reminder': {
  let message = `The task tools haven't been used recently...`
  // 列出当前 tasks
}
```

---

## 9. 验证代理集成（Verification Nudge）

当启用 `VERIFICATION_AGENT` 功能时，如果主线程 agent 完成了 3+ 个任务且其中没有验证步骤，会在工具结果中追加提醒。

### Todo V1 中的实现

**文件**: `src/tools/TodoWriteTool/TodoWriteTool.ts`  
**行号**: `76-86`

```typescript
if (
  feature('VERIFICATION_AGENT') &&
  getFeatureValue_CACHED_MAY_BE_STALE('tengu_hive_evidence', false) &&
  !context.agentId &&      // 仅主线程
  allDone &&
  todos.length >= 3 &&
  !todos.some(t => /verif/i.test(t.content))
) {
  verificationNudgeNeeded = true
}
```

### Task V2 中的实现

**文件**: `src/tools/TaskUpdateTool/TaskUpdateTool.ts`  
**行号**: `333-349`

```typescript
if (
  feature('VERIFICATION_AGENT') &&
  getFeatureValue_CACHED_MAY_BE_STALE('tengu_hive_evidence', false) &&
  !context.agentId &&           // 仅主线程
  updates.status === 'completed'
) {
  const allTasks = await listTasks(taskListId)
  const allDone = allTasks.every(t => t.status === 'completed')
  if (
    allDone &&
    allTasks.length >= 3 &&
    !allTasks.some(t => /verif/i.test(t.subject))
  ) {
    verificationNudgeNeeded = true
  }
}
```

---

## 10. 团队集成

### 10.1 任务列表共享

Leader 创建团队时设置团队名：

**文件**: `src/utils/tasks.ts`  
**行号**: `25-37`

```typescript
let leaderTeamName: string | undefined

export function setLeaderTeamName(teamName: string): void {
  if (leaderTeamName === teamName) return
  leaderTeamName = teamName
  notifyTasksUpdated()
}
```

### 10.2 代理状态跟踪

**文件**: `src/utils/tasks.ts`  
**行号**: `763-798`

```typescript
export async function getAgentStatuses(teamName: string): Promise<AgentStatus[] | null> {
  const teamData = await readTeamMembers(teamName)
  if (!teamData) return null

  const taskListId = sanitizeName(teamName)
  const allTasks = await listTasks(taskListId)

  const unresolvedTasksByOwner = new Map<string, string[]>()
  for (const task of allTasks) {
    if (task.status !== 'completed' && task.owner) {
      const existing = unresolvedTasksByOwner.get(task.owner) || []
      existing.push(task.id)
      unresolvedTasksByOwner.set(task.owner, existing)
    }
  }

  return teamData.members.map(member => {
    const tasksByName = unresolvedTasksByOwner.get(member.name) || []
    const tasksById = unresolvedTasksByOwner.get(member.agentId) || []
    const currentTasks = uniq([...tasksByName, ...tasksById])
    return {
      agentId: member.agentId,
      name: member.name,
      agentType: member.agentType,
      status: currentTasks.length === 0 ? 'idle' : 'busy',
      currentTasks,
    }
  })
}
```

### 10.3 团队成员退出处理

**文件**: `src/utils/tasks.ts`  
**行号**: `818-860`

```typescript
export async function unassignTeammateTasks(
  teamName: string,
  teammateId: string,
  teammateName: string,
  reason: 'terminated' | 'shutdown',
): Promise<UnassignTasksResult> {
  const tasks = await listTasks(teamName)
  const unresolvedAssignedTasks = tasks.filter(
    t => t.status !== 'completed' && (t.owner === teammateId || t.owner === teammateName)
  )

  for (const task of unresolvedAssignedTasks) {
    await updateTask(teamName, task.id, { owner: undefined, status: 'pending' })
  }
  // ...
}
```

---

## 11. 与 AppState 的关系（第三套系统的区分）

**注意**：`AppState.tasks` 是运行时后台任务状态机（LocalShellTask、LocalAgentTask 等），与 LLM 通过 Task V2 工具操作的 "Task" 是完全不同的概念。

**文件**: `src/state/AppStateStore.ts`  
**行号**: `159-165`

```typescript
type AppState = DeepImmutable<{
  // ...
}> & {
  // Unified task state - 运行时任务（后台 bash、子代理等）
  tasks: { [taskId: string]: TaskState }
  // ...
  todos: { [agentId: string]: TodoList }  // Todo V1 专用
}
```

**文件**: `src/tasks/types.ts`  
**行号**: `12-20`

```typescript
export type TaskState =
  | LocalShellTaskState
  | LocalAgentTaskState
  | RemoteAgentTaskState
  | InProcessTeammateTaskState
  | LocalWorkflowTaskState
  | MonitorMcpTaskState
  | DreamTaskState
```

---

## 12. 总结

| 特性 | Todo V1 | Task V2 |
|------|---------|---------|
| **存储** | 内存 (`AppState.todos`) | 文件系统 (`~/.claude/tasks/`) |
| **持久化** | 会话级，不跨会话 | 跨会话保留 |
| **并发控制** | 单进程，无锁 | 文件锁 (`proper-lockfile`) |
| **团队支持** | 无 | 完整支持（claim / owner / mailbox） |
| **依赖关系** | 无 | `blocks` / `blockedBy` |
| **所有权** | 无 | `owner` 字段 |
| **Hooks** | 无 | `TaskCreated` / `TaskCompleted` |
| **LLM 工具** | `TodoWrite` | `TaskCreate/Get/List/Update` |
| **主开关** | `!isTodoV2Enabled()` | `isTodoV2Enabled()` |
| **触发条件** | 非交互式 / headless / SDK | 交互式 TTY 启动 |
| **提醒阈值** | 10 轮未调用 `TodoWrite` | 10 轮未调用 `TaskCreate/Update` |
| **in-process teammate** | 强制禁用 | **强制启用**（硬编码注入） |

---

## 附录：关键代码速查表

| 功能 | 文件 | 行号范围 |
|------|------|---------|
| V2 开关 | `src/utils/tasks.ts` | `133-139` |
| 交互式判定 | `src/main.tsx` | `797-812` |
| 工具列表组装 | `src/tools.ts` | `208-220` |
| TodoWrite 自过滤 | `src/tools/TodoWriteTool/TodoWriteTool.ts` | `51-54` |
| TaskCreate 自过滤 | `src/tools/TaskCreateTool/TaskCreateTool.ts` | `67-70` |
| 异步 agent 工具过滤 | `src/tools/AgentTool/agentToolUtils.ts` | `70-116` |
| ASYNC_AGENT 允许列表 | `src/constants/tools.ts` | `55-71` |
| In-process teammate 注入 | `src/utils/swarm/inProcessRunner.ts` | `982-995` |
| In-process teammate 放行 | `src/constants/tools.ts` | `77-88` |
| Todo 数据模型 | `src/utils/todo/types.ts` | `4-18` |
| Todo 更新逻辑 | `src/tools/TodoWriteTool/TodoWriteTool.ts` | `65-94` |
| AppState.todos 定义 | `src/state/AppStateStore.ts` | `220` |
| V1 会话恢复 | `src/utils/sessionRestore.ts` | `138-149` |
| Task 数据模型 | `src/utils/tasks.ts` | `76-89` |
| 任务目录/路径 | `src/utils/tasks.ts` | `221-231` |
| getTaskListId | `src/utils/tasks.ts` | `199-210` |
| 锁配置 | `src/utils/tasks.ts` | `94-108` |
| createTask（列表级锁） | `src/utils/tasks.ts` | `284-308` |
| updateTask（任务级锁） | `src/utils/tasks.ts` | `370-391` |
| claimTask | `src/utils/tasks.ts` | `541-612` |
| claimTaskWithBusyCheck | `src/utils/tasks.ts` | `618-692` |
| blockTask | `src/utils/tasks.ts` | `458-486` |
| TaskUpdateTool | `src/tools/TaskUpdateTool/TaskUpdateTool.ts` | `33-363` |
| 提醒阈值配置 | `src/utils/attachments.ts` | `254-257` |
| Todo 提醒逻辑 | `src/utils/attachments.ts` | `3266-3317` |
| Task 提醒逻辑 | `src/utils/attachments.ts` | `3375-3432` |
| Todo 提醒渲染 | `src/utils/messages.ts` | `3663-3672` |
| Task 提醒渲染 | `src/utils/messages.ts` | `3680-3699` |
| getAgentStatuses | `src/utils/tasks.ts` | `763-798` |
| unassignTeammateTasks | `src/utils/tasks.ts` | `818-860` |
