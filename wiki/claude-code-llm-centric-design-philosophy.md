# Claude Code 的 LLM-Centric 设计哲学：系统即辅助，智能在模型

> **核心论点**：Claude Code 的整个架构设计围绕一个核心原则展开——**LLM 是唯一的 orchestrator（调度中枢），所有系统模块（任务管理、子 Agent 调度、工具执行、权限控制）本质上都是为 LLM 提供原子性辅助和环境支持，而非替代 LLM 做决策。**

这与其他多 Agent 框架（如基于 LangGraph 的 Deer-Flow）形成鲜明对比：后者将 supervisor 节点、图路由、条件边等编排逻辑**硬编码到框架中**，LLM 只是图中的一个节点；而 Claude Code 把**计划、路由、调度的自由完全交给 LLM**，系统只负责防止竞态、持久化状态、执行权限校验等底层支撑。

下面我们从代码层面，用具体模块来论证这一设计哲学。

---

## 1. 任务管理：Task V2 是 LLM 的"外部工作记忆"
wiki/claude-code-llm-centric-design-philosophy.md
### 1.1 没有 Supervisor，只有 LLM + 文件锁

在 `src/utils/tasks.ts` 中，Task V2 的核心数据结构是简单的 JSON 文件：

```typescript
interface Task {
  id: string
  subject: string
  description: string
  owner?: string
  status: 'pending' | 'in_progress' | 'completed'
  blocks: string[]
  blockedBy: string[]
}
```

关键设计：**系统从不主动决定"下一步该做什么"**。任务的创建、更新、依赖设置、完成标记，全部由 LLM 通过 `TaskCreateTool`、`TaskUpdateTool`、`TaskListTool` 调用驱动。

`claimTask()`（`src/utils/tasks.ts:541`）的代码逻辑是：

```typescript
export async function claimTask(taskListId, taskId, agentName, options) {
  // 1. 原子性检查：任务是否存在？是否已有 owner？是否已完成？
  // 2. 依赖是否全部完成？
  // 3. 如果是 in-process teammate，可选检查 agent 是否 busy
  // ...
}
```

这里 `claimTask` **不做任何调度决策**，它只是：
- 验证 LLM 或其他 agent 的**抢占请求**是否合法
- 通过 `proper-lockfile` 保证文件操作的原子性

当 in-process teammate 启动时，`tryClaimNextTask()`（`src/utils/swarm/inProcessRunner.ts:624`）也只是**扫描 LLM 已经创建好的任务列表**，找到第一个可用的去抢占。谁先抢到完全取决于文件系统时序，系统并没有一个中心调度器在"分配"任务。

### 1.2 涌现式任务图

Claude Code 的任务依赖关系（`blocks` / `blockedBy`）不是由框架预定义的图拓扑，而是**由 LLM 在对话过程中动态生成和修改的**。这与 LangGraph 的 `StateGraph.addEdge()` 有本质区别：

- **LangGraph**：图的节点和边在 `workflow.compile()` 时就固定了
- **Claude Code**：任务图在每一轮对话中都可能被 LLM 重写——增删节点、调整依赖、变更 owner

这意味着 Task V2 不是"工作流引擎"，而是**LLM 的长期工作记忆外存**。

### 1.3 Todo V1 vs Task V2 的切换也印证了这一点

`isTodoV2Enabled()`（`src/utils/tasks.ts:133`）根据是否是 interactive session 来决定使用哪种后端：
- **Todo V1**：内存中的 `AppState.todos`，LLM 通过 `TodoWriteTool` 直接写入
- **Task V2**：磁盘上的 JSON 文件，LLM 通过 Task 系列工具操作

无论后端是内存还是磁盘，**接口层都是面向 LLM 的 tool call**，系统内部只是换了一种持久化方式。这再次说明任务管理模块的设计目标是"让 LLM 能方便地自我管理"，而不是"让系统来管理 LLM"。

---

## 2. 子 Agent 调度：LLM 决定何时 spawn，系统只负责启动容器

### 2.1 AgentTool：LLM 的"自我调用"接口

`src/tools/AgentTool/AgentTool.tsx` 是子 Agent 调度的唯一入口。它的输入参数全部由 LLM 生成：

```typescript
{
  agent: string,           // LLM 决定用哪个 agent
  prompt: string,          // LLM 决定给子 agent 什么指令
  run_in_background?: boolean,  // LLM 决定是否异步执行
}
```

`shouldRunAsync`（`src/tools/AgentTool/AgentTool.tsx:567`）的逻辑如下：

```typescript
const shouldRunAsync = (
  run_in_background === true ||
  selectedAgent.background === true ||
  isCoordinator ||
  forceAsync ||
  assistantForceAsync ||
  (proactiveModule?.isProactiveActive() ?? false)
) && !isBackgroundTasksDisabled
```

注意：**真正决定是否异步的，首先是 LLM 传入的 `run_in_background`**。其他条件（如 coordinator mode、proactive）本质上是系统对**更高层 LLM 意图**的响应，而不是系统在替 LLM 做调度决策。

