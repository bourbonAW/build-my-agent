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
4. **Local recall first**：第一版用文件 + grep 检索 memory files、transcript 和 daily logs；SQLite FTS 是后续性能优化，vector/graph 更靠后。
5. **Scope-aware sharing**：main agent 与 subagent 共享 memory store，但通过 user/project/session/task/agent scope 隔离读写。
6. **Governed writes**：长期 memory 会影响未来行为，因此每条 durable memory 需要来源、状态、可撤销性和审计记录。
7. **Compaction-safe**：compact 前写入 durable notes；compact 后 summary 必须能指回原 transcript 或 memory source。
8. **Minimal operational cost**：Phase 1 只用本地文件 + grep，无数据库、无 daemon、无外部 API key。

## 非目标

- 不直接集成 Mem0、Graphiti、Neo4j、MemPalace 或独立 memory service 作为核心依赖。
- 不在 V1 做自动技能生成、参数化 memory、activation memory 或模型微调。
- 不在 V1 做全自动跨项目共享。跨项目 memory 必须显式配置。
- 不让 LLM extraction 自动写入高优先级行为规则；未经确认的内容只能以 `confidence<1.0` 的 `project` record 写入，不能直接成为 `feedback` 或 `user` 类记录。
- 不把 memory 设计成 MCP-only 能力。MCP 可以作为后续暴露方式，但内核应是 Bourbon runtime 的一部分。

---

## 核心选择

推荐方案是 **File-first + Grep Recall**，后续按需升级。

| 方案 | 结论 | 原因 |
|---|---|---|
| File-first + grep recall（Phase 1） | 推荐 | 零依赖、可审计、人类可读；对 coding agent 的 memory 规模足够 |
| File-first + SQLite FTS index（Phase 2） | 按需升级 | memory 文件增多后的性能优化；对上层接口透明 |
| Memory service + vector/graph backend | 后续可选 | 平台化强，但对 coding agent 第一阶段复杂度过高 |

第一版不追求“永久记住更多”，而是追求“该记的可恢复、可检索、可撤销、不会污染其他作用域”。

---

## 架构总览

```text
Prompt Context (始终注入)
  ├─ AGENTS.md                    # 项目级行为规则，人工维护
  ├─ USER.md                      # 用户偏好，人工或 Bourbon 自动写入
  └─ MEMORY.md                    # memory 文件索引，Bourbon 自动维护

Memory Files (按需召回)
  └─ ~/.bourbon/projects/{project}/memory/
       ├─ MEMORY.md               # 纯索引，≤200 行
       ├─ {kind}_{slug}.md        # 每条 memory 一个文件
       └─ logs/YYYY/MM/DD.md      # daily log，pre-compact flush 写入

Session Runtime
  ├─ append-only transcript JSONL
  ├─ active MessageChain
  ├─ ContextManager microcompact
  └─ pre-compact memory flush → daily log + new memory files

Runtime Governance
  ├─ scope-based write policy (subagent 限制)
  ├─ confidence-based overwrite protection
  ├─ audit (session JSONL，Phase 1)
  └─ sandbox (memory 目录访问限制)
```

---

## Memory Layers

### L0: Prompt Anchors

Prompt anchors 是始终注入或高优先级注入的文本，必须可读、可审查、可手动编辑。

| 文件 | 作用 | 注入策略 | 初始上限 |
|---|---|---|---|
| `AGENTS.md` | 项目级行为规则与开发约束 | 项目已有约定；memory/prompt reader 需要正式支持并作为最高优先级项目指令 | 不新增上限，但显示 token 成本 |
| `MEMORY.md` | 项目级稳定事实、决策、纠错、长期约定 | 始终注入摘要或全文，超过上限时提示整理 | 约 1,200 tokens |
| `USER.md` | 用户稳定偏好、沟通方式、环境约束 | 始终注入摘要或全文；可由用户手动编辑，也可由 Bourbon 在捕获到明确用户偏好时自动写入（如"always reply in Spanish"→ 自动追加到 USER.md） | 约 600 tokens |
| `~/.bourbon/projects/{sanitized-project}/memory/logs/YYYY/MM/YYYY-MM-DD.md` | daily work log、会话决策、低频上下文 | 默认不全量注入，由 recall search 按需召回；最近 1-2 天可摘要注入 | 无硬上限 |

Prompt anchor 集成需要新增 `src/bourbon/prompt/anchors.py`，导出 order=15 的 `memory_anchors` section。该 section 位于 identity 之后、task/error/subagent guidelines 之前，确保项目指令和 confirmed memory 的优先级高于 skills/MCP catalog。

实现时使用命名常量 `MEMORY_ANCHOR_ORDER = 15`，并在测试中验证当前 `PromptBuilder.ALL_SECTIONS` 没有 order 冲突。当前已知顺序是 identity=10、task_guidelines=20、subagent_guidelines=25、error_handling=30、task_adaptability=40、skills=60、mcp_tools=70，因此 15 是刻意选择的插入点，位于 identity 之后、task_guidelines 之前。

`anchors.py` 中的 section factory 必须声明为 `async def`，因为 `PromptSection.content` 的类型签名是 `str | Callable[[PromptContext], Awaitable[str]]`，`PromptBuilder._assemble_sections` 会 `await` 非字符串 content。

