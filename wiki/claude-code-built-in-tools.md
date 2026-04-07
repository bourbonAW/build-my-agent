# Claude Code Built-in Tools 完整清单

> 基于 Claude Code 源码分析整理

---

## 目录

1. [核心文件操作工具](#一核心文件操作工具)
2. [Shell 执行工具](#二shell-执行工具)
3. [搜索与发现工具](#三搜索与发现工具)
4. [Agent 与任务工具](#四agent-与任务工具)
5. [计划模式工具](#五计划模式工具)
6. [Web 工具](#六web-工具)
7. [MCP 相关工具](#七mcp-相关工具)
8. [LSP 代码智能工具](#八lsp-代码智能工具)
9. [消息与通知工具](#九消息与通知工具)
10. [配置与管理工具](#十配置与管理工具)
11. [实验性功能工具](#十一实验性功能工具)

---

## 一、核心文件操作工具

### 1. FileReadTool (`FileRead`)

**功能**：读取文件内容，支持文本、图片、PDF、Jupyter Notebook

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ❌ 否 (alwaysLoad) |

**输入参数**：
```typescript
{
  file_path: string   // 绝对路径
  offset?: number     // 起始行号（大文件分块读取）
  limit?: number      // 读取行数限制
  pages?: string      // PDF页码范围，如 "1-5"
}
```

**特殊功能**：
- 自动检测图片格式 (PNG/JPG/GIF/WebP) 并返回 base64
- PDF 支持分页提取为图片
- Jupyter Notebook 返回结构化 cells
- 支持 `~` 展开和路径规范化
- 读取后缓存文件状态（用于防篡改校验）

---

### 2. FileEditTool (`FileEdit`)

**功能**：基于搜索替换的文件编辑（原子性操作）

| 属性 | 值 |
|------|-----|
| 并发安全 | ❌ 否 |
| 破坏性 | ✅ 是 |
| Deferred | ❌ 否 |

**输入参数**：
```typescript
{
  file_path: string    // 绝对路径
  old_string: string   // 要替换的内容（空字符串=创建新文件）
  new_string: string   // 新内容
  replace_all?: boolean // 是否替换所有匹配
}
```

**安全特性**：
- 必须先读取文件才能编辑（`read-before-write` 保护）
- 检测文件是否在外部被修改（mtime 校验）
- 原子性写入（先写临时文件再重命名）
- 保留原始文件的换行符和编码

---

### 3. FileWriteTool (`FileWrite`)

**功能**：完整覆盖写入文件

| 属性 | 值 |
|------|-----|
| 并发安全 | ❌ 否 |
| 破坏性 | ✅ 是 |
| Deferred | ❌ 否 |

**输入参数**：
```typescript
{
  file_path: string   // 绝对路径
  content: string     // 完整文件内容
}
```

**与 FileEditTool 的区别**：
- FileWrite：完整替换整个文件内容
- FileEdit：局部修改（搜索替换）

---

### 4. NotebookEditTool (`NotebookEdit`)

**功能**：编辑 Jupyter Notebook (.ipynb) 文件

| 属性 | 值 |
|------|-----|
| 并发安全 | ❌ 否 |
| 破坏性 | ✅ 是 |
| Deferred | ✅ 是 |

**输入参数**：
```typescript
{
  notebook_path: string           // 绝对路径
  cell_id?: string                // 单元格 ID
  new_source: string              // 新内容
  cell_type?: 'code' | 'markdown' // 单元格类型
  edit_mode?: 'replace' | 'insert' | 'delete' // 编辑模式
}
```

---

## 二、Shell 执行工具

### 5. BashTool (`Bash`)

**功能**：执行 Bash 命令

| 属性 | 值 |
|------|-----|
| 并发安全 | 条件性（基于命令分析） |
| 破坏性 | 取决于命令 |
| Deferred | ❌ 否 |

**并发安全判断**：
```typescript
// 以下命令被认为是并发安全的：
// - 纯读取命令（cat, ls, grep, find 等）
// - 不修改文件系统的命令
// 串行执行的情况：
// - 写入/修改命令
// - cd 命令（需要顺序执行）
```

**特殊行为**：
- 支持超时控制
- 支持权限自动分类器（读取/写入/破坏性）
- Bash 错误会级联取消同批其他工具
- 支持 REPL 模式（在沙箱 VM 中执行）

---

### 6. PowerShellTool (`PowerShell`)

**功能**：执行 PowerShell 命令（Windows 专用）

| 属性 | 值 |
|------|-----|
| 并发安全 | 条件性 |
| 平台 | Windows only |

---

## 三、搜索与发现工具

### 7. GlobTool (`Glob`)

**功能**：文件模式匹配搜索

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | 有条件（嵌入式环境无此工具） |

**输入参数**：
```typescript
{
  pattern: string     // glob 模式，如 "**/*.ts"
  path?: string       // 搜索目录（默认 cwd）
}
```

**输出**：
```typescript
{
  filenames: string[]  // 匹配的文件路径
  numFiles: number
  durationMs: number
  truncated: boolean   // 是否超过 100 文件限制
}
```

---

### 8. GrepTool (`Grep`)

**功能**：基于 ripgrep 的内容搜索

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | 有条件 |

**输入参数**：
```typescript
{
  pattern: string                      // 正则表达式
  path?: string                        // 搜索路径
  glob?: string                        // 文件过滤模式
  output_mode?: 'content' | 'files_with_matches' | 'count'
  '-B'?: number                        // 匹配前 N 行
  '-A'?: number                        // 匹配后 N 行
  '-C'?: number                        // 上下文 N 行
  '-n'?: boolean                       // 显示行号
  '-i'?: boolean                       // 忽略大小写
  head_limit?: number                  // 结果数量限制
  offset?: number                      // 分页偏移
  multiline?: boolean                  // 多行模式
  type?: string                        // 文件类型 (js, py, rust...)
}
```

---

### 9. ToolSearchTool (`ToolSearch`)

**功能**：发现 deferred tools（动态工具加载）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | N/A（本身是发现工具） |

**搜索语法**：
```typescript
// 关键字搜索
{ query: "slack" }

// 直接选择（多选支持）
{ query: "select:WebSearchTool" }
{ query: "select:ToolA,ToolB,ToolC" }

// 必须包含（+前缀）
{ query: "+github pr" }
```

**评分算法**：
- 名称部分匹配：+10 分
- MCP Server 名称：+12 分
- searchHint 匹配：+4 分
- 描述匹配：+2 分

---

## 四、Agent 与任务工具

### 10. AgentTool (`Agent`)

**功能**：创建并运行子 Agent

| 属性 | 值 |
|------|-----|
| 并发安全 | ❌ 否 |
| Deferred | ❌ 否 |

**输入参数**：
```typescript
{
  agent_type: string        // Agent 类型
  description: string       // 任务描述
  prompt: string           // 完整提示词
}
```

**Agent 类型**：
- `default`：通用任务
- `verification`：验证代理（检查工作质量）
- 自定义 Agent（从 agents/ 目录加载）

---

### 11. SkillTool (`Skill`)

**功能**：执行 Skill（Slash Command）

| 属性 | 值 |
|------|-----|
| 并发安全 | ❌ 否 |
| Deferred | ❌ 否 |

**执行模式**：
```typescript
// Inline 模式（默认）
{ skill: "commit", args: "my changes" }
// 展开 skill 内容为提示词，在当前对话中执行

// Fork 模式（skill 定义 context: fork）
{ skill: "verify" }
// 在独立子 Agent 中执行，隔离预算和上下文
```

**权限规则匹配**：
- 精确匹配：`commit` 匹配 `commit`
- 前缀匹配：`review:*` 匹配 `review-pr`, `review-code` 等

---

### 12. TaskCreateTool / TaskGetTool / TaskListTool / TaskUpdateTool

**功能**：任务管理（Todo V2 系统）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是（除 Update） |
| Deferred | ✅ 是 |
| 启用条件 | `isTodoV2Enabled()` |

**Task 结构**：
```typescript
{
  id: string
  subject: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'cancelled'
  owner?: string
  blocks: string[]       // 阻塞的任务 ID
  blockedBy: string[]    // 被哪些任务阻塞
}
```

---

### 13. TaskStopTool (`TaskStop`)

**功能**：停止后台任务

| 属性 | 值 |
|------|-----|
| 别名 | `KillShell`（向后兼容） |
| 并发安全 | ✅ 是 |

---

### 14. TaskOutputTool

**功能**：获取任务输出

| 属性 | 值 |
|------|-----|
| Deferred | ❌ 否 |

---

## 五、计划模式工具

### 15. EnterPlanModeTool (`EnterPlanMode`)

**功能**：进入计划模式（设计阶段）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ✅ 是 |

**行为**：
- 切换权限模式为 `plan`
- 在计划模式下**禁止**文件写入（只能读取和探索）
- 支持 Interview Phase（询问用户澄清需求）

---

### 16. ExitPlanModeV2Tool (`ExitPlanMode`)

**功能**：退出计划模式，提交计划

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| Deferred | ✅ 是 |
| 需要用户确认 | ✅ 是（非 teammate） |

**输出**：
```typescript
{
  plan: string | null     // 计划内容
  filePath?: string       // 计划文件路径
  hasTaskTool?: boolean   // 是否有 Agent 工具可用
  awaitingLeaderApproval?: boolean  // teammate 等待 leader 审批
}
```

---

### 17. TodoWriteTool (`TodoWrite`)

**功能**：管理 Todo 列表（旧版）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| Deferred | ✅ 是 |
| 启用条件 | `!isTodoV2Enabled()` |

---

## 六、Web 工具

### 18. WebSearchTool (`WebSearch`)

**功能**：网络搜索（使用 Anthropic 的搜索 API）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ✅ 是 |
| 启用条件 | First Party / Vertex (Claude 4+) / Foundry |

**输入参数**：
```typescript
{
  query: string
  allowed_domains?: string[]   // 限定搜索域名
  blocked_domains?: string[]   // 排除域名
}
```

**限制**：
- 最多 8 次搜索（硬编码）
- 返回结果包含标题和 URL

---

### 19. WebFetchTool (`WebFetch`)

**功能**：获取网页内容并提取 Markdown

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ✅ 是 |

**输入参数**：
```typescript
{
  url: string    // 目标 URL
  prompt: string // 处理提示词（如 "提取主要内容"）
}
```

**预批准域名**：
- docs.anthropic.com
- github.com
- npmjs.com
- 等（用于减少权限询问）

---

## 七、MCP 相关工具

### 20. ListMcpResourcesTool (`ListMcpResources`)

**功能**：列出 MCP Server 提供的资源

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ✅ 是 |

---

### 21. ReadMcpResourceTool (`ReadMcpResource`)

**功能**：读取 MCP 资源内容

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ✅ 是 |

---

### 22. MCPTool (动态)

**功能**：调用 MCP Server 提供的工具

| 属性 | 值 |
|------|-----|
| 命名格式 | `mcp__{serverName}__{toolName}` |
| Deferred | 由 MCP Server 元数据决定 |

**示例**：
- `mcp__slack__send_message`
- `mcp__github__create_pull_request`

---

## 八、LSP 代码智能工具

### 23. LSPTool (`LSPTool`)

**功能**：语言服务器协议操作（代码导航、符号查找）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| Deferred | ✅ 是 |
| 启用条件 | LSP Server 已连接 |

**支持的操作**：
```typescript
operation: 
  | 'goToDefinition'      // 跳转到定义
  | 'findReferences'      // 查找引用
  | 'hover'              // 悬停提示
  | 'documentSymbol'     // 文档符号
  | 'workspaceSymbol'    // 工作区符号
  | 'goToImplementation' // 跳转到实现
  | 'prepareCallHierarchy' // 调用层次结构准备
  | 'incomingCalls'      // 查找调用者
  | 'outgoingCalls'      // 查找被调用者
```

**输入参数**：
```typescript
{
  operation: string
  filePath: string
  line: number       // 1-based
  character: number  // 1-based
}
```

---

## 九、消息与通知工具

### 24. BriefTool (`Brief` / `SendUserMessage`)

**功能**：向用户发送消息（助手模式主要输出通道）

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| 只读 | ✅ 是 |
| 启用条件 | `--brief` 或 `defaultView: 'chat'` 或 KAIROS 助手模式 |

**输入参数**：
```typescript
{
  message: string           // 消息内容（支持 Markdown）
  attachments?: string[]    // 附件文件路径
  status: 'normal' | 'proactive'  // proactive = 主动推送
}
```

---

### 25. AskUserQuestionTool (`AskUserQuestion`)

**功能**：向用户提问（多选支持）

| 属性 | 值 |
|------|-----|
| 并发安全 | ❌ 否 |

**使用场景**：
- 需要用户决策时
- 澄清模糊需求
- 选择实现方案

---

## 十、配置与管理工具

### 26. ConfigTool (`Config`)

**功能**：获取/设置 Claude Code 配置

| 属性 | 值 |
|------|-----|
| 并发安全 | ✅ 是 |
| Deferred | ✅ 是 |
| 权限 | 读取自动允许，设置需要确认 |

**支持设置**：
```typescript
// 主题
theme: 'dark' | 'light' | 'system'

// 模型
model: 'claude-opus-4' | 'claude-sonnet-4' | ...

// 权限模式
permissions.defaultMode: 'default' | 'auto' | 'plan'

// 其他
autoUpdateChecks: boolean
remoteControlAtStartup: boolean
voiceEnabled: boolean
```

---

### 27. TungstenTool

**功能**：Anthropic 内部工具（ant-only）

| 属性 | 值 |
|------|-----|
| 启用条件 | `process.env.USER_TYPE === 'ant'` |

---

## 十一、实验性功能工具

### 28. TeamCreateTool / TeamDeleteTool

**功能**：创建/删除 Agent 团队（Swarm 模式）

| 属性 | 值 |
|------|-----|
| 启用条件 | `isAgentSwarmsEnabled()` |

---

### 29. EnterWorktreeTool / ExitWorktreeTool

**功能**：Git Worktree 管理

| 属性 | 值 |
|------|-----|
| 启用条件 | `isWorktreeModeEnabled()` |

---

### 30. CronCreateTool / CronDeleteTool / CronListTool

**功能**：定时任务管理

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('AGENT_TRIGGERS')` |

---

### 31. RemoteTriggerTool

**功能**：远程触发器

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('AGENT_TRIGGERS_REMOTE')` |

---

### 32. SleepTool

**功能**：延迟执行

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('PROACTIVE') \|\| feature('KAIROS')` |

---

### 33. MonitorTool

**功能**：监控功能

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('MONITOR_TOOL')` |

---

### 34. WebBrowserTool

**功能**：浏览器自动化

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('WEB_BROWSER_TOOL')` |

---

### 35. SnipTool

**功能**：历史会话片段管理

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('HISTORY_SNIP')` |

---

### 36. WorkflowTool

**功能**：工作流脚本

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('WORKFLOW_SCRIPTS')` |

---

### 37. REPLTool

**功能**：REPL 模式（在 VM 中执行代码）

| 属性 | 值 |
|------|-----|
| 启用条件 | `process.env.USER_TYPE === 'ant'` |

---

### 38. TerminalCaptureTool

**功能**：终端面板捕获

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('TERMINAL_PANEL')` |

---

### 39. CtxInspectTool

**功能**：上下文检查

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('CONTEXT_COLLAPSE')` |

---

### 40. ListPeersTool

**功能**：列出对等节点

| 属性 | 值 |
|------|-----|
| 启用条件 | `feature('UDS_INBOX')` |

---

## 工具属性汇总表

### 核心工具（Always Load）

| Tool | 并发安全 | 只读 | 破坏性 | 需要权限 |
|------|----------|------|--------|----------|
| FileReadTool | ✅ | ✅ | ❌ | 读取权限 |
| FileEditTool | ❌ | ❌ | ✅ | 写入权限 |
| FileWriteTool | ❌ | ❌ | ✅ | 写入权限 |
| BashTool | 条件 | 条件 | 条件 | 自动分类 |
| GlobTool | ✅ | ✅ | ❌ | 读取权限 |
| GrepTool | ✅ | ✅ | ❌ | 读取权限 |
| AgentTool | ❌ | ❌ | 取决于任务 | 是 |
| SkillTool | ❌ | ❌ | 取决于 Skill | 是 |
| TaskStopTool | ✅ | ❌ | ✅ | 是 |
| TodoWriteTool | ✅ | ❌ | ✅ | 否 |

### Deferred Tools（需 ToolSearch 发现）

| Tool | 类别 | 启用条件 |
|------|------|----------|
| NotebookEditTool | 文件编辑 | 默认 |
| LSPTool | 代码智能 | LSP 已连接 |
| WebSearchTool | Web | 特定 provider |
| WebFetchTool | Web | 默认 |
| EnterPlanModeTool | 计划模式 | 非 channels 模式 |
| ExitPlanModeV2Tool | 计划模式 | 非 channels 模式 |
| TaskCreateTool | 任务 | TodoV2 |
| TaskGetTool | 任务 | TodoV2 |
| TaskListTool | 任务 | TodoV2 |
| TaskUpdateTool | 任务 | TodoV2 |
| ListMcpResourcesTool | MCP | 默认 |
| ReadMcpResourceTool | MCP | 默认 |
| BriefTool | 消息 | `--brief` 或 KAIROS |
| ConfigTool | 配置 | ant-only |

---

## 工具命名规范

### 内置工具
- PascalCase: `FileReadTool`, `BashTool`
- 工具名 = 类名去掉 Tool 后缀: `FileRead`, `Bash`

### MCP 工具
```
mcp__{normalized_server_name}__{normalized_tool_name}

示例：
- "claude.ai Slack" + "send_message" → mcp__claude_ai_slack__send_message
- "GitHub" + "create_pull_request" → mcp__github__create_pull_request
```

### 别名支持
工具可以定义 `aliases` 数组用于向后兼容：
```typescript
{
  name: 'TaskStopTool',
  aliases: ['KillShell']  // 旧名称
}
```

---

*文档更新时间: 2026年1月*
