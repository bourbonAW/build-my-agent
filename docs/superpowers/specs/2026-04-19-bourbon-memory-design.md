# Bourbon Memory Stack 设计

**日期**：2026-04-19
**状态**：Draft
**范围**：为 Bourbon 设计一套从项目自身架构出发的 memory 系统，覆盖 prompt anchors、session recall、结构化 memory records、subagent 共享状态和最小 runtime governance。

---

## 背景

Bourbon 已经具备一组适合承载 memory 的基础设施：

- `Session`：append-only transcript、active message chain、compact manifest
- `ContextManager`：token 估算、microcompact、auto/manual compact 触发
- `PromptBuilder`：静态 prompt section 与动态 skills/MCP section
- `SkillManager`：Agent Skills 兼容的 catalog -> activation progressive disclosure
- `MCPManager`：外部 tool server 注册与运行
- `SubagentManager`：独立 subagent session、agent type、tool filtering
- `access_control` / `sandbox` / `audit`：权限、安全执行和事件记录

因此 Bourbon 的 memory 设计不应该从外部 memory product 出发，也不应该先引入独立 vector/graph 服务。更稳妥的路线是把现有 transcript、project files、prompt context 和 runtime governance 组合成 Bourbon-native memory stack。

两份 deep research 的共同结论是：agent memory 不是简单 RAG，而是分层、可检索、可演化的上下文工程。对 Bourbon 来说，第一阶段最重要的不是追求最先进的 graph memory，而是先把长期会话、项目事实、用户偏好、subagent 结果和 compaction 丢失风险纳入同一套可审计机制。

---

## 设计目标

1. **Transcript-first**：以 Bourbon 已有 append-only transcript 作为可恢复事实底座，不让 LLM 摘要成为唯一来源。
2. **File anchors**：用 `AGENTS.md`、`MEMORY.md`、`USER.md` 和 daily logs 承载高优先级、可人工审查的长期记忆。
3. **Bounded prompt memory**：始终注入的 memory 必须有硬上限，避免 prompt 膨胀。
4. **Local recall first**：第一版用 SQLite + FTS5 检索 transcript、memory records 和 daily logs；vector/graph 是后续可选增强。
5. **Scope-aware sharing**：main agent 与 subagent 共享 memory store，但通过 user/project/session/task/agent scope 隔离读写。
6. **Governed writes**：长期 memory 会影响未来行为，因此每条 durable memory 需要来源、状态、可撤销性和审计记录。
7. **Compaction-safe**：compact 前写入 durable notes；compact 后 summary 必须能指回原 transcript 或 memory source。
8. **Minimal operational cost**：默认本地文件 + SQLite，无额外服务、无 daemon、无外部 API key。

## 非目标

- 不直接集成 Mem0、Graphiti、Neo4j、MemPalace 或独立 memory service 作为核心依赖。
- 不在 V1 做自动技能生成、参数化 memory、activation memory 或模型微调。
- 不在 V1 做全自动跨项目共享。跨项目 memory 必须显式配置。
- 不让 LLM extraction 自动写入高优先级行为规则；未经确认的内容只能进入低优先级 record 或 observation。
- 不把 memory 设计成 MCP-only 能力。MCP 可以作为后续暴露方式，但内核应是 Bourbon runtime 的一部分。

---

## 核心选择

推荐方案是 **Transcript-first + File Anchors + SQLite Recall**。

| 方案 | 结论 | 原因 |
|---|---|---|
| File-only memory | 不足以作为完整方案 | 简单可审计，但历史 session、tool trace、subagent 结果难以按需召回 |
| Transcript-first + file anchors + SQLite recall | 推荐 | 最贴合 Bourbon 当前 session/context/subagent 架构，低依赖、可审计、可测试 |
| Memory service + vector/graph backend | 后续可选 | 平台化强，但第一阶段复杂度和运维成本过高 |

第一版不追求“永久记住更多”，而是追求“该记的可恢复、可检索、可撤销、不会污染其他作用域”。

---

## 架构总览

```text
Prompt Context
  ├─ AGENTS.md
  ├─ MEMORY.md
  ├─ USER.md
  └─ CoreMemoryBlocks
       ├─ project
       ├─ user
       ├─ agent
       └─ task

Session Runtime
  ├─ append-only transcript JSONL
  ├─ active MessageChain
  ├─ ContextManager microcompact
  └─ pre-compact memory flush

Recall Store
  ├─ recall.sqlite
  │    ├─ memory_records
  │    ├─ transcript_index
  │    ├─ daily_log_index
  │    └─ FTS virtual tables
  └─ source pointers back to transcript/files/tool calls

Runtime Governance
  ├─ access_control
  ├─ audit
  ├─ sandbox
  └─ subagent tool/profile rules
```