优先级规则：

```text
direct user instruction
  > AGENTS.md / system prompt
  > confirmed MEMORY.md / USER.md
  > MemoryRecord (confidence=1.0, source=user)
  > MemoryRecord (confidence<1.0 or source=agent/subagent)
  > session recall snippets
```

### L1: Core Memory Blocks

Core memory blocks 是 prompt 内的 bounded executive summary，不是事实数据库。

建议 block：

| Block | 内容 | 来源 | 写入策略 |
|---|---|---|---|
| `project` | 当前项目目标、阶段、关键路径、架构约束 | `AGENTS.md`、`MEMORY.md`、recent decisions | main agent 或 user 确认后更新 |
| `user` | 用户偏好、工作方式、环境偏好 | `USER.md`、confirmed memory records | 用户确认优先 |
| `agent` | Bourbon 自己的操作习惯、失败规避规则 | confirmed policy memories | 严格限制，避免错误经验固化 |
| `task` | 当前任务状态、下一步、重要中间结论 | `TodoManager`（实时派生，非独立维护） | prompt render 时由 `TodoManager` 生成摘要，不写 SQLite |

```python
class CoreMemoryBlock:
    label: Literal["project", "user", "agent", "task"]
    description: str
    value: str
    token_limit: int
    source_refs: list[SourceRef]
    updated_at: datetime
    updated_by: str
```

Core block 的 `value` 是 bounded summary。完整依据必须通过 `source_refs` 回到 memory record、transcript 或文件。

**持久化与生命周期：**

- `project`、`user`、`agent` block 的内容在 prompt render 时实时从 memory 文件派生：`memory/prompt.py` 扫描对应 kind 的 `active` 文件，截取各文件 description + body 前 N 行，拼成 bounded summary 注入 prompt。没有独立的持久化文件（不需要 `core_blocks.json`）。
- `task` block 不持久化，由 `TodoManager` 在 prompt render 时实时生成摘要，`MemoryManager` 不参与。`MemoryWrite(scope="task")` 在 V1 中**不支持**。
- block 的 token limit 在配置里声明，`memory/prompt.py` 在渲染时严格执行截断。

### L2: Session Recall

Session recall 负责按需召回 episodic memory：

- 过去会话中用户说过什么
- 某个错误如何排查过
- 哪个 subagent 做过什么探索
- 某次 compact 前有哪些关键上下文
- 某个工具调用产生过什么输出

实现方式：

- transcript 仍保存在 `~/.bourbon/sessions/{project}/{session_id}.jsonl`
- Phase 1：直接 grep transcript JSONL 和 daily log 文件召回历史片段；无需额外索引
- Phase 2（后续）：当 transcript 体积增大导致 grep 性能下降时，引入 SQLite FTS 索引加速；对上层接口透明

**Transcript grep 性能约束**：transcript JSONL 增长速度远快于 memory 文件（单个长会话可能产生数 MB JSONL）。Phase 1 的 `MemorySearch` 在搜索 transcript 时应限制搜索范围：
- 默认只搜索最近 10 个 session 的 JSONL 文件
- 可通过 `recall_transcript_session_limit` 配置项调整
- 如果用户通过 `from_date` / `to_date` 指定了时间范围，按时间范围过滤 session 文件（基于文件 mtime 或 metadata.json 中的 created_at）
- 单次 grep 超过 500ms 时在 `MemoryStatus` 中标记 `transcript_search_slow: true`，提示后续可升级到 Phase 2

### L3: Memory File Format

每条 memory 是一个独立的 `.md` 文件，存放在 `~/.bourbon/projects/{sanitized-project}/memory/` 目录下。文件名由 `{kind}_{slug}.md` 组成，slug 从 `name` 字段派生（lowercase + hyphen）。

**文件格式**（YAML frontmatter + Markdown body）：

```markdown
---
id: mem_abc123
name: Reply language preference
description: User requires all responses in Spanish — used as MEMORY.md index line
kind: user
scope: user
confidence: 1.0
source: user
status: active
created_at: 2026-04-20T10:00:00Z
updated_at: 2026-04-20T10:00:00Z
created_by: agent:ses_xyz
---

User explicitly requires all responses to be in Spanish.
Stated: "siempre responde en español" (2026-04-20, session ses_xyz).
```

**Frontmatter 字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | `mem_` + 8位随机字符，全局唯一 |
| `name` | str | 简短标题，用于日志和调试 |
| `description` | str | 单行摘要，直接作为 `MEMORY.md` 索引行 |
| `kind` | enum | `user` / `feedback` / `project` / `reference` |
| `scope` | enum | `user` / `project` / `session` |
| `confidence` | float | 0.0–1.0；`source=user` 时为 1.0，agent 推断时 < 1.0 |
| `source` | enum | `user` / `agent` / `subagent` / `compaction` / `manual` |
| `status` | enum | `active` / `stale` / `rejected`；非 active 不默认召回 |
| `created_at` | ISO 8601 | 创建时间 |
| `updated_at` | ISO 8601 | 最近更新时间 |
| `created_by` | str | `user` / `agent:{session_id}` / `subagent:{run_id}` / `system:flush` |