### 2.2 没有全局 Agent 调度器

在 Claude Code 中，**不存在一个中心模块来决定"现在应该启动哪些子 agent"**。一个复杂任务如果要拆成 20 个并行的子 agent，这个决策完全由 LLM 在单轮对话中做出——它会生成 20 个 `AgentTool` 调用。

唯一的"调度建议"来自 `batch` skill（`src/skills/bundled/batch.ts`），它作为 prompt 文本告诉 LLM：

```typescript
const MIN_AGENTS = 5
const MAX_AGENTS = 30
```

但这仍然是**建议 LLM 如何思考**，而不是系统层面的硬性并发配额。系统只是在 `StreamingToolExecutor` 中验证这些 tool call 是否可以安全并行执行。

### 2.3 并发控制：系统被动放行，而非主动编排

`src/services/tools/StreamingToolExecutor.ts` 的并发逻辑（`canExecuteTool`，line 129）是：

```typescript
private canExecuteTool(isConcurrencySafe: boolean): boolean {
  const executingTools = this.tools.filter(t => t.status === 'executing')
  return (
    executingTools.length === 0 ||
    (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe))
  )
}
```

这里的关键是：**工具调用批次由 LLM 在一次 assistant message 中生成，系统只负责检查"当前正在执行的工具是否都允许并发"**。如果队列中只有 `AgentTool`（`isConcurrencySafe = true`），那么这 20 个 agent 就会真正并行执行；如果队列中混有非并发安全工具（如 `FileWriteTool`），则会串行化。

这不是一个"调度器"在决定"先执行 A 再执行 B"，而是一个**安全阀**在判断"LLM 要求的并行操作是否安全"。

---

## 3. 工具系统：LLM 是"驾驶员"，工具是"手脚"

### 3.1 所有工具都面向 LLM 的 reasoning 设计

`src/tools.ts` 注册了近 40 个工具，它们的共同特征是：
- **输入参数由 LLM 在一次 tool_use block 中填充**
- **执行逻辑是原子性的**，不包含跨工具的编排逻辑
- **结果以 tool_result block 返回给 LLM**，由 LLM 决定下一步

以 `FileReadTool`、`FileEditTool`、`BashTool` 为例：
- 读哪个文件？LLM 决定
- 改哪几行？LLM 决定（通过精确的字符串匹配）
- 执行什么命令？LLM 决定

系统不会自作主张地"既然你读了 A 文件，我猜你也想读 B 文件"。**每一个 tool call 都是 LLM 显式推理的结果**。

### 3.2 Tool loop 的核心在 QueryEngine

`src/QueryEngine.ts` 是 Claude Code 的心脏。它的主循环可以概括为：

```
1. 发送上下文（system prompt + history）给 LLM API
2. 等待 LLM 返回 content blocks（可能是 thinking、text、tool_use）
3. 如果是 tool_use，调用对应的 tool
4. 将 tool_result 追加到 history
5. 回到步骤 1
```

在这个循环中，**唯一的决策者永远是 LLM**。系统只是 message router + tool executor。这与 Deer-Flow 的 LangGraph loop 有本质区别：LangGraph 的循环是 `state -> node -> conditional edge -> next node`，框架本身在做大量路由决策。

---

## 4. 计划模式（Plan Mode）：LLM 生成计划，系统只做呈现

Claude Code 支持 `/plan` 命令，进入 Plan Mode 后：
- LLM 输出结构化的计划项（plan items）
- 用户确认后，计划项被持久化
- 后续每一轮对话，已完成的计划项会被作为上下文喂回给 LLM

这里的关键是：**系统不理解计划的内容和语义**。它不知道"第 3 步依赖于第 2 步"，也不强制执行计划的顺序。计划的执行完全依赖 LLM 在后续对话中**自我跟踪进度**，系统只是把"当前计划列表"渲染到 UI 上。

这再次印证了 LLM-centric 的设计哲学：**系统提供的是"状态呈现"和"上下文注入"，而不是"计划执行引擎"**。

---

## 5. 权限系统：不阻止 LLM 的意图，只请求确认

### 5.1 权限作为 tool 调用的 interceptor

`src/hooks/toolPermission/` 下的权限系统处理流程是：

1. LLM 发起一个 `Bash(rm -rf /)` 的 tool_use
2. `checkBashPermissionForTool` 评估风险等级
3. 如果是高风险，弹出交互式确认对话框（`interactiveHandler.ts`）
4. 用户确认后，tool 继续执行；用户拒绝后，以 `permission_denied` 结果返回给 LLM
5. LLM 收到拒绝结果后，**自己决定**如何调整策略

注意：权限系统**没有修改 LLM 的意图**，也没有自动替 LLM 想出一个替代方案。它只是：
- 评估风险
- 必要时中断并请求人类确认
- 将结果反馈给 LLM，由 LLM 自行 replan

