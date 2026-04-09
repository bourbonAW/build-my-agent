# Claude Code Task/Todo 实现细节

## 1. 核心数据类型定义

### 1.1 Task V2 任务类型

```typescript
// src/utils/tasks.ts

export const TASK_STATUSES = ['pending', 'in_progress', 'completed'] as const

export const TaskStatusSchema = lazySchema(() =>
  z.enum(['pending', 'in_progress', 'completed']),
)
export type TaskStatus = z.infer<ReturnType<typeof TaskStatusSchema>>

export const TaskSchema = lazySchema(() =>
  z.object({
    id: z.string(),
    subject: z.string(),
    description: z.string(),
    activeForm: z.string().optional(),  // 进行时显示形式
    owner: z.string().optional(),       // 代理所有者
    status: TaskStatusSchema(),
    blocks: z.array(z.string()),        // 阻塞的任务ID
    blockedBy: z.array(z.string()),     // 被谁阻塞
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
)
export type Task = z.infer<ReturnType<typeof TaskSchema>>
```

### 1.2 Todo V1 类型

```typescript
// src/utils/todo/types.ts

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
export type TodoList = z.infer<ReturnType<typeof TodoListSchema>>
```

### 1.3 Runtime Task 类型

```typescript
// src/Task.ts

export type TaskType =
  | 'local_bash'
  | 'local_agent'
  | 'remote_agent'
  | 'in_process_teammate'
  | 'local_workflow'
  | 'monitor_mcp'
  | 'dream'

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'killed'

export function isTerminalTaskStatus(status: TaskStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'killed'
}

export type TaskStateBase = {
  id: string
  type: TaskType
  status: TaskStatus
  description: string
  toolUseId?: string
  startTime: number
  endTime?: number
  totalPausedMs?: number
  outputFile: string
  outputOffset: number
  notified: boolean
}
```

## 2. 任务列表ID解析

```typescript
// src/utils/tasks.ts

/**
 * Gets the task list ID based on the current context.
 * Priority:
 * 1. CLAUDE_CODE_TASK_LIST_ID - explicit task list ID
 * 2. In-process teammate: leader's team name
 * 3. CLAUDE_CODE_TEAM_NAME - set when running as a process-based teammate
 * 4. Leader team name - set when the leader creates a team via TeamCreate
 * 5. Session ID - fallback for standalone sessions
 */
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
  
  // 3. 环境变量中的团队名（进程外队友）
  // 4. Leader 设置的团队名
  // 5. 默认使用 sessionId
  return getTeamName() || leaderTeamName || getSessionId()
}

/**
 * Team name set by the leader when creating a team.
 */
let leaderTeamName: string | undefined

export function setLeaderTeamName(teamName: string): void {
  if (leaderTeamName === teamName) return
  leaderTeamName = teamName
  notifyTasksUpdated()
}

export function clearLeaderTeamName(): void {
  if (leaderTeamName === undefined) return
  leaderTeamName = undefined
  notifyTasksUpdated()
}
```

## 3. 文件路径和目录管理

```typescript
// src/utils/tasks.ts

/**
 * Sanitizes a string for safe use in file paths.
 * Only allows alphanumeric characters, hyphens, and underscores.
 */
export function sanitizePathComponent(input: string): string {
  return input.replace(/[^a-zA-Z0-9_-]/g, '-')
}

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

export async function ensureTasksDir(taskListId: string): Promise<void> {
  const dir = getTasksDir(taskListId)
  try {
    await mkdir(dir, { recursive: true })
  } catch {
    // Directory already exists or creation failed
  }
}
```

## 4. 高水位标记管理

```typescript
// src/utils/tasks.ts

const HIGH_WATER_MARK_FILE = '.highwatermark'

/**
 * Finds the highest task ID ever assigned, considering both existing files
 * and the high water mark (for deleted/reset tasks).
 */
async function findHighestTaskId(taskListId: string): Promise<number> {
  const [fromFiles, fromMark] = await Promise.all([
    findHighestTaskIdFromFiles(taskListId),
    readHighWaterMark(taskListId),
  ])
  return Math.max(fromFiles, fromMark)
}

async function readHighWaterMark(taskListId: string): Promise<number> {
  const path = getHighWaterMarkPath(taskListId)
  try {
    const content = (await readFile(path, 'utf-8')).trim()
    const value = parseInt(content, 10)
    return isNaN(value) ? 0 : value
  } catch {
    return 0
  }
}

async function writeHighWaterMark(taskListId: string, value: number): Promise<void> {
  const path = getHighWaterMarkPath(taskListId)
  await writeFile(path, String(value))
}

/**
 * Reset task list - clears existing tasks but preserves high water mark
 * to prevent ID reuse.
 */
export async function resetTaskList(taskListId: string): Promise<void> {
  const dir = getTasksDir(taskListId)
  const lockPath = await ensureTaskListLockFile(taskListId)

  let release: (() => Promise<void>) | undefined
  try {
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)

    // Save current highest ID to high water mark
    const currentHighest = await findHighestTaskIdFromFiles(taskListId)
    if (currentHighest > 0) {
      const existingMark = await readHighWaterMark(taskListId)
      if (currentHighest > existingMark) {
        await writeHighWaterMark(taskListId, currentHighest)
      }
    }

    // Delete all task files
    const files = await readdir(dir).catch(() => [])
    for (const file of files) {
      if (file.endsWith('.json') && !file.startsWith('.')) {
        await unlink(join(dir, file)).catch(() => {})
      }
    }
    notifyTasksUpdated()
  } finally {
    if (release) await release()
  }
}
```