---

## Memory Layers

### L0: Prompt Anchors

Prompt anchors 是始终注入或高优先级注入的文本，必须可读、可审查、可手动编辑。

| 文件 | 作用 | 注入策略 | 初始上限 |
|---|---|---|---|
| `AGENTS.md` | 项目级行为规则与开发约束 | 项目已有约定；memory/prompt reader 需要正式支持并作为最高优先级项目指令 | 不新增上限，但显示 token 成本 |
| `MEMORY.md` | 项目级稳定事实、决策、纠错、长期约定 | 始终注入摘要或全文，超过上限时提示整理 | 约 1,200 tokens |
| `USER.md` | 用户稳定偏好、沟通方式、环境约束 | 始终注入摘要或全文 | 约 600 tokens |
| `memory/YYYY-MM-DD.md` | daily work log、会话决策、低频上下文 | 默认不全量注入，由 recall search 按需召回；最近 1-2 天可摘要注入 | 无硬上限 |

优先级规则：

```text
direct user instruction
  > AGENTS.md / system prompt
  > confirmed MEMORY.md / USER.md
  > active MemoryRecord
  > session recall snippets
  > inferred or unconfirmed observations
```

### L1: Core Memory Blocks

Core memory blocks 是 prompt 内的 bounded executive summary，不是事实数据库。

建议 block：

| Block | 内容 | 来源 | 写入策略 |
|---|---|---|---|
| `project` | 当前项目目标、阶段、关键路径、架构约束 | `AGENTS.md`、`MEMORY.md`、recent decisions | main agent 或 user 确认后更新 |
| `user` | 用户偏好、工作方式、环境偏好 | `USER.md`、confirmed memory records | 用户确认优先 |
| `agent` | Bourbon 自己的操作习惯、失败规避规则 | confirmed policy memories | 严格限制，避免错误经验固化 |
| `task` | 当前任务状态、下一步、重要中间结论 | active session / tasks | session scoped，不默认跨会话 |

每个 block 应有 label、description、value、token_limit、updated_at、source_refs。

### L2: Session Recall

Session recall 负责按需召回 episodic memory：

- 过去会话中用户说过什么
- 某个错误如何排查过
- 哪个 subagent 做过什么探索
- 某次 compact 前有哪些关键上下文
- 某个工具调用产生过什么输出

实现方式：

- transcript 仍保存在 `~/.bourbon/sessions/{project}/{session_id}.jsonl`
- 新增 `~/.bourbon/memory/{project}/recall.sqlite`
- SQLite 只索引和引用 transcript，不替代 transcript
- FTS5 先支持关键词、文件名、symbol、错误码、命令片段检索

### L3: Structured Memory Records

Structured records 用于稳定但不一定适合放进 prompt anchor 的长期记忆。

```python
class MemoryRecord:
    id: str
    scope: Literal["user", "project", "session", "task", "agent"]
    scope_id: str
    kind: Literal[
        "preference",
        "decision",
        "fact",
        "error",
        "instruction",
        "observation",
        "artifact",
    ]
    content: str
    source: Literal["user", "tool", "agent", "subagent", "compaction", "manual"]
    source_ref: str
    confidence: float
    status: Literal["active", "stale", "rejected"]
    created_by: str
    created_at: datetime
    updated_at: datetime
```

设计原则：

- `instruction` 和会改变未来行为的 `decision` 必须比普通 `observation` 更严格。
- subagent 默认只能写 `observation` 或 `artifact`，不能直接写 project-level `instruction`。
- LLM 自动 extraction 的记录默认 `confidence < 1.0`，且不能自动覆盖 user-confirmed memory。
- `stale` / `rejected` 不物理删除，方便 audit 和调试。

---

## 存储布局

```text
{workdir}/
  AGENTS.md
  MEMORY.md                  # optional, project durable memory
  USER.md                    # optional, project-local user profile override
  memory/
    2026-04-19.md            # daily project memory log

~/.bourbon/
  sessions/
    {project_name}/
      {session_id}.jsonl
      {session_id}.metadata.json
      {session_id}.compact.json

  memory/
    {project_name}/
      recall.sqlite
      core_blocks.json
```

Open question：`USER.md` 是否应优先放在 user-level `~/.bourbon/USER.md`，并允许 project-level override。V1 可以先支持 project-local 和 user-global 两个位置，prompt builder 按优先级合并。

---

## 工具接口

### `MemorySearch`

按 scope、kind、query、time range 检索 memory records、daily logs 和 transcript index。

输入：

```json
{
  "query": "pytest failure sandbox memory",
  "scope": "project",
  "kind": ["decision", "error", "observation"],
  "limit": 8
}
```

输出应包含：

