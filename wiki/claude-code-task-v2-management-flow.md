# Claude Code Task V2 管理流程深度解析

> **研究日期**: 2026-04-13  
> **代码基线**: Claude Code `main` 分支（`src/` 目录）  
> 本文档以代码级精度追踪 Task V2 的完整生命周期：从启用判定、LLM 工具调用、磁盘持久化、并发控制、UI 联动，到多 Agent 协作的自动化行为。

---

## 1. 核心设计哲学：LLM 主导 + 系统自动补充

Task V2 不是纯 LLM 自管理的系统。它的设计哲学是：

- **LLM 负责高层决策**：创建什么任务、更新什么状态、指定谁来做
- **系统负责底层协调**：并发安全、所有权管理、依赖清理、团队状态同步、UI 刷新、自动提醒

下面会详细列出哪些行为由 LLM 触发，哪些由系统自动执行。

---

## 2. 启用与触发时机

### 2.1 主开关判定

**文件**: `src/utils/tasks.ts`  
**行号**: `133-139`

```typescript
export function isTodoV2Enabled(): boolean {
  if (isEnvTruthy(process.env.CLAUDE_CODE_ENABLE_TASKS)) {
    return true
  }
  return !getIsNonInteractiveSession()
}
```

| 启动方式 | 结果 | 说明 |
|---------|------|------|
| 普通 TTY 交互式 `claude` | **启用 V2** | 默认行为 |
| `-p` / `--print` / `--init-only` / `--sdk-url` | 启用 V1 (`TodoWrite`) | 非交互式回退 |
| stdout 不是 TTY | 启用 V1 | CI/管道模式 |
| `CLAUDE_CODE_ENABLE_TASKS=1` | **强制启用 V2** | 环境变量覆盖一切 |

### 2.2 工具暴露机制

**文件**: `src/tools.ts`  
**行号**: `218-220`

```typescript
...(isTodoV2Enabled()
  ? [TaskCreateTool, TaskGetTool, TaskUpdateTool, TaskListTool]
  : []),
```

`TodoWriteTool` 的 `isEnabled()` 返回 `!isTodoV2Enabled()`，因此两套系统**互斥暴露给 LLM**。

### 2.3 In-Process Teammate 强制启用 V2

无论主会话是 V1 还是 V2，Agent Swarm 中的 in-process teammate 都被**硬编码注入** Task V2 四件套：

**文件**: `src/utils/swarm/inProcessRunner.ts`  
**行号**: `982-995`

```typescript
const resolvedAgentDefinition: CustomAgentDefinition = {
  // ...
  tools: agentDefinition?.tools
    ? [
        ...new Set([
          ...agentDefinition.tools,
          TASK_CREATE_TOOL_NAME,
          TASK_GET_TOOL_NAME,
          TASK_LIST_TOOL_NAME,
          TASK_UPDATE_TOOL_NAME,
        ]),
      ]
    : ['*'],
}
```

---

## 3. 数据模型与存储架构

### 3.1 数据模型

**文件**: `src/utils/tasks.ts`  
**行号**: `76-89`

```typescript
export const TaskSchema = z.object({
  id: z.string(),               // 数字字符串，自增
  subject: z.string(),          // 标题
  description: z.string(),      // 描述
  activeForm: z.string().optional(),
  owner: z.string().optional(), // 负责 agent 的名称
  status: z.enum(['pending', 'in_progress', 'completed']),
  blocks: z.array(z.string()),     // 阻塞哪些任务
  blockedBy: z.array(z.string()),  // 被哪些任务阻塞
  metadata: z.record(z.string(), z.unknown()).optional(),
})
```

### 3.2 文件系统布局

**文件**: `src/utils/tasks.ts`  
**行号**: `221-231`

```typescript
export function getTasksDir(taskListId: string): string {
  return join(getClaudeConfigHomeDir(), 'tasks', sanitizePathComponent(taskListId))
}

export function getTaskPath(taskListId: string, taskId: string): string {
  return join(getTasksDir(taskListId), `${sanitizePathComponent(taskId)}.json`)
}
```

