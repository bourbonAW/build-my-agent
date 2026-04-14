# Claude Code Task V2 vs Deer-Flow 2.0 (LangGraph) 任务管理架构对比

> **研究日期**: 2026-04-13  
> **对比对象**: 
> - Claude Code `main` 分支 — Task V2 系统（自研实现）
> - ByteDance Deer-Flow 2.0 — 基于 LangGraph 的多 Agent 编排框架

---

## 1. 核心问题：看到依赖关系就想到图，是不是应该用 LangGraph？

Claude Code 的 Task V2 有 `blocks` / `blockedBy` 字段，天然构成 DAG。Deer-Flow 2.0 则明确基于 LangGraph 的 `StateGraph` 实现 supervisor → sub-agent 的拓扑。这很容易让人产生直觉：

> "有依赖关系 = 应该用图框架 = LangGraph 是更好的决策"

但这个等式是否成立？下面从架构设计、代码实现、 trade-off 三个层面拆解。

---

## 2. Deer-Flow 2.0 的架构解析

### 2.1 整体架构

根据 Deer-Flow 官方架构文档 (`backend/docs/ARCHITECTURE.md`)：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           make_lead_agent(config)                        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            Middleware Chain                              │
│  ThreadData → Uploads → Sandbox → Summarization → Title → TodoList →   │
│  ViewImage → Clarification                                              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              Agent Core                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐   │
│  │      Model       │  │      Tools       │  │    System Prompt     │   │
│  │  (from factory)  │  │  (configured +   │  │  (with skills)       │   │
│  │                  │  │   MCP + builtin) │  │                      │   │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

LangGraph Server 作为核心运行时，负责：
- Agent creation and configuration
- Thread state management
- Middleware chain execution
- Tool execution orchestration
- SSE streaming for real-time responses
- Checkpointing

### 2.2 ThreadState：LangGraph 状态扩展

```python
class ThreadState(AgentState):
    messages: list[BaseMessage]
    sandbox: dict
    artifacts: list[str]
    thread_data: dict
    title: str | None
    todos: list[dict]         # Task tracking (plan mode)
    viewed_images: dict
```

### 2.3 Supervisor-Subgraph 拓扑

Deer-Flow 使用典型的 **supervisor-based orchestration**：

```python
# 概念性拓扑（来自 SitePoint 深度解析）
workflow.add_node("supervisor", supervisorNode)
workflow.add_node("researcher", researcherAgent)
workflow.add_node("coder", coderAgent)
workflow.add_node("reporter", reporterAgent)

workflow.addEdge("supervisor", "researcher")
workflow.addEdge("supervisor", "coder")
workflow.addEdge("researcher", "reporter")
workflow.addEdge("coder", "reporter")
workflow.setEntryPoint("supervisor")
```

核心特点：
- **Supervisor** 负责分解任务、生成计划、委派子任务
- **Sub-agent** 执行具体工作，结果回传到 supervisor
- **Harness**（编排层）监控生命周期、处理失败恢复、支持 replanning
- **Checkpointing** 通过 LangGraph 的 `SqliteSaver` / `PostgresSaver` 持久化状态
- **Human-in-the-loop** 作为一等公民，可在检查点暂停等待用户确认

### 2.4 持久化与检查点

Deer-Flow 依赖 LangGraph 的 `checkpointer`：

```python
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver("./deer_flow_checkpoints.db")
app = workflow.compile(checkpointer=checkpointer)
```

并发建议：
- SQLite：单进程运行
- PostgreSQL/Redis：支持并发多 agent 写入

---

## 3. Claude Code Task V2 的架构解析

### 3.1 整体架构