**Body 内容**：自由 Markdown 文本，无格式要求。`feedback` 类建议以规则为首行，然后 `**Why:**` 和 `**How to apply:**` 两行（与 Claude Code auto-memory 风格一致）。

**MEMORY.md 作为纯索引**（不包含记忆正文，只有指针）：

```markdown
- [Reply language preference](user_reply-language-preference.md) — User requires all responses in Spanish
- [SQLite WAL decision](project_sqlite-wal-decision.md) — Always use WAL mode; prior corruption incident without it
- [No database mocking in tests](feedback_no-db-mock.md) — Integration tests must use real DB; mocks missed prod migration bug
```

MEMORY.md 有硬性 200 行上限，超限时提示整理（与 Claude Code 相同）。索引行格式固定：`- [{name}]({filename}) — {description}`。

**200 行上限执行策略**：当 MEMORY.md 行数达到 200 行时：
- `MemoryWrite` 仍然正常创建 memory 文件，但不再自动追加索引行到 MEMORY.md
- `MemoryStatus` 返回 `index_at_capacity: true`，提示 agent 需要整理
- agent 应在下一次交互中主动告知用户"memory 索引已满，建议整理过期条目"
- 用户可以手动编辑 MEMORY.md 删除不需要的条目，或通过 `MemoryReject` 将旧条目标记为 stale
- 不做自动截断，不做静默丢弃——memory 索引的增删必须可追溯

**设计原则**：

- 信任等级由 `confidence` + `source` 表达，不由 `kind` 表达。`user`-confirmed（`confidence=1.0, source=user`）不能被 agent 自动覆盖。
- subagent 默认只能写 `project`（`scope=session`，`confidence<1.0`）和 `reference`，不能直接写 `user` 或 `feedback`。
- `status=stale/rejected` 的文件保留在磁盘，不被默认召回，但可通过显式过滤查询，便于 audit。
- Body 无长度硬上限；超长 body 由 `files.py` 在注入 prompt 时截断，不改写文件本身。

### L3 Recall Strategy（按需召回）

并非所有 memory 都能常驻 prompt。MEMORY.md 索引始终注入，但各 memory 文件的 body 只在需要时按需读取。

**Phase 1（文件 + grep）**：
- `MemorySearch` 在 Phase 1 使用 `grep`/`ripgrep` 在 memory 目录全文搜索
- 返回匹配文件的文件名、frontmatter 摘要和匹配行上下文
- 与 Claude Code 的"Searching past context"机制相同，无需额外基础设施
- daily log 同样通过 grep 搜索

**Phase 2（索引优化，后续阶段）**：
- 当 memory 文件数量增长导致 grep 性能下降时，引入 SQLite FTS5 索引
- 索引建立在 frontmatter 字段 + body 全文之上
- 对上层接口（`MemorySearch` 工具）完全透明，调用方无感知
- WAL 模式、busy timeout、进程锁等并发控制在此阶段引入

Phase 1 和 Phase 2 的分界点是 memory 文件数量，而不是时间节点。Phase 1 足以支撑数十条 memory 的场景；当单次 grep 延迟超过 200ms 时，切换到 Phase 2。

---

## 存储布局

```text
{workdir}/
  AGENTS.md              # committed project config — human-maintained, can be git-tracked
  USER.md                # optional project-local user override — user-managed, gitignore recommended

~/.bourbon/
  USER.md                # user-global profile
  projects/
    {sanitized-project}/   # sanitized canonical git root, shared across worktrees
      memory/
        MEMORY.md        # bourbon-managed durable memory (auto-written by MemoryPromote)
        logs/
          YYYY/
            MM/
              YYYY-MM-DD.md  # daily work log
  sessions/
    {project_name}/
      {session_id}.jsonl
      {session_id}.metadata.json
      {session_id}.compact.json
```

All Bourbon-managed memory files live under `~/.bourbon/projects/{sanitized-project}/memory/`. The sanitized key is derived from the canonical git root (same repo across worktrees shares one memory store). Only `AGENTS.md` and the optional `{workdir}/USER.md` override remain in the project directory, because they are human-maintained files that users may choose to commit.

**`sanitized-project` key 派生算法**：

1. 获取 canonical git root：运行 `git rev-parse --show-toplevel`，如果不在 git repo 中则使用 `workdir` 的绝对路径。
2. 对 canonical path 做 slugify：将路径中的 `/`、`\`、空格替换为 `-`，移除非 ASCII 字符，转为 lowercase，截断到 64 字符。
3. 追加 path hash 后缀：取 canonical path 的 SHA256 前 8 位 hex，用 `-` 连接到 slug 后面。

示例：`/home/user/projects/bourbon` → `home-user-projects-bourbon-a1b2c3d4`

这确保了：
- 同一 repo 的不同 worktree 共享同一个 memory store（因为 canonical git root 相同）
- 不同路径的项目不会冲突（hash 后缀保证唯一性）
- 目录名人类可读（slug 前缀提供可辨识性）

Rationale for home-directory storage:
- **Privacy**: memory files may contain personal preferences, internal decisions, error history — not suitable for git tracking or team sharing.
- **No accidental commit**: files outside `{workdir}` cannot be picked up by `git add .`.
- **Worktree sharing**: using the canonical git root as the key means all worktrees of the same repo share one memory store, consistent with how Claude Code handles this.

`USER.md` is merged from two locations in V1:

1. `~/.bourbon/USER.md` for stable user-level preferences.
2. `{workdir}/USER.md` for project-local overrides or project-specific preferences.

Merge is deterministic:

1. Parse each file into Markdown sections keyed by normalized heading text: strip leading `#` characters and surrounding whitespace, then lowercase. Content before the first heading is keyed as `__preamble__`. Example: `## Code Style` and `## code style` produce the same key `code style`.
2. Start with user-global sections in file order.
3. Overlay project-local sections by normalized heading key. Matching project-local sections replace the global section; non-matching project-local sections are appended after global-only sections.
4. Render the merged result within `user_md_token_limit`.