实际目录结构：

```
~/.claude/tasks/{taskListId}/
├── 1.json              # 任务文件（JSON 格式）
├── 2.json
├── 3.json
├── .highwatermark      # 最高任务 ID 水位标记
└── .lock               # 列表级锁文件
```

### 3.3 任务列表 ID 解析

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
4. Leader 通过 `TeamCreateTool` 设置的 `leaderTeamName`
5. 默认 fallback 为当前 `sessionId`

---

## 4. 任务生命周期完整流程

### 4.1 创建任务（TaskCreateTool）

**文件**: `src/tools/TaskCreateTool/TaskCreateTool.ts`  
**行号**: `80-129`

流程：
1. LLM 调用 `TaskCreate`，提供 `subject` / `description` / `activeForm` / `metadata`
2. 系统调用 `createTask(getTaskListId(), taskData)`
3. `createTask` 获取**列表级锁**（`.lock` 文件），读取当前最高 ID，生成 `id = highestId + 1`
4. 将任务 JSON 写入磁盘
5. 调用 `notifyTasksUpdated()` 触发 UI 刷新
6. 返回新任务 ID 给 LLM

**底层实现**（`src/utils/tasks.ts:284-308`）：

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

#### 4.1.1 High Water Mark 机制

**文件**: `src/utils/tasks.ts`  
**行号**: `91-131`

为了防止任务删除后 ID 回退，系统维护 `.highwatermark` 文件：

```typescript
const HIGH_WATER_MARK_FILE = '.highwatermark'

async function readHighWaterMark(taskListId: string): Promise<number> { /* ... */ }
async function writeHighWaterMark(taskListId: string, value: number): Promise<void> { /* ... */ }

async function findHighestTaskId(taskListId: string): Promise<number> {
  const [fromFiles, fromMark] = await Promise.all([
    findHighestTaskIdFromFiles(taskListId),
    readHighWaterMark(taskListId),
  ])
  return Math.max(fromFiles, fromMark)
}
```

#### 4.1.2 TaskCreated Hooks

创建后，系统**自动**执行 hooks：

**文件**: `src/tools/TaskCreateTool/TaskCreateTool.ts`  
**行号**: `93-113`

```typescript
const generator = executeTaskCreatedHooks(taskId, subject, description, getAgentName(), getTeamName(), ...)
for await (const result of generator) {
  if (result.blockingError) {
    blockingErrors.push(getTaskCreatedHookMessage(result.blockingError))
  }
}

if (blockingErrors.length > 0) {
  await deleteTask(getTaskListId(), taskId)  // 自动回滚！
  throw new Error(blockingErrors.join('\n'))
}
```

如果 hook 返回阻塞错误，系统会**自动删除刚创建的任务**（回滚）。