- snippet
- source_ref
- scope
- kind
- status
- confidence
- why_matched

### `MemoryWrite`

写入候选 memory record。默认不直接修改 `MEMORY.md`。

约束：

- subagent write 根据 agent type 限制 kind/scope
- high-priority kind 需要 promote 才能进入 prompt anchor
- 写入必须触发 audit event

### `MemoryPromote`

把 active memory record 提升到 `MEMORY.md`、`USER.md` 或 core block。

约束：

- project-level instruction 需要 main agent 或用户确认
- promote 必须保留 source_ref
- promote 后原 record 仍保留

### `MemoryReject`

将 record 标记为 `rejected` 或 `stale`，不做物理删除。

### `MemoryStatus`

返回当前 memory 配置和 agent 应遵循的协议：

- 当前可读 scopes
- 当前可写 scopes
- prompt anchor token usage
- 最近 memory writes
- compact 是否需要 flush

`MemoryStatus` 的价值不是状态展示，而是让 agent 在运行时知道 memory 边界。

---

## 核心流程

### 会话启动

1. `Agent.__init__` 初始化 `MemoryManager`
2. `PromptBuilder` 通过 memory/prompt reader 读取 prompt anchors 和 core blocks
3. `ContextInjector` 继续注入 workdir/date/git status
4. system prompt 中加入 bounded memory section
5. 不默认检索全部历史；只有任务需要时调用 `MemorySearch`

### 普通写入

1. 用户明确要求记住某事，agent 调用 `MemoryWrite`
2. record 初始写入 SQLite，带 source_ref
3. 如果内容是长期稳定规则，agent 可调用 `MemoryPromote`
4. promote 更新 `MEMORY.md` / `USER.md` / core block
5. audit 记录 write/promote

### Pre-Compact Flush

1. `ContextManager.should_compact()` 接近阈值
2. `Session.maybe_compact()` 在真正 compact 前触发 memory flush
3. flush 从即将归档的 messages 中提取：
   - 用户明确偏好
   - 设计决策
   - 失败轨迹和最终修正
   - subagent 产出的可复用发现
4. flush 写入 daily log 和 memory records
5. compact summary 中保留 source pointers

### Recall Search

1. agent 遇到“之前怎么做过”“这个项目有什么约定”“用户偏好是什么”等问题
2. 调用 `MemorySearch`
3. search 在 FTS index 中检索 transcript/log/records
4. 返回短 snippet 和 source_ref
5. agent 需要细节时再读原 transcript 或文件

### Subagent 共享

1. parent 创建 subagent 时传入 task scope id
2. subagent 可读：
   - project confirmed memory
   - task scope memory
   - 自己 agent scope diary
3. subagent 默认可写：
   - task observation
   - agent diary
   - artifact pointer
4. parent 负责将 subagent observation promote 成 project memory

---

## Runtime Governance

Memory governance 的目的不是做重型合规，而是防止长期记忆绕过 Bourbon 已有运行时边界。

### Access Control

Memory read/write 应复用 capability 思路：

| Operation | Capability |
|---|---|
| read project/session memory | `memory:read` |
| write candidate record | `memory:write` |
| promote to prompt anchor | `memory:promote` |
| reject/stale record | `memory:moderate` |

V1 可以先在 tool handler 内部做 scope checks，后续再纳入 `AccessController` 的统一 policy evaluation。

### Audit

新增 audit event：

- `memory.read`
- `memory.write`
- `memory.promote`
- `memory.reject`
- `memory.flush`
- `memory.search`

事件至少包含：

- memory id
- operation
- scope/kind/status
- actor：main agent、subagent id、user、background flush
- source_ref
- timestamp

### Sandbox

sandboxed command 不应默认直接读取 `~/.bourbon/memory`。如果工具执行需要 memory，应该通过 Bourbon tool API 读取受控 snippet，而不是让 shell/process 读全局 memory 文件。

项目内 `MEMORY.md` 和 `memory/YYYY-MM-DD.md` 作为普通工作区文件，按现有 filesystem policy 处理。

### Subagent Rules

不同 agent type 的默认 memory 权限：

| Agent type | Read | Write | Promote |
|---|---|---|---|
| `explore` | project/task/agent | task observation, agent diary | no |
| `coder` | project/task/agent | task observation, artifact, error | no by default |
| `plan` | project/task/agent | task decision candidate | no by default |
| `default` main agent | project/session/task/user | all candidate kinds | yes, with policy |

---

## 模块设计

新增模块：