This makes "project-local wins" section-level, not line-level or whole-file-level.

**边界情况：纯文本文件（无 heading）**：如果两个文件都没有任何 Markdown heading，所有内容都归入 `__preamble__` key。此时 project-local 的 `__preamble__` 完全替换 global 的 `__preamble__`——即 project-local 文件整体覆盖 global 文件。这是有意的行为：如果用户在项目级写了一个无结构的 `USER.md`，说明他希望完全覆盖全局偏好。实现时应在 `files.py` 的 merge 函数文档中显式记录此行为。

### Concurrent Write Safety（Phase 1）

Phase 1 使用文件系统写入，并发安全策略：

- memory 文件写入采用"写临时文件 + atomic rename"模式，防止并发写导致文件内容损坏
- MEMORY.md 索引更新由 `MemoryManager` 内部的进程锁序列化（同进程多线程 subagent 场景）
- Phase 2 引入 SQLite FTS 时，升级为 WAL 模式 + busy timeout；如 subagent 演变为独立进程，改用文件锁

---

## 工具接口

### `MemorySearch`

按 scope、kind、query 和可选时间范围检索 memory records、daily logs 和 transcript index。

默认查询只返回 `status = "active"` 的 records。`stale` 和 `rejected` 只有在调用方显式传入 status filter 时才返回，避免被推翻的 memory 重新进入上下文。

输入：

```json
{
  "query": "pytest failure sandbox memory",
  "scope": "project",
  "kind": ["project", "feedback"],
  "limit": 8,
  "from_date": "2026-04-01",
  "to_date": "2026-04-20",
  "status": ["active"]
}
```

`from_date` / `to_date` 为 ISO 8601 日期字符串（`YYYY-MM-DD`），均为可选。`status` 默认为 `["active"]`，显式传入时可包含 `stale` / `rejected`。V1 对 `from_date` / `to_date` 的过滤作用于 `MemoryRecord.created_at`；transcript index 和 daily log index 暂不支持时间过滤，该限制在 `MemoryStatus` 中通过 `fts_enabled` 等字段体现。

输出应包含：

- snippet
- `source_ref: SourceRef`
- scope
- kind
- status
- confidence
- why_matched

V1 returns raw snippets and typed source refs only. It does not run an LLM summarizer over search results; summarization belongs to a later consolidation phase.

### `MemoryWrite`

写入候选 memory record。默认不直接修改 `MEMORY.md`。

输入（字段展平，对应 `MemoryRecordDraft` + caller identity）：

```json
{
  "scope": "project",
  "scope_id": "build-my-agent",
  "kind": "project",
  "content": "Always use WAL mode for SQLite stores to allow concurrent reads.",
  "source": "user",
  "source_ref": {
    "kind": "transcript",
    "project_name": "build-my-agent",
    "session_id": "ses_abc123",
    "message_uuid": "msg_xyz789"
  },
  "confidence": 1.0
}
```

`actor` 由运行时从 `ToolContext` 注入，不由调用方在 JSON 中传入。`created_by` 由 `actor_to_created_by()` 在 `MemoryManager.write()` 内部推导。

约束：

- subagent write 根据 agent type 限制 kind/scope
- high-priority kind 需要 promote 才能进入 prompt anchor
- 写入必须触发 audit event

### `MemoryPromote`

把 active memory record 提升到 `MEMORY.md`、`USER.md` 或 core block。

约束：

- `feedback` 和 `user` 类记录 promote 到 prompt anchor 需要 main agent 或用户确认
- promote 必须保留 source_ref
- promote 后原 record 仍保留

`MemoryPromote` must use a deterministic Markdown mutation strategy for `MEMORY.md` and `USER.md`. Bourbon-managed entries live inside a visible managed section with a machine-readable marker comment for parsing:

```markdown
## Bourbon Managed Memory

> This section is managed by Bourbon. Manual edits outside individual record blocks are preserved.
> Records below are maintained automatically — do not remove the `bourbon-memory:` marker lines.

<!-- bourbon-memory:start id="mem_abc123" -->
### Decision: mem_abc123

- status: active
- kind: project
- scope: project
- source: transcript/session_uuid/message_uuid
- created_at: 2026-04-19T12:00:00Z

The promoted memory text goes here.
<!-- bourbon-memory:end id="mem_abc123" -->
```