Claude Code 的 Task V2 **完全没有使用任何图框架**，是一套自研的轻量级任务管理系统：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         LLM (主线程 / 子 Agent)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ TaskCreate   │  │ TaskUpdate   │  │ TaskList     │  │ TaskGet     │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     TaskService (src/utils/tasks.ts)                     │
│  - 磁盘 JSON 持久化 (~/.claude/tasks/<taskListId>/*.json)               │
│  - proper-lockfile 文件锁                                               │
│  - High Water Mark ID 生成                                              │
│  - claimTask / blockTask / unblock                                      │
│  - notifyTasksUpdated() 信号                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据结构

```typescript
interface Task {
  id: string
  subject: string
  description: string
  activeForm?: string
  owner?: string                // 哪个 agent 负责
  status: 'pending' | 'in_progress' | 'completed'
  blocks: string[]              // 阻塞谁
  blockedBy: string[]           // 被谁阻塞
  metadata?: Record<string, unknown>
}
```

### 3.3 调度方式

Claude Code **没有 supervisor node**。调度是分布式的、隐式的：

1. **LLM 主动调度**：主线程 LLM 调用 `TaskCreate` / `TaskUpdate` 创建和分配任务
2. **自动 claim**：In-process teammate 启动后自动调用 `tryClaimNextTask()` 抢任务
3. **文件 watcher 驱动**：`useTaskListWatcher` hook 监视磁盘，自动认领可用任务
4. **依赖检查**：`claimTask` 和 `findAvailableTask` 检查 `blockedBy` 中是否有未完成的任务

```typescript
// 没有 StateGraph，没有 supervisorNode
// 只有简单的可用性检查
function findAvailableTask(tasks: Task[]): Task | undefined {
  const unresolvedTaskIds = new Set(
    tasks.filter(t => t.status !== 'completed').map(t => t.id)
  )
  return tasks.find(task => {
    if (task.status !== 'pending') return false
    if (task.owner) return false
    return task.blockedBy.every(id => !unresolvedTaskIds.has(id))
  })
}
```

### 3.4 持久化与检查点

Claude Code 不依赖外部数据库，使用极简的文件系统持久化：

```typescript
// ~/.claude/tasks/<taskListId>/
// ├── 1.json
// ├── 2.json
// ├── .highwatermark
// └── .lock
```

- 每个任务一个 JSON 文件
- `.lock` 文件用于 `proper-lockfile` 并发控制
- `.highwatermark` 防止 ID 重用
- `notifyTasksUpdated()` + `fs.watch` 实现 UI 联动

---

## 4. 六维度深度对比

### 4.1 架构范式

| 维度 | Claude Code Task V2 | Deer-Flow 2.0 (LangGraph) |
|------|---------------------|---------------------------|
| **核心范式** | LLM-centric + 系统辅助 | Supervisor-centric graph orchestration |
| **控制流** | 隐式、分布式 | 显式、集中式（supervisor 拥有完整计划） |
| **框架依赖** | 零外部图框架 | 深度依赖 LangGraph + LangChain |
| **状态管理** | 磁盘 JSON + AppState 信号 | LangGraph `ThreadState` + Checkpointer |
| **图表达** | 无显式图，依赖关系通过 `blocks/blockedBy` 隐式表达 | 显式 `StateGraph` 节点和边 |

**关键差异**：
- Deer-Flow 的 supervisor 是一个**真正的编排节点**，它生成计划、决定路由、处理 replanning。
- Claude Code 的 "计划" 完全在 LLM 的 prompt 里，系统只提供工具让 LLM 自我追踪，没有独立的计划执行引擎。

### 4.2 依赖关系处理

**Claude Code**：
- `blocks` / `blockedBy` 只用于**抢占前检查**和**列表过滤**
- 没有图遍历、拓扑排序、条件路由
- 依赖检查非常简单：所有 `status !== 'completed'` 的任务都会阻塞下游

**Deer-Flow**：
- 依赖关系体现在 LangGraph 的 `addConditionalEdges` 中
- Supervisor 可以基于子任务完成状态动态决定下一步路由
- 天然支持复杂的工作流分支、循环、replanning

### 4.3 多 Agent 并发与调度

**Claude Code**：
- 没有全局并发限制，agent 数量由 LLM 决定
- `batch` skill 软性建议 5-30 个 background agents
- In-process teammate 通过 `claimTask` 自动抢任务
- 单个 agent 可通过 `checkAgentBusy` 限制同时只能执行一个任务

**Deer-Flow**：
- Supervisor 显式决定哪些子任务可以并行（`Promise.all` 委派）
- 通过 LangGraph 的 checkpoint 后端（PostgreSQL/Redis）支持并发写入
- 更适合长时间（小时级）运行的研究/编码工作流

### 4.4 持久化与恢复

**Claude Code**：
- 极简文件系统 JSON
- 适合会话级别或跨会话的轻量级任务跟踪
- 恢复逻辑简单：读取目录下的 JSON 文件即可
- 不支持进程崩溃后从中途恢复 agent 执行

**Deer-Flow**：
- 数据库级 checkpoint（SQLite/PostgreSQL）
- 支持进程崩溃后从最近的 graph checkpoint 恢复
- 保存的是完整的 `ThreadState`（messages、plan、results、status）
- 适合数小时的长时运行任务

### 4.5 复杂度和 overhead

**Claude Code**：
- 极低的外部依赖
- 约 862 行的 `tasks.ts` 撑起整个 Task V2
- 不需要维护图状态机、checkpoint 后端、节点路由逻辑
- 缺点：不支持复杂的条件工作流、循环、显式 replanning

**Deer-Flow**：
- 需要 LangGraph、LangChain、checkpoint 后端、Docker sandbox
- 架构完整但重量级
- 需要定义 supervisor node、sub-agent nodes、conditional edges、state channels
- 优点：对长时、复杂、多阶段工作流有原生支持

### 4.6 Human-in-the-Loop

**Claude Code**：
- 通过 `AskUserQuestionTool` 和 Plan Mode 实现人机交互
- 没有 workflow-level 的检查点概念
- 交互是 turn-based 的

**Deer-Flow**：
- 将 human-in-the-loop 作为架构一等公民
- Supervisor 可以在预定义的检查点暂停，等待用户确认后再进入下一阶段
- 更适合高计算成本、需要审批的长时任务

---

## 5. 为什么 Claude Code 没有使用 LangGraph？

从代码中可以看出几个深层原因：

### 5.1 产品定位不同

Claude Code 是**终端交互式编程助手**，核心体验是：
- 用户说一句话
- LLM 在几轮内完成代码修改
- 结果立即反馈给用户

Task V2 在这个定位下只是"工作流便签"，不是长时编排引擎。绝大多数任务在**几分钟到十几分钟**内完成，不需要小时级的 checkpoint 和恢复。

### 5.2 "LLM 即调度器"的设计哲学

Claude Code 的一个核心设计选择是：**不构建显式的计划执行引擎，而是把计划能力交给 LLM**。Task V2 的任务列表只是 LLM 的"外部工作记忆"，让 LLM 在多轮对话中保持对复杂任务的跟踪。调度决策（先做什么、后做什么、谁来做）完全由 LLM 的 reasoning 驱动。

这与 Deer-Flow 的"supervisor node 生成结构化计划并路由"形成鲜明对比。

### 5.3 工程 pragmatism

Claude Code 的代码库有近 2000 个 TS 文件，是一个巨型工程。引入 LangGraph 意味着：
- 新增大量 Python 依赖（LangGraph 主要是 Python 生态）
- 需要维护 graph topology、state schema、checkpoint migration
- 与现有的 Bun/TypeScript/Ink CLI 架构格格不入

自研轻量级 JSON 文件系统，对于他们的需求来说，是**足够且更可控**的选择。

---

## 6. 直接回答：开发自己的 Agent Loop 时，是否应该用 LangGraph？

这取决于你的产品定位，没有绝对答案。

### 6.1 选择自研（类似 Claude Code）如果你的场景是：

- **交互式对话为主**：用户在聊天界面/终端与 agent 实时互动，每轮对话都可能改变计划
- **LLM 作为核心调度器**：你希望 LLM 拥有动态修改任务、调整优先级、打破依赖的完全自由
- **技术栈在 TypeScript/JS 生态**：不想为引入 LangGraph 而跨语言或依赖不成熟的 JS 版本
- **快速迭代**：你想保持对任务调度逻辑的完全控制，不被框架的 node-edge 抽象约束
- **任务图是涌现式的**：计划不是预定义的，而是由 LLM 根据上下文动态生成的

> **核心判断**：如果你的"task graph"本质上只是 LLM 的**外部工作记忆**，而不是一个需要框架来**强制执行**的流程引擎，那么像 Claude Code 一样用简单的 JSON + 文件锁就足够了。

### 6.2 选择 LangGraph（类似 Deer-Flow）如果你的场景是：

- **需要框架级执行保证**：任务有明确的阶段、条件分支、循环，必须由框架而非 LLM 来确保执行
- **多 agent 深度编排**：需要一个中心 supervisor 显式控制子 agent 的生命周期和路由
- **进程崩溃恢复是刚需**：任务需要在 checkpoint 处恢复，而不只是重新读取任务列表
- **Human-in-the-loop 是核心需求**：需要在特定节点暂停等待审批
- **技术栈在 Python 生态**：能够充分利用 LangGraph 的成熟生态
- **愿意接受框架约束**：你认可将部分调度自由让渡给图框架，以换取可预测性和可靠性

> **核心判断**：如果你需要的是一个**真正的流程引擎**——即工作流的正确执行不完全依赖 LLM 的 reasoning，而是由框架保证的——LangGraph 的价值会非常明显。

### 6.3 中间路线

还有一种务实的中间路线：
- **任务管理（todos/tasks）**：自研轻量级系统（JSON / SQLite），像 Claude Code 一样交给 LLM 管理
- **复杂 workflow 编排**：在特定长时/批处理场景下引入 LangGraph（或 LangGraph JS），像 Deer-Flow 一样做 supervisor-subgraph

这与 Claude Code 自身的 `batch` skill 设计哲学一致：
- 日常 coding：用 Task V2
- 大型批量重构：启动 5-30 个 background agents，每个在自己的 worktree 中独立运行

---

## 7. 关键对比一览表

| 维度 | Claude Code Task V2 | Deer-Flow 2.0 |
|------|---------------------|---------------|
| **核心框架** | 自研（TypeScript） | LangGraph + LangChain（Python） |
| **调度模式** | LLM 自我调度（分布式） | Supervisor 显式调度（集中式） |
| **图表达** | 隐式（`blocks/blockedBy` DAG） | 显式（`StateGraph` 节点和边） |
| **依赖处理** | 抢占前简单检查 | 条件边动态路由 |
| **持久化** | 磁盘 JSON + 文件锁 | SQLite/PostgreSQL checkpoint |
| **崩溃恢复** | 不支持 agent 执行中恢复 | 从 checkpoint 恢复完整状态 |
| **HITL** | Turn-based（Plan Mode / AskUser） | Checkpoint 级暂停（一等公民） |
| **典型任务时长** | 分钟级 | 小时级 |
| **并发上限** | 软性建议 5-30（batch skill） | 取决于 checkpoint 后端 |
| **部署复杂度** | 低 | 高（需 LangGraph server + DB + sandbox） |
| **适用定位** | 交互式编程助手 | 长时自主 SuperAgent harness |

---

## 8. 结论

**"有依赖关系 = 应该用图框架" 这个直觉是错误的。** 

Claude Code 证明了一个重要的设计选择：
- 如果任务依赖只是为了让 LLM 自我追踪进度、辅助调度决策，**轻量级的 JSON 文件系统完全足够**。
- 只有当依赖关系需要被**框架强制执行**（自动路由、条件分支、崩溃恢复、长时编排）时，LangGraph 这样的图框架才真正发挥价值。

所以，对于你自己的 agent loop：
- **不要因为有 `blocks`/`blockedBy` 就引入 LangGraph**。
- **要因为有复杂的、需要框架保障的 workflow 执行需求，才引入 LangGraph**。

Claude Code 和 Deer-Flow 代表了两种截然不同的产品哲学，没有高下之分，只有场景之分。

---

## 附录：关键参考来源

- Deer-Flow Architecture: `github.com/bytedance/deer-flow/blob/main/backend/docs/ARCHITECTURE.md`
- Deer-Flow 深度解析: `sitepoint.com/deerflow-deep-dive-managing-longrunning-autonomous-tasks/`
- Deer-Flow 2.0 实测: `medium.com/synthetic-futures/i-set-up-bytedances-deerflow-2-0-90bb201985ad`
- Claude Code Task V2: `src/utils/tasks.ts`（本文档前面已详细分析）
- Claude Code batch skill: `src/skills/bundled/batch.ts`
