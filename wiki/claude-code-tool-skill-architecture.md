# Claude Code Tool & Skill 架构深度研究报告

> 研究范围：Claude Code 的内置 Tool、Skill 设计以及发现和调用机制
> 
> 基于代码版本：Claude Code 源码分析（2026年1月）

---

## 目录

1. [架构总览](#一架构总览)
2. [Tool 基础架构](#二tool-基础架构)
3. [内置 Tool 分类](#三内置-tool-分类)
4. [Skill 系统](#四skill-系统)
5. [Tool 发现机制](#五tool-发现机制)
6. [Tool 调用执行机制](#六tool-调用执行机制)
7. [关键设计决策](#七关键设计决策)

---

## 一、架构总览

Claude Code 的 Tool 和 Skill 架构是一个分层的、可扩展的系统，主要分为三个层次：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         用户交互层 (UI Layer)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  REPL.tsx    │  │   SDK API    │  │   CLI Mode   │  │  print.ts    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Tool 管理层 (Tool Management)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Tool Registry (tools.ts)                        │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ Built-in     │  │ MCP Tools    │  │ Deferred     │              │   │
│  │  │ Tools        │  │ (Dynamic)    │  │ Tools        │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Skill Registry (skills/)                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ Bundled      │  │ User/Project │  │ MCP Skills   │              │   │
│  │  │ Skills       │  │ Skills       │  │              │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Tool 执行层 (Tool Execution)                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   StreamingToolExecutor                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │ Permission   │  │ Concurrent   │  │ Hook         │              │   │
│  │  │ Check        │  │ Execution    │  │ System       │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、Tool 基础架构

### 2.1 Tool 类型定义 (Tool.ts)

Claude Code 的核心 Tool 架构定义在 `Tool.ts` 中，这是一个完整的类型系统：

```typescript
export type Tool<
  Input extends AnyObject = AnyObject,
  Output = unknown,
  P extends ToolProgressData = ToolProgressData,
> = {
  // 基础属性
  name: string
  aliases?: string[]
  searchHint?: string  // 用于 ToolSearch 关键字匹配
  
  // 核心方法
  call(
    args: z.infer<Input>,
    context: ToolUseContext,
    canUseTool: CanUseToolFn,
    parentMessage: AssistantMessage,
    onProgress?: ToolCallProgress<P>,
  ): Promise<ToolResult<Output>>
  
  description(/* ... */): Promise<string>
  prompt(/* ... */): Promise<string>
  
  // Schema 定义
  readonly inputSchema: Input
  readonly inputJSONSchema?: ToolInputJSONSchema
  outputSchema?: z.ZodType<unknown>
  
  // 行为特性
  isConcurrencySafe(input: z.infer<Input>): boolean
  isEnabled(): boolean
  isReadOnly(input: z.infer<Input>): boolean
  isDestructive?(input: z.infer<Input>): boolean
  interruptBehavior?(): 'cancel' | 'block'
  
  // MCP/Deferred 相关
  isMcp?: boolean
  isLsp?: boolean
  shouldDefer?: boolean
  alwaysLoad?: boolean
  
  // 其他可选方法
  validateInput?(): Promise<ValidationResult>
  checkPermissions(): Promise<PermissionDecision>
  backfillObservableInput?(): void
  // ...
}
```

### 2.2 ToolUseContext - 工具执行上下文

Tool 执行时接收的上下文对象，包含丰富的运行时信息：

```typescript
export type ToolUseContext = {
  options: {
    commands: Command[]
    tools: Tools
    mainLoopModel: string
    thinkingConfig: ThinkingConfig
    mcpClients: MCPServerConnection[]
    mcpResources: Record<string, ServerResource[]>
    isNonInteractiveSession: boolean
    agentDefinitions: AgentDefinitionsResult
    refreshTools?: () => Tools  // 动态刷新工具
    // ...
  }
  abortController: AbortController
  readFileState: FileStateCache
  getAppState(): AppState
  setAppState(f: (prev: AppState) => AppState): void
  setInProgressToolUseIDs: (f: (prev: Set<string>) => Set<string>) => void
  updateFileHistoryState: (updater) => void
  updateAttributionState: (updater) => void
  // ... 20+ 个属性
}
```

### 2.3 buildTool - Tool 工厂函数

Tool 使用工厂函数创建，简化 Tool 定义：

```typescript
export const SkillTool: Tool<InputSchema, Output, Progress> = buildTool({
  name: SKILL_TOOL_NAME,
  searchHint: 'invoke a slash-command skill',
  maxResultSizeChars: 100_000,
  
  // Schema
  get inputSchema(): InputSchema { return inputSchema() },
  get outputSchema(): OutputSchema { return outputSchema() },
  
  // 描述
  description: async ({ skill }) => `Execute skill: ${skill}`,
  prompt: async () => getPrompt(getProjectRoot()),
  
  // 行为
  isConcurrencySafe: () => false,  // Skill 是串行的
  isEnabled: () => true,
  isReadOnly: () => false,
  
  // 核心调用
  async call(input, context, canUseTool, parentMessage, onProgress) {
    // ... 实现
  },
  
  // 权限检查
  async checkPermissions(input, context) {
    // ... 返回 PermissionDecision
  },
  
  // 输入验证
  async validateInput(input, context): Promise<ValidationResult> {
    // ... 返回验证结果
  }
} satisfies ToolDef<InputSchema, Output, Progress>)
```

---

## 三、内置 Tool 分类

Claude Code 的内置 Tool 可以分为以下几大类：

### 3.1 文件操作工具

| Tool | 功能 | 并发安全 | 破坏性 |
|------|------|----------|--------|
| `FileReadTool` | 读取文件内容 | ✅ | 只读 |
| `FileEditTool` | 编辑文件（搜索替换）| ❌ | ✅ |
| `FileWriteTool` | 写入/创建文件 | ❌ | ✅ |
| `NotebookEditTool` | 编辑 Jupyter Notebook | ❌ | ✅ |
| `GlobTool` | 文件模式匹配 | ✅ | 只读 |
| `GrepTool` | 文本搜索 | ✅ | 只读 |

### 3.2 Shell 执行工具

| Tool | 功能 | 并发安全 | 特殊处理 |
|------|------|----------|----------|
| `BashTool` | 执行 Bash 命令 | 条件性 | Bash 错误会取消兄弟工具 |
| `PowerShellTool` | 执行 PowerShell | 条件性 | Windows 专用 |

**并发安全判断**：`isConcurrencySafe` 基于输入分析（如 read-only 命令是安全的）

### 3.3 Agent/任务工具

| Tool | 功能 | 模式 |
|------|------|------|
| `AgentTool` | 创建子 Agent | fork 子进程 |
| `SkillTool` | 执行 Skill | inline/fork |
| `TaskCreateTool` | 创建后台任务 | - |
| `TaskStopTool` | 停止任务 | - |
| `TaskListTool` | 列出任务 | - |
| `TaskOutputTool` | 获取任务输出 | - |
| `TaskUpdateTool` | 更新任务 | - |
| `SendMessageTool` | 发送消息给 Agent | - |

### 3.4 计划模式工具

| Tool | 功能 |
|------|------|
| `EnterPlanModeTool` | 进入计划模式 |
| `ExitPlanModeV2Tool` | 退出计划模式 |
| `TodoWriteTool` | 管理 Todo 列表 |

### 3.5 MCP 相关工具

| Tool | 功能 |
|------|------|
| `MCPTool` | 调用 MCP Server 工具 |
| `ListMcpResourcesTool` | 列出 MCP 资源 |
| `ReadMcpResourceTool` | 读取 MCP 资源 |
| `ToolSearchTool` | 发现并加载 Deferred Tools |

### 3.6 其他工具

| Tool | 功能 |
|------|------|
| `WebSearchTool` | 网络搜索 |
| `WebFetchTool` | 获取网页内容 |
| `AskUserQuestionTool` | 向用户提问 |
| `ConfigTool` | 配置管理 |
| `BriefTool` | 生成简报 |
| `TeamCreateTool/TeamDeleteTool` | 团队管理 |

---

## 四、Skill 系统

### 4.1 Skill 是什么？

Skill 是 Claude Code 的高级功能，本质上是**可复用的、带提示词的命令**：

```
Skill = Markdown文件 + Frontmatter配置 + 可执行逻辑
```

Skill 与 Tool 的区别：
- **Tool**: 底层原子操作，直接执行（如读文件、执行命令）
- **Skill**: 高层复合操作，展开为提示词由模型处理（如 "review-pr"、"commit"）

### 4.2 Skill 目录结构

```
skills/
├── bundled/                    # 内置 Skills
│   ├── index.ts               # 注册入口
│   ├── batch.ts               # /batch skill
│   ├── debug.ts               # /debug skill
│   ├── remember.ts            # /remember skill
│   ├── simplify.ts            # /simplify skill
│   ├── verify.ts              # /verify skill
│   └── ...
├── loadSkillsDir.ts           # Skill 加载器
└── mcpSkillBuilders.ts        # MCP Skill 构建

用户/项目 Skills 目录:
~/.claude/skills/              # 用户级 Skills
./.claude/skills/              # 项目级 Skills
.claude/commands/              # 兼容旧版命令目录
```

### 4.3 Skill 格式 (SKILL.md)

```markdown
---
name: "Commit Changes"
description: "Create a git commit with a thoughtful message"
arguments:
  - message
  - files
allowed-tools:
  - Bash
  - FileRead
when_to_use: "When the user wants to commit changes"
model: sonnet  # 可选：覆盖模型
effort: high   # 可选：指定 effort 级别
context: fork  # 可选：执行上下文 (inline/fork)
user-invocable: true  # 用户可直接调用
---

# Commit Changes Skill

Create a thoughtful commit message for the changes...

## Instructions

1. Check git status to see what changed
2. Read relevant files to understand the changes
3. Write a commit message that...

## Example

```bash
git add {{files}}
git commit -m "{{message}}"
```
```

### 4.4 Skill 加载流程

```typescript
// skills/loadSkillsDir.ts
export const getSkillDirCommands = memoize(async (cwd: string): Promise<Command[]> => {
  // 1. 加载多个来源的 Skills
  const [
    managedSkills,      // 策略管理的 Skills
    userSkills,         // 用户级 ~/.claude/skills
    projectSkills,      // 项目级 ./.claude/skills
    additionalSkills,   // --add-dir 指定的额外目录
    legacyCommands,     // 兼容旧版 .claude/commands
  ] = await Promise.all([...])
  
  // 2. 合并并去重（基于文件真实路径）
  const deduplicated = deduplicateByRealpath(allSkills)
  
  // 3. 分离条件 Skills
  const unconditional = []
  const conditional = []
  for (const skill of deduplicated) {
    if (skill.paths && !isActivated(skill.name)) {
      conditional.push(skill)  // 存储待激活
    } else {
      unconditional.push(skill)
    }
  }
  
  return unconditional
})
```

### 4.5 Skill 执行模式

Skill 有两种执行模式：

#### Inline 模式（默认）

```
┌────────────────────────────────────────────────────┐
│ 主对话上下文                                        │
│                                                    │
│ User: "/commit my changes"                         │
│                                                    │
│ ▼ SkillTool.call()                                 │
│                                                    │
│ ┌──────────────────────────────────────────────┐  │
│ │ 1. 解析 Skill                                  │  │
│ │ 2. 展开 Prompt（参数替换、!命令执行）            │  │
│ │ 3. 返回 newMessages 注入主对话                  │  │
│ └──────────────────────────────────────────────┘  │
│                                                    │
│ [Skill 展开的内容作为 UserMessage 进入主对话]       │
│                                                    │
│ Claude 继续处理...                                  │
└────────────────────────────────────────────────────┘
```

#### Fork 模式

```
┌────────────────────────────────────────────────────┐
│ 主对话上下文              │  Forked Agent (子进程)  │
│                           │                         │
│ User: "/verify"           │                         │
│                           │                         │
│ ▼ SkillTool.call()        │  ┌─────────────────┐   │
│                           │  │ runAgent()      │   │
│ ┌─────────────────────┐   │  │ - 复制上下文     │   │
│ │ executeForkedSkill() │   │  │ - 独立执行       │   │
│ └─────────────────────┘   │  │ - 返回结果       │   │
│                           │  └─────────────────┘   │
│ ◄── 等待子 Agent 完成 ────┤                         │
│                           │                         │
│ [返回结果作为 tool_result]  │                         │
└────────────────────────────────────────────────────┘
```

---

## 五、Tool 发现机制

### 5.1 工具分层架构

```
┌────────────────────────────────────────────────────────────────┐
│                        可用工具池                                │
├────────────────────────────────────────────────────────────────┤
│  Built-in Tools (alwaysLoad=true)                              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │ Bash    │ │ Read    │ │ Edit    │ │ Agent   │  ...         │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘              │
├────────────────────────────────────────────────────────────────┤
│  MCP Tools (动态发现，alwaysLoad 或 defer)                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                          │
│  │ mcp__   │ │ mcp__   │ │ mcp__   │  ...                     │
│  │ slack__ │ │ github__│ │ jira__  │                          │
│  │ send    │ │ createPR│ │ create  │                          │
│  └─────────┘ └─────────┘ └─────────┘                          │
├────────────────────────────────────────────────────────────────┤
│  Deferred Tools (ToolSearch 发现后加载)                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                          │
│  │ LSP     │ │ Web     │ │ Verify  │  ...                     │
│  │ Tool    │ │ Browser │ │ Plan    │                          │
│  └─────────┘ └─────────┘ └─────────┘                          │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 ToolSearch 发现机制

**ToolSearchTool** 是 Claude Code 的动态工具发现系统：

```typescript
// 模型调用 ToolSearch
await ToolSearchTool.call({
  query: "slack",           // 搜索查询
  max_results: 5
})

// 返回 tool_reference 块
{
  matches: ["mcp__slack__send_message", "mcp__slack__list_channels"],
  query: "slack",
  total_deferred_tools: 42
}
```

**发现后加载流程**：

```
1. 模型调用 ToolSearchTool
   └─► 关键词匹配（名称、描述、searchHint）
       
2. 返回 tool_reference 块
   └─► 客户端记录到 discoveredSkillNames
   
3. 下次 API 调用时
   └─► claude.ts 过滤工具列表
   └─► 只包含已发现的 deferred tools
   
4. 模型现在可以使用这些工具
```

### 5.3 MCP Tool 发现流程

```
┌────────────────────────────────────────────────────────────────┐
│ MCP Server 连接流程                                              │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  1. MCP Server 配置 (settings.json)                             │
│     {                                                          │
│       "mcpServers": {                                          │
│         "slack": {                                             │
│           "command": "npx",                                    │
│           "args": ["-y", "@anthropic-ai/mcp-slack"]            │
│         }                                                      │
│       }                                                        │
│     }                                                          │
│                                                                │
│  2. 启动时连接 MCP Servers                                      │
│     └─► useManageMCPConnections hook                          │
│         └─► 为每个 server 创建 stdio/sse/ws 连接               │
│                                                                │
│  3. 握手获取工具列表 (tools/list)                                │
│     └─► 将 MCP tools 映射为 Claude Code Tools                  │
│         name: "mcp__{server}__{tool}"                           │
│                                                                │
│  4. 根据 _meta 决定加载策略                                     │
│     ├─► alwaysLoad: true  → 立即包含在 prompt 中               │
│     ├─► defer_loading: true → 等待 ToolSearch 发现             │
│     └─► 默认 → 根据工具数量阈值决定是否 defer                   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 5.4 动态 Skill 发现

Skill 支持两种动态发现：

**1. 路径触发的 Skill 发现**

```typescript
// 当读取/写入文件时
discoverSkillDirsForPaths(filePaths, cwd)
  └─► 从文件路径向上遍历到 cwd
  └─► 发现 .claude/skills 目录
  └─► 加载目录中的 Skills
```

**2. 条件 Skill 激活**

```yaml
# SKILL.md frontmatter
paths:
  - "src/**/*.ts"    # 当操作 TypeScript 文件时激活
  - "**/*.test.js"   # 当操作测试文件时激活
```

---

## 六、Tool 调用执行机制

### 6.1 完整调用流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Tool 调用完整流程                               │
└─────────────────────────────────────────────────────────────────────────┘

  1. 模型生成 tool_use
     └─► AssistantMessage 包含 tool_use block
     
  2. query.ts 处理
     └─► StreamingToolExecutor.addTool(toolUse, assistantMessage)
     
  3. 并发控制检查
     └─► canExecuteTool(isConcurrencySafe)
         ├─► 串行工具：等待其他工具完成
         └─► 并行工具：如果都是 concurrency-safe，并行执行
         
  4. 权限检查 (checkPermissionsAndCallTool)
     ├─► validateInput()           # Zod schema 验证
     ├─► tool.validateInput?.()    # 自定义验证
     ├─► checkPermissions()        # 权限规则匹配
     │   ├─► Deny 规则匹配 → 拒绝
     │   ├─► Allow 规则匹配 → 允许
     │   └─► 默认 → Ask 用户
     ├─► PreToolUse Hooks          # 钩子系统
     └─► 权限对话框 (如果需要)
     
  5. 执行 Tool
     └─► tool.call(input, context, canUseTool, parentMessage, onProgress)
         ├─► 同步/异步执行
         ├─► 流式进度报告 (onProgress)
         └─► 返回 ToolResult
     
  6. 后处理
     ├─► PostToolUse Hooks
     ├─► 结果处理 (tool_result block)
     └─► 附加新消息 (newMessages)
     
  7. 返回给模型
     └─► UserMessage 包含 tool_result
```

### 6.2 StreamingToolExecutor 详解

```typescript
class StreamingToolExecutor {
  private tools: TrackedTool[] = []
  
  // 添加工具
  addTool(block: ToolUseBlock, assistantMessage: AssistantMessage) {
    // 1. 检查工具是否存在
    // 2. 判断并发安全性
    // 3. 加入队列
    // 4. 触发 processQueue()
  }
  
  // 处理队列
  private async processQueue() {
    for (const tool of this.tools) {
      if (canExecuteTool(tool.isConcurrencySafe)) {
        await this.executeTool(tool)
      }
    }
  }
  
  // 执行单个工具
  private async executeTool(tool: TrackedTool) {
    // 1. 设置状态 'executing'
    // 2. 调用 runToolUse() 生成器
    // 3. 流式产出 MessageUpdate
    // 4. 完成时设置状态 'completed'
  }
  
  // 获取结果（生成器）
  async *getRemainingResults() {
    while (hasUnfinishedTools()) {
      yield* getCompletedResults()
      await waitForExecutingOrProgress()
    }
  }
}
```

### 6.3 并发控制规则

```
规则 1: 串行工具独占执行
┌────────────────────────────────────────┐
│ [Read] [Edit] [Read]                   │
│   ✅     ❌     ⏳ (等待 Edit 完成)      │
└────────────────────────────────────────┘

规则 2: 并行安全工具可并发
┌────────────────────────────────────────┐
│ [Read] [Grep] [Glob]                   │
│   ✅     ✅     ✅ (全部并行)            │
└────────────────────────────────────────┘

规则 3: 混合情况
┌────────────────────────────────────────┐
│ [Read] [Edit] [Grep] [Read]            │
│   ✅     ❌     ⏳     ⏳                │
│          ✅ (Edit 完成后)               │
└────────────────────────────────────────┘

规则 4: Bash 错误级联
┌────────────────────────────────────────┐
│ [Bash: cmd1] [Bash: cmd2] [Read]       │
│      ❌        ⏳→❌      ✅ (继续)      │
│ (cmd1 失败，cmd2 被取消)                │
└────────────────────────────────────────┘
```

### 6.4 Tool 生命周期钩子

```typescript
// 执行前钩子
await runPreToolUseHooks({
  tool,
  input,
  context,
  toolUseID,
  // ...
})

// 执行后钩子
await runPostToolUseHooks({
  tool,
  input,
  result,
  context,
  // ...
})

// 失败时钩子
await runPostToolUseFailureHooks({
  tool,
  input,
  error,
  context,
  // ...
})
```

---

## 七、关键设计决策

### 7.1 为什么区分 Tool 和 Skill？

| 维度 | Tool | Skill |
|------|------|-------|
| **抽象层级** | 底层原子操作 | 高层复合工作流 |
| **执行方式** | 直接执行 | 展开为提示词 |
| **上下文** | 当前对话 | 可 fork 独立 Agent |
| **权限** | 细粒度控制 | 整体允许/拒绝 |
| **示例** | Read, Edit, Bash | commit, review-pr, verify |

### 7.2 Deferred Tool 的意义

**问题**: MCP Server 可能有数十个工具，全部放入 prompt 会导致：
- Token 消耗过大
- 模型注意力分散
- 首次调用延迟增加

**解决方案**: Deferred Tool
```
1. 初始只加载 alwaysLoad=true 的工具（核心 10-15 个）
2. 模型需要时调用 ToolSearch 发现
3. 发现的工具才加入 prompt
4. 实现"按需加载"
```

### 7.3 Skill 的 Fork vs Inline 选择

| 模式 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **Inline** | 简单提示词注入 | 快速、共享上下文 | 污染主对话 |
| **Fork** | 复杂多步骤任务 | 隔离、独立预算、可中断 | 需要等待 |

### 7.4 权限系统的多层设计

```
Layer 1: 规则匹配 (Deny → Allow → Ask)
Layer 2: PreToolUse Hooks
Layer 3: 自动分类器 (BashClassifier)
Layer 4: 用户确认对话框
```

### 7.5 MCP 工具命名规范

```
mcp__{normalized_server_name}__{normalized_tool_name}

示例:
- "claude.ai Slack" + "send_message" → mcp__claude_ai_slack__send_message
- "GitHub" + "create_pull_request" → mcp__github__create_pull_request
```

---

## 附录：关键文件索引

| 文件 | 职责 |
|------|------|
| `Tool.ts` | Tool 类型定义、buildTool 工厂 |
| `tools.ts` | 内置工具注册表、getTools() |
| `tools/ToolSearchTool/ToolSearchTool.ts` | 动态工具发现 |
| `tools/SkillTool/SkillTool.ts` | Skill 执行 |
| `skills/loadSkillsDir.ts` | Skill 加载器 |
| `skills/bundled/index.ts` | 内置 Skills 注册 |
| `services/tools/toolExecution.ts` | Tool 执行核心 |
| `services/tools/StreamingToolExecutor.ts` | 流式并发执行器 |
| `services/mcp/client.ts` | MCP 客户端 |
| `utils/toolSearch.ts` | Tool 搜索工具函数 |

---

*报告完成时间: 2026年1月*
