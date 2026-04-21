# Claude Code Memory 模块架构设计

> 基于 Claude Code CLI 源代码的深度分析（`src/memdir/`、`src/services/SessionMemory/`、`src/services/extractMemories/`、`src/services/teamMemorySync/`、`src/services/autoDream/`、`src/tools/AgentTool/agentMemory.ts` 等核心模块）

---

## 1. 架构总览

Claude Code 的 Memory 系统是一个**多层、多模态、文件驱动**的持久化记忆架构。它的核心设计哲学是：

- **文件即数据库**：所有记忆都以 Markdown 文件形式存储在磁盘上，前端使用 Git 风格的索引（`MEMORY.md`）+ 主题文件（`*.md`）组织
- **分层隔离**：从个人到团队、从项目到会话，每一层都有明确的边界和作用域
- **后台自治**：记忆提取、整合、同步大量依赖 Forked Agent（子代理）在后台静默完成，不阻塞主对话流
- **安全第一**：团队同步有完整的路径遍历防护、符号链接逃逸检测、密钥泄露扫描

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Memory 系统全景图                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  用户可见层                                                               │
│  ├─ /memory 命令 (MemoryFileSelector.tsx) → 编辑 CLAUDE.md / 记忆文件      │
│  ├─ MemoryUpdateNotification.tsx → 记忆更新提示                           │
│  └─ MemoryUsageIndicator.tsx → 进程内存监控（仅 ant 内部构建）              │
├─────────────────────────────────────────────────────────────────────────┤
│  指令文件层 (User-Managed)                                                │
│  ├─ Managed memory   /etc/claude-code/CLAUDE.md                          │
│  ├─ User memory      ~/.claude/CLAUDE.md                                 │
│  ├─ Project memory   ./CLAUDE.md, .claude/CLAUDE.md, .claude/rules/*.md  │
│  └─ Local memory     ./CLAUDE.local.md                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  自动记忆层 (Auto-Managed)                                                │
│  ├─ Auto Memory      ~/.claude/projects/<repo>/memory/                   │
│  │   ├─ MEMORY.md (索引)                                                  │
│  │   ├─ *.md (主题记忆文件，带 frontmatter)                                │
│  │   └─ logs/YYYY/MM/YYYY-MM-DD.md (KAIROS 模式下仅追加的每日日志)         │
│  ├─ Team Memory      ~/.claude/projects/<repo>/memory/team/              │
│  │   └─ 通过 OAuth 与 anthropic 服务器双向同步 (pull/push)                  │
│  ├─ Agent Memory     ~/.claude/agent-memory/<agent>/                     │
│  │   └─ 或 .claude/agent-memory/<agent>/ (project scope)                  │
│  └─ Session Memory   ~/.claude/session-memory/<session>.md               │
│      └─ 用于 context compaction 的会话摘要                                │
├─────────────────────────────────────────────────────────────────────────┤
│  后台服务层                                                               │
│  ├─ extractMemories.ts    → 对话结束后自动提取耐久记忆                      │
│  ├─ sessionMemory.ts      → 实时维护会话笔记                               │
│  ├─ autoDream.ts          → 定期整合记忆（/dream 技能）                     │
│  └─ teamMemorySync/       → 团队记忆文件监视与服务器同步                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心子系统详解

### 2.1 Auto Memory（自动记忆 / Memdir）

**路径**：`src/memdir/`  
**存储位置**：`~/.claude/projects/<sanitized-git-root>/memory/`  
**入口文件**：`MEMORY.md`

#### 2.1.1 四类型分类学（Four-Type Taxonomy）

所有自动记忆被严格约束为四种类型，任何可从代码、Git 历史或文件结构中推导出的信息**不得**存入记忆：

| 类型 | 作用域 | 说明 | 保存时机 |
|------|--------|------|----------|
| `user` | always private | 用户角色、目标、偏好、知识背景 | 得知用户任何角色/偏好信息时 |
| `feedback` | default private, team when project-wide | 用户对 assistant 工作方式的指正与确认 | 用户纠正（"不要那样做"）或确认（"没错，继续保持"）时 |
| `project` | bias toward team | 项目内正在进行的工作、目标、缺陷、事件 | 得知谁在做什么、为什么做、截止时间时 |
| `reference` | usually team | 指向外部系统的指针（Linear 项目、Grafana 面板、Slack 频道） | 得知外部资源及其用途时 |

#### 2.1.2 文件格式与索引机制

每条记忆是一个独立的 `.md` 文件，使用 YAML frontmatter：

```markdown
---
name: 用户角色
description: 用户是数据科学家，关注可观测性
type: user
---

用户目前专注于日志和可观测性基础设施的调研。
```

`MEMORY.md` 是一个**纯索引**，不包含记忆正文：

```markdown
- [用户角色](user_role.md) — 数据科学家，关注可观测性
- [测试策略](feedback_testing.md) — 集成测试必须连接真实数据库
```

**截断保护**：`MEMORY.md` 有硬性的 200 行 / 25KB 上限，超限后会截断并附加警告，促使模型保持索引精简。

#### 2.1.3 后台提取（extractMemories）

**源码**：`src/services/extractMemories/extractMemories.ts`

- **触发时机**：每次主查询循环结束（模型产出最终回复且无 tool calls）时，通过 `stopHooks.ts` 中的 `handleStopHooks` 触发
- **执行方式**：使用 `runForkedAgent` 创建一个**完美分叉**的子代理，共享父对话的 prompt cache
- **互斥机制**：如果主代理在本轮已经写入过记忆文件（通过 `hasMemoryWritesSince` 检测），后台提取自动跳过，避免重复工作
- **节流机制**：每 N 轮（默认 1，可通过 GrowthBook 配置 `tengu_bramble_lintel` 调节）才执行一次提取
- **工具限制**：子代理只能使用 `Read`、`Grep`、`Glob`、只读 `Bash`、`Edit`/`Write`（且仅限 memory 目录内）
- **预注入清单**：提取前通过 `scanMemoryFiles` 扫描已有记忆 frontmatter，生成清单注入提示，避免子代理浪费一轮执行 `ls`

#### 2.1.4 KAIROS 模式（Assistant Daily Log）

当 `feature('KAIROS')` 激活且处于 assistant 模式时，记忆写入方式变为：

- **写入目标**：`<autoMemPath>/logs/YYYY/MM/YYYY-MM-DD.md`
- **写入方式**：append-only，每条记录是一个带时间戳的 bullet
- **整合时机**：夜间由 `/dream` 技能（autoDream）将日志蒸馏为 `MEMORY.md` + 主题文件
- **动机**：assistant 会话几乎是永久性的，append-only 日志避免了持续重写索引的开销

---

### 2.2 Team Memory（团队记忆）

**路径**：`src/services/teamMemorySync/`, `src/memdir/teamMemPaths.ts`  
**存储位置**：`<autoMemPath>/team/`  
**依赖**：`feature('TEAMMEM')` 编译标志 + `tengu_herring_clock` GrowthBook 开关 + OAuth 认证

#### 2.2.1 双目录架构

当 team memory 启用时，系统会同时加载两个目录：

- **Private**：`~/.claude/projects/<repo>/memory/`（个人记忆）
- **Team**：`~/.claude/projects/<repo>/memory/team/`（团队共享记忆）

系统提示中会包含两个 `MEMORY.md` 索引，并附带 `<scope>` 标签指导模型选择正确的目录。

#### 2.2.2 服务器同步协议

**API 端点**：`GET/PUT /api/claude_code/team_memory?repo={owner/repo}`

| 操作 | 语义 | 关键机制 |
|------|------|----------|
| **Pull** | 服务器覆盖本地 | 使用 `If-None-Match` + ETag 实现 304 缓存；404 表示尚无数据 |
| **Push** | 本地差异上传 | Delta upload（仅上传内容哈希与服务器 `entryChecksums` 不同的文件） |
| **Conflict** | 乐观锁 | `If-Match` ETag，412 时通过 `GET ?view=hashes` 刷新 serverChecksums 后重试 |

**批量控制**：
- 单文件上限：250KB（`MAX_FILE_SIZE_BYTES`）
- 单 PUT body 上限：200KB（`MAX_PUT_BODY_BYTES`），超限自动分片为多个 PUT
- 服务器条目上限：从结构化 413 响应中学习 `max_entries`，按字母序截断本地文件

#### 2.2.3 文件监视与 Debounced Push

**源码**：`src/services/teamMemorySync/watcher.ts`

- 使用 `fs.watch({ recursive: true })` 监听 `team/` 目录
- **Debounced**：写操作发生后等待 2 秒无新变更才触发 push，避免频繁写入导致过多请求
- **永久失败抑制**：对于 `no_oauth`、`no_repo`、4xx（除 409/429 外）等不可恢复错误，会永久抑制重试，直到文件删除（unlink）或会话重启
- **启动流程**：会话启动时先执行 initial pull，再启动 watcher；即使服务器为空也启动 watcher，避免新仓库的写入死区

#### 2.2.4 安全设计

**源码**：`src/memdir/teamMemPaths.ts`

团队记忆的写路径通过多层防护阻止目录遍历和符号链接逃逸：

1. **字符串级校验**：`resolve()` 消除 `..` 段后检查前缀是否在 `teamDir` 内
2. **符号链接解析**：`realpathDeepestExisting()` 对最深存在的祖先调用 `realpath()`，沿目录树向上遍历，检测 dangling symlink 和 symlink loop
3. **路径键消毒**：`sanitizePathKey()` 拒绝 null byte、URL-encoded traversal (`%2e%2e%2f`)、Unicode normalization attack（全角 `．．／`）、反斜杠、绝对路径

**密钥扫描**：`src/services/teamMemorySync/secretScanner.ts` 使用 gitleaks 规则在 push 前扫描文件内容，发现密钥则跳过上传并记录规则 ID（不记录值）。

---

### 2.3 Session Memory（会话记忆）

**路径**：`src/services/SessionMemory/`  
**存储位置**：`~/.claude/session-memory/<session-id>.md`

#### 2.3.1 核心目的

Session Memory 解决的是**长对话上下文压缩（compaction）**问题。传统 compaction 需要调用 LLM API 生成摘要，而 Session Memory 使用一个持续维护的本地笔记文件，在 compaction 时直接替代 API 调用，大幅降低 token 消耗和延迟。

#### 2.3.2 结构化模板

默认模板包含 9 个固定章节（`src/services/SessionMemory/prompts.ts`）：

```markdown
# Session Title
# Current State
# Task specification
# Files and Functions
# Workflow
# Errors & Corrections
# Codebase and System Documentation
# Learnings
# Key results
# Worklog
```

每个章节都有斜体描述行作为模板指令，子代理更新时**只能修改内容，不能修改章节标题和描述行**。

#### 2.3.3 触发策略

**源码**：`src/services/SessionMemory/sessionMemory.ts`

阈值三选二（必须满足 token 阈值）：

| 阈值 | 默认值 | 说明 |
|------|--------|------|
| `minimumMessageTokensToInit` | 10,000 | 首次触发 session memory 所需的总上下文 token 数 |
| `minimumTokensBetweenUpdate` | 5,000 | 自上次提取后上下文增长的 token 数 |
| `toolCallsBetweenUpdates` | 3 | 自上次提取后的 tool call 次数 |

触发公式：
```
shouldExtract = (tokenThreshold && toolCallThreshold) || (tokenThreshold && !hasToolCallsInLastTurn)
```

#### 2.3.4 Forked Agent 提取

- 通过 `registerPostSamplingHook` 注册为后采样钩子
- 使用 `runForkedAgent` 执行，权限极度收敛：只允许对**唯一的 session memory 文件**执行 `Edit`
- 使用 `sequential()` 包装确保同一时刻只有一个提取任务运行
- 支持手动触发：`/summary` 命令调用 `manuallyExtractSessionMemory`

#### 2.3.5 与 Compaction 的集成

**源码**：`src/services/compact/sessionMemoryCompact.ts`

当上下文过长触发 auto-compact 时：

1. 等待任何进行中的 session memory 提取完成（15s 超时）
2. 读取 session memory 文件内容
3. 如果内容为空或仅匹配模板，回退到传统 compaction
4. 计算 `lastSummarizedMessageId` 之后的消息保留范围
5. 保留消息需满足：至少 `minTokens`（默认 10k）、至少 `minTextBlockMessages`（默认 5 条）
6. 使用 session memory 作为 compact summary 的内容，替代 LLM API 调用
7. 生成 `CompactBoundaryMessage` 标记压缩边界

**关键保护**：`adjustIndexToPreserveAPIInvariants()` 确保不会切割 `tool_use`/`tool_result` 对，也不会丢失与保留消息共享 `message.id` 的 thinking 块。

---

### 2.4 Agent Memory（代理记忆）

**路径**：`src/tools/AgentTool/agentMemory.ts`

为子代理（Agent Tool）提供持久化记忆，支持三种作用域：

| 作用域 | 存储路径 | 说明 |
|--------|----------|------|
| `user` | `~/.claude/agent-memory/<agent>/` | 跨项目共享的用户级记忆 |
| `project` | `<cwd>/.claude/agent-memory/<agent>/` | 项目级记忆，可通过 VCS 共享 |
| `local` | `<cwd>/.claude/agent-memory-local/<agent>/` | 本地非版本控制记忆 |

加载方式与 Auto Memory 相同（`buildMemoryPrompt` + `MEMORY.md`），但提示词中会附加作用域说明（如 "Since this memory is user-scope..."）。

---

### 2.5 CLAUDE.md / 指令文件系统

**路径**：`src/utils/claudemd.ts`

这是用户**主动管理**的记忆层，与自动记忆形成互补：

**加载优先级**（后加载的覆盖先加载的）：

1. **Managed memory** — `/etc/claude-code/CLAUDE.md`（企业统一部署）
2. **User memory** — `~/.claude/CLAUDE.md`（用户全局）
3. **Project memory** — 从 CWD 向上遍历，发现 `CLAUDE.md`、`.claude/CLAUDE.md`、`.claude/rules/*.md`
4. **Local memory** — `./CLAUDE.local.md`（个人项目级，不提交到 VCS）

**@include 指令**：
- 语法：`@path`, `@./relative`, `@~/home`, `@/absolute`
- 仅在叶文本节点生效（代码块内不解析）
- 被 include 的文件作为独立条目插入到包含文件之前
- 防止循环引用

**记忆类型标注**：`src/utils/memory/types.ts` 定义了 `User`、`Project`、`Local`、`Managed`、`AutoMem`、`TeamMem` 等类型，用于 UI 分类和遥测。

---

### 2.6 AutoDream（记忆整合 /dream）

**路径**：`src/services/autoDream/`

AutoDream 是记忆的**夜间整理服务**，核心职责是将 append-only 的日志或分散的记忆整合为结构化的主题文件。

**触发条件**（三阶门控， cheapest first）：
1. **时间门**：距离上次整合 >= `minHours`（默认 24h）
2. **会话门**：自上次整合以来产生的新会话 transcript 数量 >= `minSessions`（默认 5）
3. **锁门**：无其他进程正在执行整合（通过文件锁实现）

**扫描节流**：时间门通过后若会话门未过，每 10 分钟才扫描一次 transcript 目录，避免持续触发。

**执行方式**：同样使用 `runForkedAgent`，提示词由 `consolidationPrompt.ts` 构建，权限与 `extractMemories` 相同（只读工具 + memory 目录写权限）。

---

## 3. 记忆召回（Recall）

### 3.1 系统提示注入

**源码**：`src/memdir/memdir.ts` → `loadMemoryPrompt()`

记忆通过以下方式注入模型上下文：

1. **行为指令**：`buildMemoryLines()` 生成记忆类型学、保存规则、何时访问、信任规则等结构化指导
2. **索引内容**：`MEMORY.md` 的内容作为 `## MEMORY.md` 章节追加到系统提示
3. ** freshness 提示**：超过 1 天的记忆会附加 `memoryFreshnessText`，提醒模型验证时效性

当同时启用 auto + team memory 时，使用 `teamMemPrompts.ts` 中的 `buildCombinedMemoryPrompt()` 生成联合提示。

### 3.2 相关性检索

**源码**：`src/memdir/findRelevantMemories.ts`

对于超出系统提示 token 预算的大量记忆文件，Claude Code 采用**双层召回**：

1. **扫描层**：`scanMemoryFiles()` 递归读取 memory 目录下所有 `.md` 文件（排除 `MEMORY.md`），解析 frontmatter，按 `mtimeMs` 降序排列，上限 200 个文件
2. **选择层**：通过 `sideQuery` 调用 Sonnet 模型，传入用户查询 + 记忆清单（文件名 + description + type + 时间戳），让模型选择最多 5 个最相关的记忆文件

**去重优化**：`alreadySurfaced` 集合过滤掉已在之前轮次展示过的记忆，让选择器将预算花在新鲜候选上。

**工具使用降噪**：如果用户正在 actively 使用某个 MCP 工具，选择器会跳过该工具的参考文档类记忆（避免噪音），但保留警告/已知问题类记忆。

### 3.3 搜索历史上下文

当 GrowthBook 标志 `tengu_coral_fern` 开启时，系统提示会追加 `## Searching past context` 章节，指导模型：
1. 用 `grep` 搜索 memory 目录
2. 用 `grep` 搜索 session transcript（`.jsonl`）作为最后手段

---

## 4. 关键设计模式

### 4.1 Forked Agent 模式

所有后台记忆操作（extractMemories、sessionMemory、autoDream）都使用 `runForkedAgent`：

- **完美分叉**：子代理与主对话共享相同的 system prompt、user context、tool context，因此 prompt cache 命中率高
- **状态隔离**：通过 `createSubagentContext()` 创建独立的 `readFileState`，避免污染父代理的文件缓存
- **权限收敛**：通过 `canUseTool` 回调严格限制子代理可操作的工具和路径范围

### 4.2 闭包状态管理

`extractMemories` 和 `autoDream` 使用**闭包内可变状态**而非模块级全局变量：

```typescript
export function initExtractMemories(): void {
  let lastMemoryMessageUuid: string | undefined
  let inProgress = false
  let pendingContext: ...
  // ... 所有状态封装在闭包内
}
```

这使得测试可以在 `beforeEach` 中调用 `initExtractMemories()` 获得一个全新的状态沙盒。

### 4.3 Feature Flag 与 Dead Code Elimination

大量使用 `bun:bundle` 的 `feature()` 函数进行编译时条件消除：

```typescript
const teamMemPaths = feature('TEAMMEM')
  ? require('./teamMemPaths.js')
  : null
```

未启用的功能在构建时被完全剥离，减小 bundle 体积。

### 4.4 遥测驱动优化

几乎每个记忆操作都有对应的 telemetry 事件：

| 事件名 | 说明 |
|--------|------|
| `tengu_memdir_loaded` | memory 目录加载统计 |
| `tengu_extract_memories_extraction` | 后台提取结果与 token 使用 |
| `tengu_session_memory_extraction` | 会话记忆提取 |
| `tengu_team_mem_sync_started` | 团队同步启动 |
| `tengu_team_mem_push_suppressed` | push 永久失败抑制 |
| `tengu_sm_compact_*` | 基于 session memory 的 compaction 各阶段 |

---

## 5. 安全与权限

### 5.1 文件系统权限

- Auto memory 目录通过 `ensureMemoryDirExists()` 在加载提示时静默创建
- Session memory 文件创建时设置 `mode: 0o600`，目录 `mode: 0o700`
- Team memory 的写操作必须通过 `validateTeamMemWritePath()` / `validateTeamMemKey()` 双重校验

### 5.2 路径覆盖安全

`getAutoMemPath()` 支持两种覆盖方式，安全策略不同：

| 覆盖来源 | 安全处理 |
|----------|----------|
| `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`（env） | 不展开 `~`，不给予 write carve-out（因为由 SDK 程序化设置） |
| `autoMemoryDirectory`（settings.json） | 展开 `~/`，但**排除 projectSettings**（防止恶意仓库通过提交 `.claude/settings.json` 获取敏感目录写权限） |

### 5.3 记忆漂移防护

系统提示中包含强制的 `TRUSTING_RECALL_SECTION`：

> "A memory that names a specific function, file, or flag is a claim that it existed *when the memory was written*. It may have been renamed, removed, or never merged."

模型被要求：
- 引用文件路径前，先验证文件存在
- 引用函数或 flag 前，先 grep 确认
- 用户即将基于记忆采取行动前，再次验证

---

## 6. 扩展点与自定义

### 6.1 自定义 Session Memory 模板

用户可放置文件：
- `~/.claude/session-memory/config/template.md` → 替换默认 9 节模板
- `~/.claude/session-memory/config/prompt.md` → 替换默认的更新提示词（支持 `{{currentNotes}}`、`{{notesPath}}` 变量替换）

### 6.2 禁用记忆

多层级关闭：
1. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`（环境变量，最高优先级）
2. `CLAUDE_CODE_SIMPLE=1`（`--bare` 模式，完全禁用）
3. `settings.json` 中设置 `"autoMemoryEnabled": false`（项目级 opt-out）

### 6.3 Cowork 扩展

通过 `CLAUDE_COWORK_MEMORY_EXTRA_GUIDELINES` 环境变量可向所有记忆提示追加额外指导（如企业合规要求）。

---

## 7. 文件目录索引

| 路径 | 职责 |
|------|------|
| `src/memdir/memoryTypes.ts` | 四类型分类学、提示词文本常量 |
| `src/memdir/memdir.ts` | 提示构建、MEMORY.md 加载与截断、目录确保 |
| `src/memdir/paths.ts` | auto memory 路径解析、启用判断、覆盖处理 |
| `src/memdir/memoryScan.ts` | memory 目录扫描、frontmatter 解析、清单格式化 |
| `src/memdir/memoryAge.ts` | 记忆年龄计算、时效性警告文本 |
| `src/memdir/findRelevantMemories.ts` | 相关性检索（sideQuery → Sonnet 选择） |
| `src/memdir/teamMemPaths.ts` | team memory 路径、遍历/链接逃逸防护 |
| `src/memdir/teamMemPrompts.ts` | 联合（auto+team）提示构建 |
| `src/services/extractMemories/extractMemories.ts` | 后台记忆提取主逻辑 |
| `src/services/extractMemories/prompts.ts` | 提取子代理的提示模板 |
| `src/services/SessionMemory/sessionMemory.ts` | 会话记忆提取钩子 |
| `src/services/SessionMemory/sessionMemoryUtils.ts` | 阈值状态管理、配置、等待 |
| `src/services/SessionMemory/prompts.ts` | 会话记忆模板、更新提示、截断逻辑 |
| `src/services/teamMemorySync/index.ts` | pull/push 同步协议、批量、冲突解决 |
| `src/services/teamMemorySync/watcher.ts` | 文件监视、debounced push、生命周期 |
| `src/services/teamMemorySync/types.ts` | Zod schema、API 类型定义 |
| `src/services/teamMemorySync/secretScanner.ts` | gitleaks 规则密钥扫描 |
| `src/services/autoDream/autoDream.ts` | 夜间记忆整合调度 |
| `src/services/compact/sessionMemoryCompact.ts` | 基于 session memory 的上下文压缩 |
| `src/tools/AgentTool/agentMemory.ts` | 子代理记忆路径与提示加载 |
| `src/utils/claudemd.ts` | CLAUDE.md 发现、@include、层级加载 |
| `src/utils/memoryFileDetection.ts` | 记忆文件路径检测、scope 判断、命令扫描 |
| `src/commands/memory/memory.tsx` | `/memory` 交互命令 |
| `src/components/memory/MemoryFileSelector.tsx` | 记忆文件选择 UI |
| `src/skills/bundled/remember.ts` | `/remember` skill（记忆整理与晋升建议） |

---

## 8. 总结

Claude Code 的 Memory 架构是一个**精心设计的分层持久化系统**：

1. **用户管理层**（CLAUDE.md 家族）提供显式、版本化的指令；
2. **自动记忆层**（Auto/Team/Agent Memory）通过后台 Agent 自治地从对话中提炼知识；
3. **会话记忆层**（Session Memory）用本地文件替代昂贵的 API compaction；
4. **整合层**（AutoDream）周期性地将碎片整理为结构化知识。

其最突出的设计亮点在于：
- **文件驱动**：不依赖外部数据库，利用文件系统本身的语义（mtime、frontmatter、目录层级）
- **后台自治**：Forked Agent 模式让记忆维护零感知、零阻塞
- **安全纵深**：从编译时 DCE、路径遍历防护、符号链接解析、密钥扫描到 OAuth 认证，层层设防
- **Telemetry-first**：每个决策点都有遥测事件，支持数据驱动的持续优化