## 5. 文件锁实现

```typescript
// src/utils/tasks.ts

// Lock options: retry with backoff for concurrent callers
const LOCK_OPTIONS = {
  retries: {
    retries: 30,        // ~10+ concurrent swarm agents
    minTimeout: 5,      // 5ms initial
    maxTimeout: 100,    // 100ms max
  },
}

function getTaskListLockPath(taskListId: string): string {
  return join(getTasksDir(taskListId), '.lock')
}

async function ensureTaskListLockFile(taskListId: string): Promise<string> {
  await ensureTasksDir(taskListId)
  const lockPath = getTaskListLockPath(taskListId)
  // Create with 'wx' flag (write-exclusive) so concurrent callers
  // don't both create it
  try {
    await writeFile(lockPath, '', { flag: 'wx' })
  } catch {
    // File already exists
  }
  return lockPath
}
```

## 6. 核心 CRUD 操作

### 6.1 创建任务

```typescript
export async function createTask(
  taskListId: string,
  taskData: Omit<Task, 'id'>,
): Promise<string> {
  const lockPath = await ensureTaskListLockFile(taskListId)

  let release: (() => Promise<void>) | undefined
  try {
    // Acquire exclusive lock
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)

    // Read highest ID while holding lock
    const highestId = await findHighestTaskId(taskListId)
    const id = String(highestId + 1)
    
    const task: Task = { id, ...taskData }
    const path = getTaskPath(taskListId, id)
    await writeFile(path, jsonStringify(task, null, 2))
    
    notifyTasksUpdated()
    return id
  } finally {
    if (release) await release()
  }
}
```

### 6.2 读取任务

```typescript
export async function getTask(
  taskListId: string,
  taskId: string,
): Promise<Task | null> {
  const path = getTaskPath(taskListId, taskId)
  try {
    const content = await readFile(path, 'utf-8')
    const data = jsonParse(content) as { status?: string }

    // Migration for old status names
    if (process.env.USER_TYPE === 'ant') {
      if (data.status === 'open') data.status = 'pending'
      else if (data.status === 'resolved') data.status = 'completed'
      else if (['planning', 'implementing', 'reviewing', 'verifying']
        .includes(data.status || '')) {
        data.status = 'in_progress'
      }
    }
    
    const parsed = TaskSchema().safeParse(data)
    if (!parsed.success) {
      logForDebugging(`[Tasks] Task ${taskId} failed validation: ${parsed.error.message}`)
      return null
    }
    return parsed.data
  } catch (e) {
    if (getErrnoCode(e) === 'ENOENT') return null
    logError(e)
    return null
  }
}

export async function listTasks(taskListId: string): Promise<Task[]> {
  const dir = getTasksDir(taskListId)
  let files: string[]
  try {
    files = await readdir(dir)
  } catch {
    return []
  }
  
  const taskIds = files
    .filter(f => f.endsWith('.json'))
    .map(f => f.replace('.json', ''))
  
  const results = await Promise.all(
    taskIds.map(id => getTask(taskListId, id))
  )
  return results.filter((t): t is Task => t !== null)
}
```

### 6.3 更新任务