这是典型的 LLM-centric 设计：**系统是人类与 LLM 之间的安全闸门，而不是决策代理**。

### 5.2 自动行为也被约束在"原子性辅助"层面

Task V2 中有一些自动行为，但它们都是**无状态、无决策的辅助逻辑**：
- `unassignTeammateTasks`（`src/utils/tasks.ts:818`）：当 teammate 退出时，自动释放其 owner 的任务。这只是清理状态。
- `tryClaimNextTask`（`src/utils/swarm/inProcessRunner.ts:624`）：空闲 teammate 自动抢任务。这只是基于时序的原子抢占，不是调度分配。
- `task_reminder`：10 轮未操作任务时给 LLM 发 nudge。这只是**提醒 LLM 去管理**，系统不会替 LLM 做任务管理决策。

---

## 6. 总结：Claude Code 的架构公式

我们可以用以下公式来概括 Claude Code 的架构设计哲学：

```
Claude Code = LLM (唯一的 orchestrator & planner)
           + Tool Registry (让 LLM 能调用外部能力)
           + Task State Store (让 LLM 能外化长期记忆)
           + Permission Layer (在人类许可下放行 LLM 的意图)
           + Execution Sandbox (安全地执行 LLM 决定的命令)
           + UI Layer (呈现 LLM 的思考过程和工具执行结果)
```

在这个公式中：
- **没有 Workflow Engine**
- **没有 Supervisor Node**
- **没有 Graph Router**
- **没有 Predefined Orchestration Logic**

所有需要"智能"的决策（计划、调度、路由、replanning、优先级调整）都被**有意识地推给了 LLM**。

### 这与 LangGraph 型框架的本质区别

| 维度 | Claude Code (LLM-Centric) | LangGraph / Deer-Flow (Framework-Centric) |
|------|---------------------------|-------------------------------------------|
| **计划能力** | 在 LLM 的 reasoning 中 | 在 supervisor node 和 graph topology 中 |
| **调度决策** | LLM 通过 tool call 动态决定 | 框架通过 conditional edge 强制执行 |
| **任务图** | 涌现式，由 LLM 创建和修改 | 预定义式，在 compile 时固定 |
| **系统角色** | LLM 的辅助基础设施 | 包含 LLM 在内的更大 orchestration 框架 |
| **灵活性** | 极高（LLM 可随时打破规则） | 中等（规则由框架保障，修改需改图） |
| **可靠性** | 依赖 LLM 能力 | 框架提供执行保证 |

### 设计选择背后的 trade-off

Claude Code 选择 LLM-centric 路线，本质上是**用"框架可靠性"换取"LLM 灵活性"**：
- **优势**：无需维护复杂的图状态机；LLM 可以随时根据用户的新指令 replan；架构极简，与对话式 CLI 的天然形态高度契合。
- **代价**：没有框架级的执行保证；如果 LLM 的 reasoning 出错（比如忘记标记任务完成、错误设置依赖），系统不会自动纠正；长时自主运行的容错性较低。

理解这一点，对于设计你自己的 Agent 系统至关重要：
> **如果你相信 LLM 的 reasoning 能力足以胜任调度中枢，且你的产品形态是高度交互式的对话系统，那么 Claude Code 的 LLM-centric 路线是值得借鉴的。如果你需要框架来强制执行复杂工作流，并愿意牺牲部分灵活性，那么 LangGraph 式的 framework-centric 路线更合适。**

---

## 附录：佐证文档的关键代码引用

| 模块 | 文件路径 | 核心逻辑 |
|------|---------|---------|
| Task V2 核心 | `src/utils/tasks.ts` | JSON 文件持久化、`claimTask` 抢占检查、`proper-lockfile` 并发控制 |
| In-Process Teammate | `src/utils/swarm/inProcessRunner.ts:624` | `tryClaimNextTask` 自动抢任务 |
| Todo V1 | `src/tools/TodoWriteTool/TodoWriteTool.ts:65` | LLM 直接写入 `AppState.todos` |
| Agent 调度入口 | `src/tools/AgentTool/AgentTool.tsx:567` | `shouldRunAsync` 解析 LLM 的 `run_in_background` 意图 |
| 并发执行 | `src/services/tools/StreamingToolExecutor.ts:129` | `canExecuteTool` 被动放行并发安全工具 |
| Batch Skill | `src/skills/bundled/batch.ts` | LLM 软性建议 5-30 个并行 background agents |
| 主循环 | `src/QueryEngine.ts` | LLM → tool_use → tool execution → tool_result → LLM 的循环 |
| 权限处理 | `src/hooks/toolPermission/interactiveHandler.ts` | 高风险 tool 的用户确认拦截 |
| 任务自动释放 | `src/utils/tasks.ts:818` | `unassignTeammateTasks` teammate 退出时的状态清理 |

---

*撰写日期：2026-04-13*
*分析基于 Claude Code `main` 分支源码*