### 4.2 读取任务（TaskGetTool / TaskListTool）

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
    blockedBy: task.blockedBy.filter(id => !resolvedTaskIds.has(id)), // 已完成的不算阻塞
  }))

  return { data: { tasks } }
}
```

**文件**: `src/tools/TaskGetTool/TaskGetTool.ts`  
**行号**: `73-97`

获取单个任务完整信息（包括 `blocks` 和 `blockedBy`）。

### 4.3 更新任务（TaskUpdateTool）

**文件**: `src/tools/TaskUpdateTool/TaskUpdateTool.ts`  
**行号**: `123-363`

这是 Task V2 中最复杂的环节，包含以下系统级自动行为：

#### (1) 自动展开任务列表面板

```typescript
context.setAppState(prev => {
  if (prev.expandedView === 'tasks') return prev
  return { ...prev, expandedView: 'tasks' as const }
})
```

#### (2) `deleted` 状态 = 物理删除

如果 LLM 将 `status` 设为 `deleted`：

```typescript
if (status === 'deleted') {
  const deleted = await deleteTask(taskListId, taskId)
  return {
    data: {
      success: deleted,
      updatedFields: deleted ? ['deleted'] : [],
      // ...
    },
  }
}
```

#### (3) 自动分配 Owner

当 teammate 将任务设为 `in_progress` 且未显式指定 owner 时：

**行号**: `188-199`

```typescript
if (
  isAgentSwarmsEnabled() &&
  status === 'in_progress' &&
  owner === undefined &&
  !existingTask.owner
) {
  const agentName = getAgentName()
  if (agentName) {
    updates.owner = agentName
    updatedFields.push('owner')
  }
}
```

#### (4) 更改 Owner 时自动发送 Mailbox 通知

**行号**: `277-298`

```typescript
if (updates.owner && isAgentSwarmsEnabled()) {
  const assignmentMessage = JSON.stringify({
    type: 'task_assignment',
    taskId,
    subject: existingTask.subject,
    description: existingTask.description,
    assignedBy: senderName,
    timestamp: new Date().toISOString(),
  })
  await writeToMailbox(updates.owner, {
    from: senderName,
    text: assignmentMessage,
    timestamp: new Date().toISOString(),
    color: senderColor,
  }, taskListId)
}
```

#### (5) 添加阻塞关系

```typescript
if (addBlocks && addBlocks.length > 0) {
  for (const blockId of newBlocks) {
    await blockTask(taskListId, taskId, blockId)
  }
}
if (addBlockedBy && addBlockedBy.length > 0) {
  for (const blockerId of newBlockedBy) {
    await blockTask(taskListId, blockerId, taskId)
  }
}
```

#### (6) 完成时的 TaskCompleted Hooks

**行号**: `232-265`

```typescript
if (status === 'completed') {
  const generator = executeTaskCompletedHooks(taskId, existingTask.subject, existingTask.description, ...)
  for await (const result of generator) {
    if (result.blockingError) {
      blockingErrors.push(getTaskCompletedHookMessage(result.blockingError))
    }
  }
  if (blockingErrors.length > 0) {
    return { data: { success: false, error: blockingErrors.join('\n') } }
  }
}
```

如果 hook 阻止完成，系统会**拒绝状态变更**，但不自动删除任务。

### 4.4 删除任务（deleteTask）

**文件**: `src/utils/tasks.ts`  
**行号**: `393-441`

系统自动执行的级联清理：

```typescript
export async function deleteTask(taskListId: string, taskId: string): Promise<boolean> {
  // 1. 更新 high water mark
  const numericId = parseInt(taskId, 10)
  if (!isNaN(numericId)) {
    const currentMark = await readHighWaterMark(taskListId)
    if (numericId > currentMark) {
      await writeHighWaterMark(taskListId, numericId)
    }
  }

  // 2. 删除任务文件
  await unlink(path)

  // 3. 级联清理：从其他任务的 blocks/blockedBy 中移除对本任务的引用
  const allTasks = await listTasks(taskListId)
  for (const task of allTasks) {
    const newBlocks = task.blocks.filter(id => id !== taskId)
    const newBlockedBy = task.blockedBy.filter(id => id !== taskId)
    if (newBlocks.length !== task.blocks.length || newBlockedBy.length !== task.blockedBy.length) {
      await updateTask(taskListId, task.id, { blocks: newBlocks, blockedBy: newBlockedBy })
    }
  }

  notifyTasksUpdated()
  return true
}
```

---

## 5. 并发控制与文件锁

### 5.1 锁配置

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

预算支持约 10+ 并发 swarm agent，最后竞争者最多等待约 2.6 秒。

### 5.2 三层锁策略

| 操作 | 锁级别 | 文件 | 说明 |
|------|--------|------|------|
| `createTask` | 列表级锁 | `.lock` | 防止 ID 冲突 |
| `updateTask` | 任务级锁 | `{taskId}.json` | 防止并发修改同一任务 |
| `claimTask` | 任务级/列表级锁 | `{taskId}.json` 或 `.lock` | `checkAgentBusy=true` 时用列表级锁保证原子性 |

**文件**: `src/utils/lockfile.ts`  
**行号**: `1-43`

`proper-lockfile` 的懒加载包装器，避免启动时加载开销。

### 5.3 claimTask 的并发安全

**文件**: `src/utils/tasks.ts`  
**行号**: `541-612`（基础版） / `618-692`（带 busy check 版）

```typescript
export async function claimTask(..., options: { checkAgentBusy?: boolean } = {}): Promise<ClaimTaskResult> {
  if (options.checkAgentBusy) {
    return claimTaskWithBusyCheck(taskListId, taskId, claimantAgentId)
  }
  // 否则使用任务级锁
}
```

`claimTaskWithBusyCheck` 使用**列表级锁**，在锁保护下：
1. 读取所有任务
2. 检查目标任务是否已被他人认领 / 已完成 / 有未解决 blockers
3. 检查 claimant 是否已有其他 open 任务
4. 原子性更新 owner

---

## 6. 多 Agent 协作自动化流程

Task V2 与 Agent Swarm 深度集成，存在多条**非 LLM 主动调用**的系统自动化路径。

### 6.1 In-Process Teammate 自动抢任务

 teammate 启动时，不等待 LLM 分配，直接自动 claim：

**文件**: `src/utils/swarm/inProcessRunner.ts`  
**行号**: `1015-1019`

```typescript
// Try to claim an available task immediately so the UI can show activity
// from the very start. The idle loop handles claiming for subsequent tasks.
await tryClaimNextTask(identity.parentSessionId, identity.agentName)
```

**行号**: `620-657`

```typescript
async function tryClaimNextTask(taskListId: string, agentName: string): Promise<string | undefined> {
  const tasks = await listTasks(taskListId)
  const availableTask = findAvailableTask(tasks)
  if (!availableTask) return undefined

  const result = await claimTask(taskListId, availableTask.id, agentName)
  if (!result.success) return undefined

  await updateTask(taskListId, availableTask.id, { status: 'in_progress' })
  return formatTaskAsPrompt(availableTask)
}
```

### 6.2 "Tasks Mode" 自动轮询抢任务

`useTaskListWatcher` hook 用于外部任务监听模式：Claude 监视磁盘上的任务目录，自动认领并执行新任务。

**文件**: `src/hooks/useTaskListWatcher.ts`  
**行号**: `34-189`

```typescript
export function useTaskListWatcher({ taskListId, isLoading, onSubmitTask }: Props): void {
  // 设置 fs.watch 监听器
  watcher = watch(tasksDir, debouncedCheck)

  checkForTasksRef.current = async () => {
    if (isLoadingRef.current) return  // 正在工作，不抢新任务

    const tasks = await listTasks(taskListId)
    const availableTask = findAvailableTask(tasks)
    if (!availableTask) return

    const result = await claimTask(taskListId, availableTask.id, agentId)
    if (!result.success) return

    currentTaskRef.current = availableTask.id
    const prompt = formatTaskAsPrompt(availableTask)
    const submitted = onSubmitTaskRef.current(prompt)
    if (!submitted) {
      // 提交失败，释放 claim
      await updateTask(taskListId, availableTask.id, { owner: undefined })
      currentTaskRef.current = null
    }
  }
}
```

### 6.3 Teammate 退出时自动解绑

当 teammate 被终止或优雅关闭时，系统自动将其所有未完成任务解绑：

**文件**: `src/utils/tasks.ts`  
**行号**: `818-860`

```typescript
export async function unassignTeammateTasks(
  teamName: string,
  teammateId: string,
  teammateName: string,
  reason: 'terminated' | 'shutdown',
): Promise<UnassignTasksResult> {
  const unresolvedAssignedTasks = tasks.filter(
    t => t.status !== 'completed' && (t.owner === teammateId || t.owner === teammateName)
  )

  for (const task of unresolvedAssignedTasks) {
    await updateTask(teamName, task.id, { owner: undefined, status: 'pending' })
  }
  // ...
}
```

### 6.4 任务分配后的 Mailbox 通知

当 `TaskUpdateTool` 更改 `owner` 时，系统自动向新 owner 的 mailbox 写入 `task_assignment` 消息（见 4.3 节）。Teammate 的 inbox 轮询器会读取该消息并提交为 prompt。

### 6.5 Agent 状态计算

**文件**: `src/utils/tasks.ts`  
**行号**: `763-798`

```typescript
export async function getAgentStatuses(teamName: string): Promise<AgentStatus[] | null> {
  const teamData = await readTeamMembers(teamName)
  if (!teamData) return null

  const taskListId = sanitizeName(teamName)
  const allTasks = await listTasks(taskListId)

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

> **注意**：代码中搜索未发现 `getAgentStatuses` 的直接调用方，它可能是为未来的 UI 面板或 `/team` 命令预留的 API。

---

## 7. UI 联动与状态通知

### 7.1 信号机制：notifyTasksUpdated

所有写操作（create/update/delete/reset/block）完成后都会调用：

**文件**: `src/utils/tasks.ts`  
**行号**: `61-67`

```typescript
export function notifyTasksUpdated(): void {
  try {
    tasksUpdated.emit()
  } catch {
    // Ignore listener errors
  }
}
```

调用方分布（通过 `grep notifyTasksUpdated`）：
- `setLeaderTeamName` / `clearLeaderTeamName`（`tasks.ts:36,46`）
- `resetTaskList`（`tasks.ts:182`）
- `createTask`（`tasks.ts:301`）
- `updateTaskUnsafe`（`tasks.ts:366`）
- `deleteTask`（`tasks.ts:436`）
- `teamHelpers.ts:677`（团队清理时）

### 7.2 TasksV2Store：单例文件 watcher + 轮询回退

**文件**: `src/hooks/useTasksV2.ts`  
**行号**: `29-199`

```typescript
class TasksV2Store {
  #tasks: Task[] | undefined = undefined
  #hidden = false
  #watcher: FSWatcher | null = null
  #pollTimer: ReturnType<typeof setTimeout> | null = null

  subscribe = (fn: () => void): (() => void) => {
    this.#unsubscribeTasksUpdated = onTasksUpdated(this.#debouncedFetch)
    void this.#fetch()
  }

  #fetch = async (): Promise<void> => {
    this.#rewatch(getTasksDir(taskListId))
    const current = (await listTasks(taskListId)).filter(t => !t.metadata?._internal)
    this.#tasks = current

    const hasIncomplete = current.some(t => t.status !== 'completed')
    if (hasIncomplete || current.length === 0) {
      this.#hidden = current.length === 0
      this.#clearHideTimer()
    } else if (this.#hideTimer === null && !this.#hidden) {
      // 所有任务刚完成，5秒后隐藏并清空
      this.#hideTimer = setTimeout(
        this.#onHideTimerFired.bind(this, taskListId),
        HIDE_DELAY_MS,  // 5000ms
      )
    }

    this.#notify()

    // 有未完成任务时启动轮询回退（5秒一次）
    if (hasIncomplete) {
      this.#pollTimer = setTimeout(this.#debouncedFetch, FALLBACK_POLL_MS)  // 5000ms
    }
  }
}
```

### 7.3 5 秒隐藏 + resetTaskList

当所有任务都完成并保持 5 秒后：

**文件**: `src/hooks/useTasksV2.ts`  
**行号**: `154-172`

```typescript
#onHideTimerFired(scheduledForTaskListId: string): void {
  const currentId = getTaskListId()
  if (currentId !== scheduledForTaskListId) return

  void listTasks(currentId).then(async tasksToCheck => {
    const allStillCompleted =
      tasksToCheck.length > 0 &&
      tasksToCheck.every(t => t.status === 'completed')
    if (allStillCompleted) {
      await resetTaskList(currentId)  // 清空任务文件并更新 high water mark
      this.#tasks = []
      this.#hidden = true
    }
    this.#notify()
  })
}
```

**resetTaskList 实现**（`src/utils/tasks.ts:147-188`）：

```typescript
export async function resetTaskList(taskListId: string): Promise<void> {
  const dir = getTasksDir(taskListId)
  const lockPath = await ensureTaskListLockFile(taskListId)
  let release: (() => Promise<void>) | undefined
  try {
    release = await lockfile.lock(lockPath, LOCK_OPTIONS)

    // 保存当前最高 ID 到 high water mark
    const currentHighest = await findHighestTaskIdFromFiles(taskListId)
    if (currentHighest > 0) {
      const existingMark = await readHighWaterMark(taskListId)
      if (currentHighest > existingMark) {
        await writeHighWaterMark(taskListId, currentHighest)
      }
    }

    // 删除所有任务文件
    for (const file of files) {
      if (file.endsWith('.json') && !file.startsWith('.')) {
        await unlink(filePath)
      }
    }
    notifyTasksUpdated()
  } finally {
    if (release) await release()
  }
}
```

**被谁调用**：
- `useTasksV2Store` 的 5s hide timer（自动清理已完成任务）
- `TeamCreateTool` 创建新团队时（`src/tools/TeamCreateTool/TeamCreateTool.ts:185`）

### 7.4 TaskListV2 渲染逻辑

**文件**: `src/components/TaskListV2.tsx`  
**行号**: `30-378`

核心行为：
- 只展示非内部任务（已在 `useTasksV2` 过滤）
- 已完成任务在 30 秒内仍显示（`RECENT_COMPLETED_TTL_MS = 30_000`）
- 截断策略：按终端高度 `maxDisplay = min(10, max(3, rows - 14))`
- 截断时优先级：最近完成（30s 内） > in_progress > pending（未阻塞的优先） >  older completed
- 如果是 swarm 模式，会展示 teammate 颜色和当前活动描述（从 `AppState.tasks` 中的 `InProcessTeammateTaskState` 读取）

> 注意：这里出现了 Task V2 与 `AppState.tasks`（后台任务状态机）的**首次交汇**——`TaskListV2` 用 `AppState.tasks` 来渲染 teammate 的实时活动 spinner，但任务列表本身的数据来自磁盘 JSON。

---

## 8. 依赖关系管理

### 8.1 建立阻塞关系

**文件**: `src/utils/tasks.ts`  
**行号**: `458-486`

```typescript
export async function blockTask(taskListId: string, fromTaskId: string, toTaskId: string): Promise<boolean> {
  const [fromTask, toTask] = await Promise.all([getTask(...), getTask(...)])

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

### 8.2 可用性检查

`findAvailableTask` 和 `claimTask` 中都会检查阻塞：

```typescript
const unresolvedTaskIds = new Set(
  allTasks.filter(t => t.status !== 'completed').map(t => t.id),
)
const blockedByTasks = task.blockedBy.filter(id => unresolvedTaskIds.has(id))

if (blockedByTasks.length > 0) {
  return { success: false, reason: 'blocked', task, blockedByTasks }
}
```

只有 `status === 'completed'` 的任务才不会阻塞他人。`pending` 和 `in_progress` 都会被视为未解决 blocker。

---

## 9. 提醒与 Nudge 机制

### 9.1 Task Reminder

当 LLM 连续 **10 轮** 未调用 `TaskCreate` 或 `TaskUpdate` 时，系统自动插入 `task_reminder` attachment：

**文件**: `src/utils/attachments.ts`  
**行号**: `3375-3432`

```typescript
async function getTaskReminderAttachments(messages, toolUseContext): Promise<Attachment[]> {
  if (!isTodoV2Enabled()) return []
  if (process.env.USER_TYPE === 'ant') return []
  // Brief 模式跳过

  const { turnsSinceLastTaskManagement, turnsSinceLastReminder } = getTaskReminderTurnCounts(messages)

  if (
    turnsSinceLastTaskManagement >= TODO_REMINDER_CONFIG.TURNS_SINCE_WRITE &&  // 10
    turnsSinceLastReminder >= TODO_REMINDER_CONFIG.TURNS_BETWEEN_REMINDERS      // 10
  ) {
    const tasks = await listTasks(getTaskListId())
    return [{ type: 'task_reminder', content: tasks, itemCount: tasks.length }]
  }
  return []
}
```

**文件**: `src/utils/messages.ts`  
**行号**: `3680-3699`

渲染为系统提示，提醒 LLM 使用 `TaskCreate` / `TaskUpdate` 跟踪进度。

### 9.2 Verification Nudge

完成 3+ 任务且没有验证步骤时，系统会在 `TaskUpdateTool` 的结果中追加提醒，要求 LLM 调用验证代理（Verification Agent）。

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
  if (allDone && allTasks.length >= 3 && !allTasks.some(t => /verif/i.test(t.subject))) {
    verificationNudgeNeeded = true
  }
}
```

---

## 10. 与 AppState.tasks（后台任务）的边界

这是最容易混淆的地方。Claude Code 中有**两个完全不同的 "Task" 概念**：

| 概念 | 类型 | 存储 | 用途 |
|------|------|------|------|
| **Task V2** | `Task`（工作流任务） | 磁盘 JSON (`~/.claude/tasks/`) | LLM 规划与多 agent 协作 |
| **Background Task** | `TaskState` | 内存 `AppState.tasks` | 运行时后台任务（bash、子代理、workflow 等） |

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

**交汇点**：
- `TaskListV2.tsx` 用 `AppState.tasks` 读取 in-process teammate 的实时活动，叠加在 Task V2 的列表项旁边显示。
- `useTasksV2.ts` 的 hook 返回的是磁盘上的 `Task[]`。
- `AppStateStore.ts` 中的 `tasks` 字段与 `todos` 字段是完全独立的两个系统。

---

## 11. 控制方总结：LLM 触发 vs 系统自动

| 行为 | 控制方 | 关键代码位置 |
|------|--------|-------------|
| 调用 `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate` | **LLM** | `src/tools/Task*Tool/*.ts` |
| ID 自增、JSON 写入 | **系统自动** | `src/utils/tasks.ts:284-308` |
| 文件锁获取与释放 | **系统自动** | `src/utils/tasks.ts` / `src/utils/lockfile.ts` |
| `TaskCreated` / `TaskCompleted` Hooks 执行 | **系统自动** | `TaskCreateTool.ts:93-113` / `TaskUpdateTool.ts:235-264` |
| Hook 失败时自动回滚 | **系统自动** | `TaskCreateTool.ts:111-112` |
| 删除时级联清理 blocks/blockedBy | **系统自动** | `src/utils/tasks.ts:420-434` |
| In-process teammate 启动自动 claim | **系统自动** | `inProcessRunner.ts:1015-1019` |
| Task Mode 自动轮询 claim | **系统自动** | `useTaskListWatcher.ts:34-189` |
| `in_progress` 时自动设置 owner | **系统自动** | `TaskUpdateTool.ts:188-199` |
| 更改 owner 时发送 mailbox | **系统自动** | `TaskUpdateTool.ts:277-298` |
| Teammate 退出解绑任务 | **系统自动** | `src/utils/tasks.ts:818-860` |
| 所有任务完成 5s 后 resetTaskList | **系统自动** | `useTasksV2.ts:154-172` |
| 10 轮未管理插入 task_reminder | **系统自动** | `attachments.ts:3375-3432` |
| 完成 3+ 任务插入 verification nudge | **系统自动** | `TaskUpdateTool.ts:333-349` |
| UI 通过 fs.watch 自动刷新 | **系统自动** | `useTasksV2.ts:90-104` |

---

## 12. 关键代码速查表

| 功能 | 文件 | 行号范围 |
|------|------|---------|
| V2 总开关 | `src/utils/tasks.ts` | `133-139` |
| 交互式判定 | `src/main.tsx` | `797-812` |
| 工具列表注册 | `src/tools.ts` | `208-220` |
| TodoWrite 自过滤 | `src/tools/TodoWriteTool/TodoWriteTool.ts` | `51-54` |
| Task 数据模型 | `src/utils/tasks.ts` | `76-89` |
| 任务目录/路径 | `src/utils/tasks.ts` | `221-231` |
| getTaskListId | `src/utils/tasks.ts` | `199-210` |
| 锁配置 | `src/utils/tasks.ts` | `94-108` |
| proper-lockfile 包装 | `src/utils/lockfile.ts` | `1-43` |
| createTask | `src/utils/tasks.ts` | `284-308` |
| updateTask | `src/utils/tasks.ts` | `370-391` |
| updateTaskUnsafe | `src/utils/tasks.ts` | `354-368` |
| deleteTask | `src/utils/tasks.ts` | `393-441` |
| blockTask | `src/utils/tasks.ts` | `458-486` |
| claimTask | `src/utils/tasks.ts` | `541-612` |
| claimTaskWithBusyCheck | `src/utils/tasks.ts` | `618-692` |
| High Water Mark | `src/utils/tasks.ts` | `91-131` |
| resetTaskList | `src/utils/tasks.ts` | `147-188` |
| getAgentStatuses | `src/utils/tasks.ts` | `763-798` |
| unassignTeammateTasks | `src/utils/tasks.ts` | `818-860` |
| notifyTasksUpdated | `src/utils/tasks.ts` | `61-67` |
| onTasksUpdated | `src/utils/tasks.ts` | `53` |
| TaskCreateTool | `src/tools/TaskCreateTool/TaskCreateTool.ts` | `18-129` |
| TaskUpdateTool | `src/tools/TaskUpdateTool/TaskUpdateTool.ts` | `33-363` |
| TaskListTool | `src/tools/TaskListTool/TaskListTool.ts` | `13-116` |
| TaskGetTool | `src/tools/TaskGetTool/TaskGetTool.ts` | `13-128` |
| TeamCreateTool reset | `src/tools/TeamCreateTool/TeamCreateTool.ts` | `182-191` |
| inProcessRunner 自动 claim | `src/utils/swarm/inProcessRunner.ts` | `620-657`, `1015-1019` |
| useTaskListWatcher | `src/hooks/useTaskListWatcher.ts` | `34-189` |
| findAvailableTask | `src/hooks/useTaskListWatcher.ts` | `197-208` |
| TasksV2Store | `src/hooks/useTasksV2.ts` | `29-199` |
| useTasksV2 | `src/hooks/useTasksV2.ts` | `218-229` |
| useTasksV2WithCollapseEffect | `src/hooks/useTasksV2.ts` | `236-249` |
| TaskListV2 渲染 | `src/components/TaskListV2.tsx` | `30-378` |
| Task Reminder | `src/utils/attachments.ts` | `3375-3432` |
| Todo Reminder | `src/utils/attachments.ts` | `3266-3317` |
| task_reminder 渲染 | `src/utils/messages.ts` | `3680-3699` |
| writeToMailbox (task assignment) | `src/tools/TaskUpdateTool/TaskUpdateTool.ts` | `277-298` |
| IN_PROCESS_TEAMMATE_ALLOWED_TOOLS | `src/constants/tools.ts` | `77-88` |
| ASYNC_AGENT_ALLOWED_TOOLS | `src/constants/tools.ts` | `55-71` |
| filterToolsForAgent | `src/tools/AgentTool/agentToolUtils.ts` | `70-116` |
| resolveAgentTools | `src/tools/AgentTool/agentToolUtils.ts` | `122-180` |
| AppState.tasks 定义 | `src/state/AppStateStore.ts` | `159-165` |
| AppState.todos 定义 | `src/state/AppStateStore.ts` | `220` |
| TaskState 联合类型 | `src/tasks/types.ts` | `12-20` |