Rationale: using a `##` section heading ("Bourbon Managed Memory") makes the region visible in all Markdown renderers and editors, including GitHub and VS Code preview. The `<!-- bourbon-memory:... -->` comment lines serve as machine-readable delimiters for precise upsert; they are hidden in rendered output but present in raw text. Users who edit the raw file can see the comment markers and understand the boundary.

Mutation rules:

- If `memory_id` is not present in the managed section, append a new `### {kind_title}: {id}` block inside the section.
- If `memory_id` already exists, replace that block (from its `start` to `end` marker) in place rather than appending a duplicate.
- Replacement updates metadata and body text together.
- Manual user edits **outside** the `<!-- bourbon-memory:start/end -->` blocks (including edits to the `##` heading or the blockquote preamble) are never rewritten by memory tools.
- `MemoryReject` updates `status:` inside the managed block to `rejected` or `stale`; it does not delete the block.
- Tests must cover: manual edit in preamble → not clobbered; duplicate promote → single block; reject after promote → status updated in place.

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

Implemented memory tools are first-class always-loaded tools, not optional deferred tools. Phase 1 loads `MemorySearch`, `MemoryWrite`, and `MemoryStatus`; Phase 2 adds `MemoryPromote` and `MemoryReject` using the same always-loaded policy. If schema overhead becomes measurable, later versions can defer mutation tools behind `ToolSearch`.

Memory tools 遵循现有的 `@register_tool` 装饰器注册模式。`src/bourbon/tools/memory.py` 中的 tool handler 通过装饰器自动注册到全局 `ToolRegistry`，并在 `src/bourbon/tools/__init__.py` 的 `_ensure_imports()` 中添加懒加载导入：

```python
# in _ensure_imports()
from bourbon.tools import memory  # noqa: F401
```

Memory tools 不使用 `suppress(ImportError)` 包裹，因为 memory 是核心运行时能力，不是可选依赖。

### `MemoryManager` Public Interface

Implementation should keep tool handlers thin and route through a stable manager interface:

```python
class MemoryManager:
    def search(self, query: str, *, scope: str, kind: list[str] | None, limit: int) -> list[MemorySearchResult]: ...
    def write(self, record: MemoryRecordDraft, *, actor: MemoryActor) -> MemoryRecord: ...
    def promote(self, memory_id: str, *, target: str, actor: MemoryActor) -> MemoryRecord: ...
    def reject(self, memory_id: str, *, status: str, actor: MemoryActor, reason: str = "") -> MemoryRecord: ...
    def get_status(self, *, actor: MemoryActor) -> MemoryStatus: ...
    def flush_before_compact(self, messages: list[TranscriptMessage], *, session_id: str) -> MemoryFlushResult: ...
```

**`MemoryActor` 类型定义**（位于 `models.py`）：

```python
@dataclass(frozen=True)
class MemoryActor:
    """Identifies who is performing a memory operation."""
    kind: Literal["user", "agent", "subagent", "system"]
    session_id: str | None = None   # for agent/subagent
    run_id: str | None = None       # for subagent only
    agent_type: str | None = None   # e.g. "explore", "coder", "plan"

def actor_to_created_by(actor: MemoryActor) -> str:
    """Derive created_by string from actor."""
    if actor.kind == "user":
        return "user"
    if actor.kind == "agent":
        return f"agent:{actor.session_id}"
    if actor.kind == "subagent":
        return f"subagent:{actor.run_id}"
    return f"system:{actor.kind}"
```

`MemoryActor` 由 `Agent._make_tool_context()` 构造并注入 `ToolContext`，tool handler 从 `ctx` 中取出传给 `MemoryManager`。subagent 的 `agent_type` 用于 policy 层判断写入权限。

**`MemoryWrite` 幂等性**：如果 agent 因超时重试而两次调用 `MemoryWrite` 写入相同内容，Phase 1 不做自动去重——每次调用都会产生一条独立的 `MemoryRecord`（不同 `id`）。原因是内容相同不代表语义相同（可能来自不同上下文）。如果重复写入成为实际问题，Phase 2 可引入基于 `(kind, scope, content_hash)` 的 24 小时内去重窗口。

---

## 核心流程

### 会话启动

1. `Agent.__init__` 初始化 `MemoryManager`
2. `PromptBuilder` 通过 memory/prompt reader 读取 prompt anchors 和 core blocks
3. `ContextInjector` 继续注入 workdir/date/git status
4. system prompt 中加入 bounded memory section
5. 不默认检索全部历史；只有任务需要时调用 `MemorySearch`

### 普通写入

**Phase 1**（write only）：

1. 用户明确要求记住某事，agent 调用 `MemoryWrite`
2. 新建 memory 文件（frontmatter + body），写入 memory 目录，status = `active`
3. audit 记录 write 事件

**Phase 2**（write + promote）：

4. 如果内容是长期稳定规则，agent 可调用 `MemoryPromote`
5. promote 更新 `MEMORY.md` / `USER.md` / core block，保留 source_ref
6. audit 记录 promote 事件

Phase 1 交付后，记忆以文件形式存储，可通过 `MemorySearch` 按需召回，MEMORY.md 索引始终注入 prompt。prompt anchor 的 Bourbon 自动写入能力（`MemoryPromote` → `MEMORY.md` / `USER.md`）在 Phase 2 才可用。

