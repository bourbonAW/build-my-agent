# Claude Code Task/Todo 调用流程图

## 1. Todo V1 调用流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Model 调用 TodoWriteTool                                        │
│ { todos: [                                                      │
│   { content: "Implement API", status: "in_progress", ... },    │
│   { content: "Write tests", status: "pending", ... }           │
│ ]}                                                              │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ TodoWriteTool.call()                                            │
│                                                                 │
│ 1. 确定存储键                                                   │
│    const todoKey = context.agentId ?? getSessionId()           │
│                                                                 │
│ 2. 获取当前待办列表                                             │
│    const oldTodos = appState.todos[todoKey] ?? []              │
│                                                                 │
│ 3. 检查是否全部完成                                             │
│    const allDone = todos.every(_ => _.status === 'completed')  │
│    const newTodos = allDone ? [] : todos                        │
│                                                                 │
│ 4. 验证代理提醒（如果启用 VERIFICATION_AGENT）                 │
│    if (allDone && todos.length >= 3 && !hasVerificationTask)   │
│      verificationNudgeNeeded = true                             │
│                                                                 │
│ 5. 更新 AppState                                                │
│    context.setAppState(prev => ({                               │
│      ...prev,                                                   │
│      todos: { ...prev.todos, [todoKey]: newTodos }             │
│    }))                                                          │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 返回 ToolResult                                                 │
│ { data: { oldTodos, newTodos, verificationNudgeNeeded } }      │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Task V2 - 创建任务流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Model 调用 TaskCreateTool                                       │
│ {                                                               │
│   subject: "Implement authentication",                         │
│   description: "Add JWT-based auth to API endpoints",          │
│   activeForm: "Implementing authentication",                   │
│   metadata: { priority: "high", estimatedHours: 4 }            │
│ }                                                               │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ TaskCreateTool.call()                                           │
│                                                                 │
│ 1. 获取任务列表ID                                               │
│    const taskListId = getTaskListId()                          │
│    // 优先级: CLAUDE_CODE_TASK_LIST_ID > teammateCtx >        │
│    //           CLAUDE_CODE_TEAM_NAME > leaderTeamName >      │
│    //           sessionId                                       │
│                                                                 │
│ 2. 创建任务（带文件锁）                                         │
│    const taskId = await createTask(taskListId, {               │
│      subject, description, activeForm,                         │
│      status: 'pending', owner: undefined,                      │
│      blocks: [], blockedBy: [], metadata                       │
│    })                                                           │
│                                                                 │
│    2.1 获取锁文件路径                                           │
│        lockPath = join(getTasksDir(taskListId), '.lock')       │
│                                                                 │
│    2.2 获取独占锁                                               │
│        release = await lockfile.lock(lockPath, LOCK_OPTIONS)   │
│                                                                 │
│    2.3 读取当前最高ID                                           │
│        highestId = max(fromFiles, fromHighWaterMark)           │
│        id = String(highestId + 1)  // 自增ID                   │
│                                                                 │
│    2.4 写入任务文件                                             │
│        writeFile(`${id}.json`, JSON.stringify(task))           │
│                                                                 │
│    2.5 释放锁                                                   │
│        await release()                                          │
│                                                                 │
│    2.6 通知更新                                                 │
│        notifyTasksUpdated()                                     │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. 执行 TaskCreated Hooks                                       │
│    const generator = executeTaskCreatedHooks(                  │
│      taskId, subject, description,                             │
│      getAgentName(), getTeamName(), ...                        │
│    )                                                            │
│                                                                 │
│    for await (const result of generator) {                     │
│      if (result.blockingError) {                               │
│        blockingErrors.push(...)                                │
│      }                                                          │
│    }                                                            │
│                                                                 │
│    // 如果有阻塞错误，回滚创建                                  │
│    if (blockingErrors.length > 0) {                            │
│      await deleteTask(taskListId, taskId)                      │
│      throw new Error(blockingErrors.join('\n'))                │
│    }                                                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. 自动展开任务面板                                             │
│    context.setAppState(prev => ({                               │
│      ...prev,                                                   │
│      expandedView: 'tasks'                                      │
│    }))                                                          │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 返回 ToolResult                                                 │
│ { data: { task: { id: "1", subject } } }                       │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Task V2 - 更新任务流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Model 调用 TaskUpdateTool                                       │
│ {                                                               │
│   taskId: "1",                                                 │
│   status: "in_progress",                                       │
│   owner: "worker-1",                                           │
│   addBlockedBy: ["2"]  // 被任务2阻塞                          │
│ }                                                               │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ TaskUpdateTool.call()                                           │
│                                                                 │
│ 1. 获取任务列表ID                                               │
│    const taskListId = getTaskListId()                          │
│                                                                 │
│ 2. 检查任务存在                                                 │
│    const existingTask = await getTask(taskListId, taskId)      │
│    if (!existingTask) return { success: false, error: ... }    │
│                                                                 │
│ 3. 构建更新字段                                                 │
│    const updates = {}                                           │
│    if (subject !== undefined) updates.subject = subject        │
│    if (status !== undefined) {                                  │
│      if (status === 'deleted') {                               │
│        // 物理删除任务                                          │
│        await deleteTask(taskListId, taskId)                    │
│        return { success: true, updatedFields: ['deleted'] }    │
│      }                                                          │
│      if (status === 'completed') {                             │
│        // 执行 TaskCompleted hooks                              │
│        const generator = executeTaskCompletedHooks(...)        │
│        // 检查阻塞错误...                                       │
│      }                                                          │
│      updates.status = status                                   │
│    }                                                            │
│                                                                 │
│    // 自动设置 owner（如果是队友标记为 in_progress）           │
│    if (isAgentSwarmsEnabled() &&                                │
│        status === 'in_progress' &&                              │
│        !existingTask.owner) {                                  │
│      updates.owner = getAgentName()                            │
│    }                                                            │
│                                                                 │
│    if (owner !== undefined) updates.owner = owner              │
│    if (metadata !== undefined) updates.metadata = merged       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. 应用更新                                                     │
│    await updateTask(taskListId, taskId, updates)               │
│                                                                 │
│    4.1 检查任务存在                                             │
│    4.2 获取文件锁                                               │
│    4.3 读取现有任务                                             │
│    4.4 合并更新                                                 │
│    4.5 写入文件                                                 │
│    4.6 释放锁                                                   │
│    4.7 通知更新                                                 │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 通知新所有者（如果更改了 owner）                            │
│    if (updates.owner && isAgentSwarmsEnabled()) {              │
│      const assignmentMessage = JSON.stringify({                │
│        type: 'task_assignment',                                │
│        taskId, subject, description,                           │
│        assignedBy: getAgentName(),                             │
│        timestamp: new Date().toISOString()                     │
│      })                                                         │
│      await writeToMailbox(updates.owner, {                     │
│        from: senderName,                                        │
│        text: assignmentMessage,                                │
│        timestamp: ..., color: senderColor                      │
│      }, taskListId)                                             │
│    }                                                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. 添加阻塞关系（如果提供了 addBlocks/addBlockedBy）           │
│    if (addBlocks) {                                            │
│      for (const blockId of addBlocks) {                        │
│        await blockTask(taskListId, taskId, blockId)            │
│        // 更新双方的 blocks/blockedBy 数组                      │
│      }                                                          │
│    }                                                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. 验证提醒（如果启用 VERIFICATION_AGENT）                     │
│    if (allTasksCompleted && allTasks.length >= 3 &&            │
│        !anyTaskIsVerification) {                               │
│      verificationNudgeNeeded = true                             │
│    }                                                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 返回 ToolResult                                                 │
│ { data: {                                                       │
│   success: true,                                                │
│   taskId: "1",                                                 │
│   updatedFields: ['status', 'owner', 'blockedBy'],             │
│   statusChange: { from: 'pending', to: 'in_progress' },        │
│   verificationNudgeNeeded: false                                │
│ }}                                                              │
└─────────────────────────────────────────────────────────────────┘
```

## 4. Task V2 - 抢占任务流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent 调用 claimTask()                                          │
│ claimTask(taskListId, taskId, agentId, { checkAgentBusy: true })│
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
              ┌─────────────────────┐
              │ checkAgentBusy?     │
              └──────────┬──────────┘
                    是 /     \ 否
                      /       \
                     ▼         ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│ claimTaskWithBusyCheck() │  │ 任务级锁（原始行为）          │
│                          │  │                              │
│ 1. 获取任务列表锁        │  │ 1. 检查任务存在              │
│    .lock 文件            │  │ 2. 获取任务文件锁            │
│                          │  │ 3. 检查：已声明/已完成/阻塞  │
│ 2. 读取所有任务          │  │ 4. 更新 owner                │
│                          │  │                              │
│ 3. 检查任务存在          │  │                              │
│                          │  │                              │
│ 4. 检查：已声明/已完成/阻塞│ │                              │
│                          │  │                              │
│ 5. 检查代理是否忙碌      │  │                              │
│    （遍历所有任务找      │  │                              │
│     owner === agentId    │  │                              │
│     && status !== completed）│                            │
│                          │  │                              │
│ 6. 原子声明任务          │  │                              │
│    更新 owner            │  │                              │
└──────────────────────────┘  └──────────────────────────────┘
                          \      /
                           \    /
                            \  /
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 返回 ClaimTaskResult                                            │
│                                                                 │
│ 成功:                                                           │
│ { success: true, task: updatedTask }                           │
│                                                                 │
│ 失败:                                                           │
│ { success: false, reason: 'task_not_found' }                   │
│ { success: false, reason: 'already_claimed', task }            │
│ { success: false, reason: 'already_resolved', task }           │
│ { success: false, reason: 'blocked', task, blockedByTasks }    │
│ { success: false, reason: 'agent_busy', task, busyWithTasks }  │
└─────────────────────────────────────────────────────────────────┘
```