```typescript
// Internal: no lock - for callers already holding a lock
async function updateTaskUnsafe(
  taskListId: string,
  taskId: string,
  updates: Partial<Omit<Task, 'id'>>,
): Promise<Task | null> {
  const existing = await getTask(taskListId, taskId)
  if (!existing) return null
  
  const updated: Task = { ...existing, ...updates, id: taskId }
  const path = getTaskPath(taskListId, taskId)
  await writeFile(path, jsonStringify(updated, null, 2))
  notifyTasksUpdated()
  return updated
}

export async function updateTask(
  taskListId: string,
  taskId: string,
  updates: Partial<Omit<Task, 'id'>>,
): Promise<Task | null> {
  const path = getTaskPath(taskListId, taskId)

  // Check existence before locking
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

### 6.4 删除任务

```typescript
export async function deleteTask(
  taskListId: string,
  taskId: string,
): Promise<boolean> {
  const path = getTaskPath(taskListId, taskId)

  try {
    // Update high water mark before deleting
    const numericId = parseInt(taskId, 10)
    if (!isNaN(numericId)) {
      const currentMark = await readHighWaterMark(taskListId)
      if (numericId > currentMark) {
        await writeHighWaterMark(taskListId, numericId)
      }
    }

    // Delete task file
    try {
      await unlink(path)
    } catch (e) {
      if (getErrnoCode(e) === 'ENOENT') return false
      throw e
    }

    // Remove references from other tasks
    const allTasks = await listTasks(taskListId)
    for (const task of allTasks) {
      const newBlocks = task.blocks.filter(id => id !== taskId)
      const newBlockedBy = task.blockedBy.filter(id => id !== taskId)
      if (newBlocks.length !== task.blocks.length ||
          newBlockedBy.length !== task.blockedBy.length) {
        await updateTask(taskListId, task.id, {
          blocks: newBlocks,
          blockedBy: newBlockedBy,
        })
      }
    }

    notifyTasksUpdated()
    return true
  } catch {
    return false
  }
}
```

## 7. 阻塞关系管理

```typescript
export async function blockTask(
  taskListId: string,
  fromTaskId: string,   // A
  toTaskId: string,     // B
): Promise<boolean> {
  const [fromTask, toTask] = await Promise.all([
    getTask(taskListId, fromTaskId),
    getTask(taskListId, toTaskId),
  ])
  if (!fromTask || !toTask) return false

  // A blocks B:
  // - fromTask.blocks 添加 toTaskId (A 阻塞 B)
  // - toTask.blockedBy 添加 fromTaskId (B 被 A 阻塞)
  
  if (!fromTask.blocks.includes(toTaskId)) {
    await updateTask(taskListId, fromTaskId, {
      blocks: [...fromTask.blocks, toTaskId],
    })
  }

  if (!toTask.blockedBy.includes(fromTaskId)) {
    await updateTask(taskListId, toTaskId, {
      blockedBy: [...toTask.blockedBy, fromTaskId],
    })
  }

  return true
}
```

## 8. 任务抢占实现

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
  busyWithTasks?: string[]
  blockedByTasks?: string[]
}

export async function claimTask(
  taskListId: string,
  taskId: string,
  claimantAgentId: string,
  options: { checkAgentBusy?: boolean } = {},
): Promise<ClaimTaskResult> {
  if (options.checkAgentBusy) {
    return claimTaskWithBusyCheck(taskListId, taskId, claimantAgentId)
  }
  // ... task-level lock implementation
}

async function claimTaskWithBusyCheck(
  taskListId: string,
  taskId: string,
  claimantAgentId: string,
): Promise<ClaimTaskResult> {
  const lockPath = await ensureTaskListLockFile(taskListId)

  let release: (() => Promise<void>) | undefined
  try {
    // Acquire list-level lock for atomic busy check
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)

    // Read all tasks atomically
    const allTasks = await listTasks(taskListId)
    const task = allTasks.find(t => t.id === taskId)
    
    if (!task) return { success: false, reason: 'task_not_found' }
    if (task.owner && task.owner !== claimantAgentId) {
      return { success: false, reason: 'already_claimed', task }
    }
    if (task.status === 'completed') {
      return { success: false, reason: 'already_resolved', task }
    }

    // Check for unresolved blockers
    const unresolvedTaskIds = new Set(
      allTasks.filter(t => t.status !== 'completed').map(t => t.id)
    )
    const blockedByTasks = task.blockedBy.filter(id => unresolvedTaskIds.has(id))
    if (blockedByTasks.length > 0) {
      return { success: false, reason: 'blocked', task, blockedByTasks }
    }

    // Check if agent is busy with other unresolved tasks
    const agentOpenTasks = allTasks.filter(
      t => t.status !== 'completed' &&
           t.owner === claimantAgentId &&
           t.id !== taskId
    )
    if (agentOpenTasks.length > 0) {
      return {
        success: false,
        reason: 'agent_busy',
        task,
        busyWithTasks: agentOpenTasks.map(t => t.id),
      }
    }

    // Claim the task
    const updated = await updateTask(taskListId, taskId, {
      owner: claimantAgentId,
    })
    return { success: true, task: updated! }
  } finally {
    if (release) await release()
  }
}
```

## 9. 代理状态跟踪