### Pre-Compact Flush

The pre-compact flush is coordinated by `Agent`, not by `Session`. This avoids introducing a `Session → MemoryManager` dependency that would create a circular import (`memory` already depends on `session` types).

Integration pattern (in `agent.py`):

当前代码中 `session.maybe_compact()` 的调用位于 `_step_impl()` 和 `_step_stream_impl()` 中，在进入 conversation loop 之前（而非 `_run_conversation_loop()` 内部）。因此 flush hook 必须插入到这两个方法中 `self.session.maybe_compact()` 调用之前：

```python
# inside Agent._step_impl() AND Agent._step_stream_impl(),
# before the existing self.session.maybe_compact() call
if self.session.context_manager.should_compact() and self._memory_manager:
    messages_to_flush = self.session.chain.get_compactable_messages()
    self._memory_manager.flush_before_compact(
        messages_to_flush, session_id=self.session.session_id
    )
self.session.maybe_compact()
```

注意：`_step_impl()`（同步路径）和 `_step_stream_impl()`（流式路径，REPL 主入口）都需要插入相同的 flush hook。遗漏流式路径会导致流式模式下的 compaction 事件丢失 memory flush。

`Session.maybe_compact()` remains unaware of memory. `MemoryManager` is initialized in `Agent.__init__` and passed down through `ToolContext` — no new coupling is introduced into the session layer.

Flow:

1. `ContextManager.should_compact()` 接近阈值
2. `Agent` 在 `_step_impl()` / `_step_stream_impl()` 中调用 `session.maybe_compact()` 前先调用 `memory_manager.flush_before_compact()`
3. V1 flush 是确定性/启发式流程，不调用 LLM：
   - 为即将归档的 transcript range 写入 source pointer
   - 索引所有 `is_error=True` 的 `ToolResultBlock`
   - 捕获包含 `remember`、`always`、`never`、`记住`、`以后` 等关键词的用户消息作为 low-confidence candidate
   - 捕获 subagent final result 作为 task-scoped `project` record（`confidence<1.0`）
   - 捕获已存在 task/plan summary 的 source pointer
4. flush 写入 `~/.bourbon/projects/{sanitized-project}/memory/logs/YYYY/MM/YYYY-MM-DD.md` 和 `memory_records`
5. compact summary 中保留 typed `SourceRef`

**Daily log 日期归属**：如果一个 session 跨越午夜，flush 写入的 daily log 使用 session 开始日期（从 `session.metadata.created_at` 获取），而非 flush 执行时的当前日期。这确保同一 session 的所有 flush 写入同一个 daily log 文件，避免跨午夜时日志分裂。

LLM-driven extraction、总结和事实合并不在 V1 的 compact path 中执行。原因是 `Session.maybe_compact()` 发生在 agent step 中途；在这里追加 LLM turn 会增加延迟、失败模式和递归风险。LLM consolidation 延后到 Phase 4 的 background consolidation。

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
   - task-scoped `project` record（`confidence<1.0`）
   - agent diary
   - `reference`（指向产出文件或外部资源）
4. parent 负责将 subagent 写入的低 confidence `project` record promote 成 project memory

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

Phase 1：memory 操作（write、promote、reject、flush）作为普通 audit event 写入现有的 `AuditLogger`（`~/.bourbon/audit/session-{uuid}.jsonl`）。每条事件包含：memory 文件名、operation、kind/scope、actor（user / agent:session_id / subagent:run_id）、timestamp。

跨会话 audit 查询在 Phase 1 通过 grep audit JSONL 实现。Phase 2 引入 SQLite 时，可将 memory audit 迁移到 `audit_log` 表以支持结构化查询。

### Sandbox

sandboxed command 不应默认直接读取 `~/.bourbon/projects/`。如果工具执行需要 memory，应该通过 Bourbon tool API 读取受控 snippet，而不是让 shell/process 读全局 memory 文件。

`{workdir}/AGENTS.md` 和 `{workdir}/USER.md` 作为普通工作区文件，按现有 filesystem policy 处理。`~/.bourbon/projects/{sanitized-project}/memory/` 下的所有文件属于用户私有数据，应通过 access policy 限制 sandbox 访问。

### Subagent Rules

不同 agent type 的默认 memory 权限：

| Agent type | Read | Write | Promote |
|---|---|---|---|
| `explore` | project/task/agent | `project`(task,low-conf), `reference`, agent diary | no |
| `coder` | project/task/agent | `project`(task,low-conf), `reference` | no by default |
| `plan` | project/task/agent | `project`(task,low-conf) | no by default |
| `default` main agent | project/session/task/user | all kinds, all confidence levels | yes, with policy |

---

## 模块设计

新增模块：