## 5. 团队成员退出处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│ 队友进程终止或优雅关闭                                          │
│ (terminated | shutdown)                                        │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ unassignTeammateTasks(teamName, teammateId, name, reason)      │
│                                                                 │
│ 1. 获取团队所有任务                                             │
│    const tasks = await listTasks(teamName)                     │
│                                                                 │
│ 2. 筛选该成员的未完成任务                                       │
│    const unresolvedAssignedTasks = tasks.filter(               │
│      t => t.status !== 'completed' &&                          │
│      (t.owner === teammateId || t.owner === teammateName)      │
│    )                                                            │
│                                                                 │
│ 3. 取消分配每个任务                                             │
│    for (const task of unresolvedAssignedTasks) {               │
│      await updateTask(teamName, task.id, {                     │
│        owner: undefined,                                        │
│        status: 'pending'  // 重置为待处理                      │
│      })                                                         │
│    }                                                            │
│                                                                 │
│ 4. 构建通知消息                                                 │
│    const actionVerb = reason === 'terminated'                  │
│      ? 'was terminated' : 'has shut down'                      │
│    let notificationMessage = `${name} ${actionVerb}.`          │
│                                                                 │
│    if (unresolvedAssignedTasks.length > 0) {                   │
│      notificationMessage +=                                     │
│        ` ${count} task(s) were unassigned: ${taskList}.` +     │
│        ` Use TaskList to check availability...`                │
│    }                                                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 返回 UnassignTasksResult                                        │
│ {                                                               │
│   unassignedTasks: [{ id, subject }, ...],                     │
│   notificationMessage: "worker-1 was terminated. 2 task(s)..." │
│ }                                                               │
└─────────────────────────────────────────────────────────────────┘
```

## 6. Task V2 与 Runtime Task 的关系

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      两种 "Task" 概念的区分                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌─────────────────────────────┐    ┌─────────────────────────────────┐ │
│   │     Task V2 (工作流任务)     │    │  Runtime Task (运行时任务)       │ │
│   ├─────────────────────────────┤    ├─────────────────────────────────┤ │
│   │                             │    │                                 │ │
│   │ 用途: 工作流管理             │    │ 用途: 后台执行跟踪               │ │
│   │                             │    │                                 │ │
│   │ 存储: ~/.claude/tasks/      │    │ 存储: AppState.tasks (内存)      │ │
│   │                             │    │                                 │ │
│   │ 持久化: 是（跨会话）         │    │ 持久化: 否（会话级）             │ │
│   │                             │    │                                 │ │
│   │ 工具: TaskCreate/Update/... │    │ 工具: BashTool, AgentTool, ...  │ │
│   │                             │    │                                 │ │
│   │ 字段: subject, description, │    │ 字段: type, status, outputFile, │ │
│   │       blocks, blockedBy,    │    │       startTime, endTime, ...   │ │
│   │       owner, metadata       │    │                                 │ │
│   │                             │    │                                 │ │
│   │ 生命周期: 手动管理           │    │ 生命周期: 自动管理               │ │
│   │                             │    │                                 │ │
│   │ 类型: 'pending' | 'in_pro- │    │ 类型: 'local_bash' | 'local_    │ │
│   │        gress' | 'completed' │    │        agent' | 'remote_agent'  │ │
│   │                             │    │        | 'in_process_teammate'  │ │
│   │                             │    │        | ...                    │ │
│   │                             │    │                                 │ │
│   └─────────────────────────────┘    └─────────────────────────────────┘ │
│                                                                          │
│   关系：                                                                 │
│   - Task V2 用于计划和跟踪工作                                          │
│   - Runtime Task 用于实际执行                                           │
│   - AgentTool 可能同时创建两者                                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## 7. 文件锁机制详解

```
┌─────────────────────────────────────────────────────────────────┐
│ 并发场景：多个 Claude 进程同时创建任务                            │
│                                                                 │
│ 进程 A                    锁文件                   进程 B       │
│   │                          │                       │          │
│   │  1. 请求锁               │                       │          │
│   │─────────────────────────▶│                       │          │
│   │                          │                       │          │
│   │  2. 获得锁               │                       │          │
│   │◀─────────────────────────│                       │          │
│   │                          │                       │          │
│   │  3. 读取 highestId=5     │                       │          │
│   │  4. 创建任务 6           │                       │          │
│   │  5. 释放锁               │                       │          │
│   │─────────────────────────▶│                       │          │
│   │                          │                       │          │
│   │                          │  6. 请求锁（等待）    │          │
│   │                          │◀──────────────────────│          │
│   │                          │                       │          │
│   │                          │  7. 获得锁            │          │
│   │                          │──────────────────────▶│          │
│   │                          │                       │          │
│   │                          │  8. 读取 highestId=6  │          │
│   │                          │  9. 创建任务 7        │          │
│   │                          │  10. 释放锁           │          │
│   │                          │                       │          │
└─────────────────────────────────────────────────────────────────┘