```typescript
export type AgentStatus = {
  agentId: string
  name: string
  agentType?: string
  status: 'idle' | 'busy'
  currentTasks: string[]
}

export async function getAgentStatuses(
  teamName: string,
): Promise<AgentStatus[] | null> {
  const teamData = await readTeamMembers(teamName)
  if (!teamData) return null

  const taskListId = sanitizeName(teamName)
  const allTasks = await listTasks(taskListId)

  // Group unresolved tasks by owner
  const unresolvedTasksByOwner = new Map<string, string[]>()
  for (const task of allTasks) {
    if (task.status !== 'completed' && task.owner) {
      const existing = unresolvedTasksByOwner.get(task.owner) || []
      existing.push(task.id)
      unresolvedTasksByOwner.set(task.owner, existing)
    }
  }

  // Build status for each agent
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

## 10. 任务更新信号系统

```typescript
// src/utils/tasks.ts

const tasksUpdated = createSignal()

export const onTasksUpdated = tasksUpdated.subscribe

export function notifyTasksUpdated(): void {
  try {
    tasksUpdated.emit()
  } catch {
    // Ignore listener errors
  }
}
```

## 11. Todo V1 工具实现

```typescript
// src/tools/TodoWriteTool/TodoWriteTool.ts

export const TodoWriteTool = buildTool({
  name: TODO_WRITE_TOOL_NAME,
  isEnabled() { return !isTodoV2Enabled() },
  
  async call({ todos }, context) {
    const todoKey = context.agentId ?? getSessionId()
    const oldTodos = appState.todos[todoKey] ?? []
    const allDone = todos.every(_ => _.status === 'completed')
    const newTodos = allDone ? [] : todos

    // Verification nudge for VERIFICATION_AGENT feature
    let verificationNudgeNeeded = false
    if (
      feature('VERIFICATION_AGENT') &&
      !context.agentId &&
      allDone &&
      todos.length >= 3 &&
      !todos.some(t => /verif/i.test(t.content))
    ) {
      verificationNudgeNeeded = true
    }

    context.setAppState(prev => ({
      ...prev,
      todos: { ...prev.todos, [todoKey]: newTodos },
    }))

    return { data: { oldTodos, newTodos, verificationNudgeNeeded } }
  },
})
```

## 12. 功能标志切换

```typescript
// src/utils/tasks.ts

export function isTodoV2Enabled(): boolean {
  // Force-enable tasks in non-interactive mode
  if (isEnvTruthy(process.env.CLAUDE_CODE_ENABLE_TASKS)) {
    return true
  }
  // Interactive mode: enabled by default
  return !getIsNonInteractiveSession()
}
```

## 13. 工具注册

```typescript
// src/tools.ts

export function getAllBaseTools(): Tools {
  return [
    // ... other tools
    TodoWriteTool,  // V1 - 当 !isTodoV2Enabled() 时启用
    
    // V2 tools - 当 isTodoV2Enabled() 时启用
    ...(isTodoV2Enabled()
      ? [TaskCreateTool, TaskGetTool, TaskUpdateTool, TaskListTool]
      : []),
    // ... other tools
  ]
}
```

## 14. AppState 中的任务状态

```typescript
// src/state/AppStateStore.ts

type AppState = {
  // ... other fields
  
  // Unified task state for runtime tasks (background bash, agents, etc.)
  tasks: { [taskId: string]: TaskState }
  
  // Todo V1 checklist storage
  todos: { [agentId: string]: TodoList }
  
  // Task list UI state
  expandedView: 'none' | 'tasks' | 'teammates'
  foregroundedTaskId?: string
  viewingAgentTaskId?: string
  
  // ... other fields
}

function getDefaultAppState(): AppState {
  return {
    // ... other defaults
    tasks: {},
    todos: {},
    expandedView: 'none',
    // ... other defaults
  }
}
```

## 15. 关键设计决策

### 15.1 为什么选择文件系统存储？

| 需求 | 解决方案 |
|------|----------|
| 跨会话持久化 | 文件系统天然支持 |
| 多进程并发 | proper-lockfile 提供分布式锁 |
| 跨代理共享 | 统一的 taskListId 解析 |
| 可观察性 | 文件可直接查看和调试 |
| 崩溃恢复 | 文件状态独立于进程 |

### 15.2 为什么使用自增ID？

- **可读性**: `#1`, `#2` 比 UUID 更易读
- **排序**: 自然按创建时间排序
- **水位标记**: 防止删除后ID重用

### 15.3 为什么分离 blocks/blockedBy？

```typescript
// 双向引用设计
interface Task {
  blocks: string[]      // 我阻塞谁
  blockedBy: string[]   // 谁阻塞我
}

// 优点：
// 1. O(1) 查询阻塞关系
// 2. 无需遍历所有任务找依赖
// 3. 支持快速检查是否可以抢占
```

### 15.4 为什么需要两种锁？

| 锁类型 | 用途 | 粒度 |
|--------|------|------|
| 任务列表锁 (.lock) | createTask, claimTaskWithBusyCheck | 列表级 |
| 任务文件锁 (1.json) | updateTask, claimTask | 任务级 |

- **列表锁**: 需要读取/修改多个任务的操作
- **任务锁**: 只需修改单个任务的操作