```text
src/bourbon/memory/
  __init__.py
  manager.py        # MemoryManager orchestration
  models.py         # MemoryRecord, SourceRef, CoreMemoryBlock, enums
  store.py          # memory 文件读写（atomic rename）、MEMORY.md 索引维护、grep 搜索；Phase 2 在此层加 SQLite FTS
  files.py          # AGENTS.md / MEMORY.md / USER.md / daily log handling
  policy.py         # scope and agent-type checks
  prompt.py         # render bounded memory prompt section
  compact.py        # pre-compact flush helpers

src/bourbon/prompt/anchors.py
  memory_anchors_section  # PromptSection(order=15)

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
| `src/bourbon/prompt/anchors.py` | add order=15 file anchor section for `AGENTS.md`, `MEMORY.md`, `USER.md`, and core blocks; section factory 必须是 `async def` |
| `src/bourbon/prompt/__init__.py` | import anchors section, append to `ALL_SECTIONS`（当前 `ALL_SECTIONS = DEFAULT_SECTIONS + DYNAMIC_SECTIONS`，改为 `DEFAULT_SECTIONS + ANCHOR_SECTIONS + DYNAMIC_SECTIONS`） |
| `src/bourbon/agent.py` | 在 `_step_impl()` 和 `_step_stream_impl()` 中，`self.session.maybe_compact()` 调用之前插入 `memory_manager.flush_before_compact()`；两条路径都需要 |
| `src/bourbon/tools/__init__.py` | add `memory_manager: Any \| None = None` and `memory_actor: Any \| None = None` to `ToolContext`; 在 `_ensure_imports()` 中添加 `from bourbon.tools import memory` |
| `src/bourbon/subagent/manager.py` | pass subagent identity/scope to memory policy |
| `src/bourbon/audit/events.py` | add memory event types (write, promote, reject, flush, search) to existing AuditLogger |
| `src/bourbon/config.py` | add `[memory]` config |

---

## 配置

```toml
[memory]
enabled = true
storage_dir = "~/.bourbon/projects"   # memory lives at {storage_dir}/{sanitized-project}/memory/
auto_flush_on_compact = true
auto_extract = false   # Phase 1: explicit write only; background LLM extraction deferred
recall_limit = 8       # max memory files returned by MemorySearch
recall_transcript_session_limit = 10  # max recent sessions to grep for transcript recall

[memory.prompt]
memory_md_token_limit = 1200
user_md_token_limit = 600
core_block_token_limit = 1200   # per block (project/user/agent combined)