锁配置：
{
  retries: 30,           // 最多重试30次
  minTimeout: 5,         // 首次等待5ms
  maxTimeout: 100        // 最大等待100ms（指数退避）
}
// 总等待时间预算：约2.6秒
// 适用于 ~10+ 并发代理场景
```

## 8. 任务状态转换图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Task V2 状态机                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│    ┌──────────┐                                                 │
│    │  pending │◀────────────────────────────────┐               │
│    └────┬─────┘                                 │               │
│         │                                        │               │
│         │ claimTask / update status              │               │
│         ▼                                        │               │
│    ┌──────────┐                                 │               │
│    │in_progress│                                │               │
│    └────┬─────┘                                 │               │
│         │                                        │               │
│         │ update status                          │               │
│         ▼                                        │               │
│    ┌──────────┐     deleteTask()                │               │
│    │completed │─────────────────────────────────▶│ 删除         │
│    └──────────┘                                 │               │
│                                                                  │
│  状态转换条件：                                                   │
│  - pending → in_progress: claimTask() 成功                     │
│  - in_progress → completed: TaskUpdateTool 更新                │
│  - 任何状态 → 删除: TaskUpdateTool 设置 status='deleted'       │
│                                                                  │
│  注意：没有 'failed' 或 'killed' 状态                           │
│  （这些是 Runtime Task 的状态）                                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```