```text
src/bourbon/memory/
  __init__.py
  manager.py        # MemoryManager orchestration
  models.py         # MemoryRecord, CoreMemoryBlock, enums
  store.py          # SQLite store + FTS index
  files.py          # AGENTS.md / MEMORY.md / USER.md / daily log handling
  policy.py         # scope and agent-type checks
  prompt.py         # render bounded memory prompt section
  compact.py        # pre-compact flush helpers

src/bourbon/tools/memory.py
  MemorySearch
  MemoryWrite
  MemoryPromote
  MemoryReject
  MemoryStatus
```

修改点：

| File | Change |
|---|---|
| `src/bourbon/agent.py` | initialize `MemoryManager`; pass it into prompt context and tool context |
| `src/bourbon/prompt/types.py` | add optional `memory_manager` |
| `src/bourbon/prompt/dynamic.py` | add bounded memory section and project anchor reader |
| `src/bourbon/session/manager.py` | call pre-compact flush before `chain.compact()` |
| `src/bourbon/tools/__init__.py` | register memory tools |
| `src/bourbon/subagent/manager.py` | pass subagent identity/scope to memory policy |
| `src/bourbon/audit/events.py` | add memory audit event types |
| `src/bourbon/config.py` | add `[memory]` config |

---

## 配置

```toml
[memory]
enabled = true
storage_dir = "~/.bourbon/memory"
project_files = true
auto_flush_on_compact = true
auto_extract = false
recall_limit = 8

[memory.prompt]
memory_md_token_limit = 1200
user_md_token_limit = 600
core_block_token_limit = 1200

[memory.recall]
backend = "sqlite_fts"
index_tool_results = true
index_subagent_results = true
```

`auto_extract = false` 是有意的默认值。V1 应优先支持显式 write、manual promote 和 compact-triggered flush；后台 LLM extraction 可以在 V1 稳定后开启。

---

## 测试策略

### Unit tests

- `MemoryRecord` validation：scope/kind/status/source 合法性
- SQLite store CRUD：write/search/reject/promote metadata
- FTS search：文件名、symbol、错误码、自然语言 query
- prompt render：token limit、空文件、超长文件截断
- file anchors：`MEMORY.md` / `USER.md` 不存在、存在、超限
- policy：subagent type 对 scope/kind 的读写限制

### Integration tests

- `Agent` 初始化时 memory section 正确注入
- `MemoryWrite` 后 `MemorySearch` 可召回 source_ref
- manual compact 或 auto compact 前触发 flush
- subagent 只能写 task observation，不能 promote project instruction
- rejected memory 不再被默认 search 注入，但 audit 可见
- sandboxed command 无法直接读 user-global memory store

### Eval cases

- 跨会话偏好召回：用户明确说偏好后，下一 session 能按需召回
- 错误纠正：错误 memory 被 reject 后不再影响回答
- scoped isolation：项目 A 的 memory 不污染项目 B
- subagent promotion：explore observation 只有经 main agent promote 后才成为 project decision
- compaction resilience：compact 后仍能通过 source_ref 找回关键历史

---

## 分阶段路线

### Phase 1: Memory Foundations

- `MemoryRecord` model
- SQLite store + FTS search
- project `MEMORY.md` / `USER.md` reader
- prompt memory section with token limits
- `MemorySearch` / `MemoryWrite` / `MemoryStatus`
- audit events for read/write/search

### Phase 2: Compaction and Promotion

- pre-compact flush hook
- daily memory log
- `MemoryPromote` / `MemoryReject`
- source pointer in compact summaries
- policy checks for promotion

### Phase 3: Subagent and Governance

- task scope id propagation
- subagent memory write restrictions
- sandbox memory path protection
- user-global memory support
- richer audit browsing

### Phase 4: Optional Advanced Recall

- vector backend behind `MemoryStore` interface
- temporal fields for time-varying facts
- background consolidation
- memory eval dashboard

---

## Open Questions

1. Should `USER.md` be project-local by default, user-global by default, or merged from both?
2. Should `MEMORY.md` updates be direct file edits or mediated through `MemoryPromote` only?
3. Should compact flush be LLM-driven in V1, or start as explicit daily-log/source-pointer capture?
4. Should memory tools be always loaded, or deferred behind `ToolSearch`?
5. Should `MemorySearch` return raw snippets only, or optionally summarize results before returning?

---

## Decision

Adopt **Transcript-first + File Anchors + SQLite Recall** as Bourbon's Stage B memory design.

This keeps Bourbon aligned with its current architecture:

- transcripts remain the source of recoverable episodic truth
- project files remain the source of high-priority human-reviewable memory
- SQLite provides local, cheap recall before introducing vector/graph dependencies
- runtime governance uses Bourbon's existing strengths instead of bolting on a black-box memory service

The first implementation plan should build the smallest durable loop:

```text
read prompt anchors
  -> write/search structured memory records
  -> index transcript snippets
  -> flush before compact
  -> audit memory operations
```