# [memory.recall] — Phase 2 only, not present in Phase 1
# backend = "sqlite_fts"
# fallback_backend = "sqlite_like"
```

`auto_extract = false` 是有意的默认值。Phase 1 只支持显式 write 和 compact-triggered flush；后台 LLM extraction 在 Phase 1 稳定后开启。`[memory.recall]` 整节在 Phase 2 引入 SQLite 时才激活。

---

## 测试策略

### Unit tests

- `MemoryRecord` validation：scope/kind/status/source 合法性
- `SourceRef` validation：transcript/file/tool_call/manual 的必填字段
- `MemoryRecord` content length：超过 10KB 时 truncate 并设置 `content_truncated`
- `MemoryActor` validation：kind/session_id/run_id 的组合合法性
- `actor_to_created_by()` 对各种 actor kind 的正确派生
- memory 文件 CRUD：写入、读取、status 更新（stale/rejected）
- MEMORY.md 索引：新增条目、去重更新、200 行上限时停止追加并设置 `index_at_capacity`
- 文件写入原子性：临时文件 + rename，并发写不损坏文件
- grep 搜索：关键词匹配返回文件名 + frontmatter + 上下文行
- grep fallback：memory 目录不存在时返回空结果而非报错
- transcript grep：限制搜索最近 N 个 session，超过 `recall_transcript_session_limit` 的旧 session 不搜索
- prompt render：token limit、空文件、超长文件截断
- prompt anchor order：`memory_anchors` order=15，位于 identity(10) 之后、task_guidelines(20) 之前
- prompt anchor section factory 是 `async def`，可被 `PromptBuilder._assemble_sections` 正确 await
- file anchors：`MEMORY.md` / `USER.md` 不存在、存在、超限
- `USER.md` merge：section-level 覆盖、纯 preamble 文件整体覆盖、单文件缺失时 fallback
- Markdown promote：managed region append、dedupe、reject/stale status update
- policy：subagent type 对 scope/kind 的读写限制
- `ToolContext` carries `memory_manager` and `memory_actor` into memory tool handlers
- `sanitized-project` key：slug + hash 派生的正确性和跨 worktree 一致性
- daily log 日期归属：跨午夜 session 使用 session 开始日期

### Integration tests

- `Agent` 初始化时 memory section 正确注入
- `MemoryWrite` 后 `MemorySearch` 可召回 source_ref
- `_step_impl()` 和 `_step_stream_impl()` 中 compact 前均触发 deterministic flush，不调用 LLM
- subagent 只能写 task-scoped `project`（low-conf）和 `reference`，不能 promote `feedback` 或 `user` 类记录
- rejected memory 不再被默认 search 注入，但 audit 可见
- memory audit events 在新 session 中仍可查询
- sandboxed command 无法直接读 user-global memory store
- `memory.enabled = false` 时 `MemoryManager` 不初始化，memory tools 不注册，prompt 中无 memory section

### Eval cases

- 跨会话偏好召回：用户明确说偏好后，下一 session 能按需召回
- 错误纠正：错误 memory 被 reject 后不再影响回答
- scoped isolation：项目 A 的 memory 不污染项目 B
- subagent promotion：explore 写入的低 confidence `project` record 只有经 main agent promote 后才进入 prompt anchor
- compaction resilience：compact 后仍能通过 source_ref 找回关键历史

---

## 分阶段路线

### Phase 1: Memory Foundations

- `MemoryRecord`, `SourceRef`, and `MemoryActor` models
- `sanitized-project` key 派生（slug + SHA256 前 8 位）
- memory 文件读写（atomic rename）+ MEMORY.md 索引维护（含 200 行上限 capacity 检测）
- grep-based recall（memory files + transcript JSONL + daily logs）
- transcript grep 限制搜索最近 N 个 session（`recall_transcript_session_limit`）
- process-local write lock for MEMORY.md index updates
- memory audit events via existing AuditLogger (session JSONL)
- project `AGENTS.md` / `MEMORY.md` / `USER.md` reader
- user-global `~/.bourbon/USER.md` merge（含纯 preamble 边界情况）
- prompt anchor section order=15 with token limits（`async def` factory）
- `ToolContext.memory_manager` and `ToolContext.memory_actor`
- `MemorySearch` / `MemoryWrite` / `MemoryStatus`
- memory tools 通过 `@register_tool` 注册，在 `_ensure_imports()` 中懒加载
- deterministic pre-compact flush hook（`_step_impl` 和 `_step_stream_impl` 双路径）
- daily memory log（跨午夜 session 使用 session 开始日期）
- typed source pointer in compact summaries
- `memory.enabled = false` 时的 graceful degradation

### Phase 2: Promotion and Moderation

- `MemoryPromote` / `MemoryReject`
- deterministic Markdown managed region for promoted records
- policy checks for promotion

### Phase 3: Subagent and Governance

- task scope id propagation
- subagent memory write restrictions
- sandbox memory path protection
- richer audit browsing

### Phase 4: Optional Advanced Recall

- vector backend behind `MemoryStore` interface
- temporal fields for time-varying facts
- background consolidation
- memory eval dashboard

---

## Phase 1 Decisions

The following choices are fixed before implementation planning:

1. `USER.md` is merged from user-global `~/.bourbon/USER.md` and project-local `{workdir}/USER.md`; project-local content wins on conflict.
2. `MEMORY.md` and `USER.md` mutation is mediated through `MemoryPromote` for Bourbon-managed entries. Users may manually edit outside the managed region.
3. Compact flush is deterministic in V1 and writes source pointers plus simple candidates. It does not call an LLM.
4. Implemented memory tools are always loaded because memory is core runtime capability. Phase 1 includes search/write/status; Phase 2 adds promote/reject.
5. `MemorySearch` returns raw snippets and typed `SourceRef` values. Search-result summarization is deferred.
6. Memory audit events are written to the existing session AuditLogger (JSONL). Phase 2 may migrate to a SQLite audit_log for structured cross-session queries.
7. All Bourbon-managed memory files (MEMORY.md, daily logs, individual memory .md files) live under `~/.bourbon/projects/{sanitized-project}/memory/`. No SQLite or JSON persistence files in Phase 1. Only `AGENTS.md` and the optional `{workdir}/USER.md` override remain in the project directory.
11. `MemoryRecord.kind` uses four values aligned with Claude Code's taxonomy: `user`, `feedback`, `project`, `reference`. Trust level is expressed via `confidence` (0.0–1.0) and `source`, not via kind. The original `instruction`, `preference`, `fact`, `error`, `observation` kinds are absorbed into this four-type set; `artifact` is absorbed into `reference`.
12. `task` CoreMemoryBlock is not independently maintained by `MemoryManager`. It is derived from `TodoManager` at prompt render time. `MemoryWrite(scope="task")` is not supported in V1. This avoids high-frequency SQLite writes and keeps task state's single source of truth in `TodoManager`.
8. `MemoryRecordDraft` does not carry a `created_by` field. The caller always supplies a `MemoryActor`; `MemoryManager.write()` derives `created_by` via `actor_to_created_by()`. This keeps the derivation rule in one place and prevents callers from supplying inconsistent strings.
9. `SourceRef` enforces field constraints in `__post_init__`: `message_uuid` and `start/end_message_uuid` are mutually exclusive; `start` and `end` must appear together; required fields are checked per `kind`. This makes invalid refs a hard error at construction time rather than a silent data quality issue.
10. Pre-compact flush is coordinated in `Agent._step_impl()` and `Agent._step_stream_impl()`, not in `Session` or `_run_conversation_loop()`. `Agent` calls `memory_manager.flush_before_compact()` before `session.maybe_compact()` in both sync and streaming paths. `Session` remains unaware of memory, avoiding a circular dependency.

---

## Decision

Adopt **File-first + Grep Recall** as Bourbon's Stage B memory design for Phase 1.

This keeps Bourbon aligned with its current architecture:

- transcripts remain the source of recoverable episodic truth
- project files remain the source of high-priority human-reviewable memory
- grep over memory files provides local, zero-dependency recall; SQLite FTS is a Phase 2 optimization when file count grows
- runtime governance uses Bourbon's existing strengths instead of bolting on a black-box memory service

The first implementation plan should build the smallest durable loop:

```text
read prompt anchors
  -> write/search structured memory records
  -> index transcript snippets
  -> flush before compact
  -> audit memory operations
```
