# Hermes Agent 记忆系统架构分析

> 基于 DeepWiki（deepwiki.com/NousResearch/hermes-agent）、官方文档及第三方技术分析整理（2026-04）。
> 研究目的：理解 Hermes 的记忆设计理念，为 Bourbon 记忆系统提供参考。

---

## 1. 项目概况

**Hermes Agent** 是 Nous Research 开发的自进化 AI Agent 框架，核心特性是：

- **持久记忆**：跨会话保留知识，不随 context 重置丢失
- **自主创技能**：任务完成后自动从经验中提炼可复用 Skill
- **GEPA 自进化**（ICLR 2026 Oral）：用进化算法持续优化自身 Skill/Prompt/工具描述

整体架构三层分离：

```
┌───────────────────────────────────────────────────────┐
│            接入层（Runtime Modes）                      │
│  CLI · Gateway(Telegram/Discord/WhatsApp) ·            │
│  ACP(VSCode/Zed) · Batch(RL轨迹) · Web UI             │
├───────────────────────────────────────────────────────┤
│            AIAgent 对话循环（run_agent.py）              │
│  user input → LLM → handle_function_call → result     │
│  ↑ IterationBudget 防止无限循环                         │
├───────────────────────────────────────────────────────┤
│            记忆 + 学习系统（核心）                       │
│  MEMORY.md · USER.md · SQLite SessionDB · Skills      │
│  Honcho（可选） · HRR（可选）                           │
└───────────────────────────────────────────────────────┘
```

数据根目录：`HERMES_HOME`（默认 `~/.hermes/`）

```
~/.hermes/
├── config.yaml          # 模型与后端配置
├── .env                 # API 密钥
├── SOUL.md              # Agent 人格/身份
├── MEMORY.md            # 持久记忆（2200 字符上限）
├── USER.md              # 用户偏好（1375 字符上限）
├── sessions/            # SQLite 会话数据库
│   └── state.db         # WAL 模式 + FTS5 索引
└── skills/              # Agent 自主创建/管理的技能
    └── <category>/<skill>/SKILL.md
```

---

## 2. 四层记忆架构

Hermes 将记忆切分为四个职责不重叠的层：

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1: System Prompt Memory（常驻注入）                     │
│  MEMORY.md（2200 字符）+ USER.md（1375 字符）                  │
│  会话启动时生成 Frozen Snapshot，整个会话内不变                  │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: Skill Memory（经验结晶）                             │
│  ~/.hermes/skills/ 中的 SKILL.md 文件                         │
│  Agent 完成复杂任务后自动创建，可自主迭代改进                    │
├──────────────────────────────────────────────────────────────┤
│  Layer 3: Session Search（跨会话召回）                         │
│  SQLite state.db + FTS5 全文索引                              │
│  检索结果经 LLM 摘要后注入，不暴露原始历史                       │
├──────────────────────────────────────────────────────────────┤
│  Layer 4: External Extensions（可插拔扩展）                    │
│  Honcho（辩证用户建模）/ HRR（代数记忆）/ RetainDB 等            │
│  通过统一 MemoryProvider 接口接入                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Layer 1：系统提示记忆（Frozen Snapshot Pattern）

### 3.1 文件设计

| 文件 | 字符上限 | 用途 |
|------|---------|------|
| `MEMORY.md` | **2200** | Agent 观察：环境约定、项目信息、已知 workaround、经验教训 |
| `USER.md` | **1375** | 用户偏好和习惯（明确的或推断的） |

使用 `§` 作为 section 分隔符，支持多行条目。

### 3.2 Frozen Snapshot Pattern（冻结快照）

这是 Hermes 记忆系统最重要的工程决策，专为 LLM prefix caching 优化：

```
session 启动
    ↓
加载 MEMORY.md + USER.md
    ↓
生成不可变快照（Frozen Snapshot）
    ↓
注入 system prompt ──────────────────────────┐
    ↓                                         │ system prompt 全程不变
对话轮次 1, 2, 3 ...                           │ → prefix cache 命中率最大化
    ↓                                         │
mid-session memory_write 调用                 │
    ↓                                         │
只写磁盘（加文件锁）+ 不修改 system prompt ───┘
    ↓
session 结束

下次 session 启动时才从磁盘重新加载
```

**核心权衡**：当前会话内的记忆更新不能立即被 agent 感知，但换来了整个会话的 prefix cache 稳定性。

### 3.3 记忆安全扫描

记忆内容进入 system prompt 前，`_scan_memory_content` 做多维度威胁检测：

| 攻击类型 | 示例 |
|---------|------|
| Prompt injection | "ignore previous instructions", "disregard above" |
| 外泄技术 | `curl`/`wget` 带 `$ENV_VAR` 参数 |
| 持久化攻击 | 修改 `authorized_keys`、访问 `.ssh/` |
| 混淆技术 | 零宽度 Unicode 字符 |

这是**必要的安全边界**：一旦 agent 有写记忆的权限，就必须在读取时做安全扫描。

---

## 4. Layer 2：Skill 系统（经验结晶）

### 4.1 存储格式

Skill 存储在 `~/.hermes/skills/<category>/<skill>/` 目录下，遵循 [agentskills.io](https://agentskills.io) 开放标准：

```markdown
---
name: skill-name                    # 最多 64 字符
description: 简短说明               # 最多 1024 字符
platforms: [linux, macos]           # 可选平台限制
required_environment_variables:
  - GITHUB_TOKEN
metadata:
  hermes:
    requires_toolsets: [git]
    fallback_for_toolsets: [github]
---

[Skill 正文内容...]
```

支持 references/、templates/、assets/ 等辅助资源目录，按需加载。

### 4.2 三级渐进式加载（Token 优化）

| 级别 | 工具 | 内容量 |
|------|------|--------|
| 0 | `skills_list()` | 名称 + 截断描述（最小 token） |
| 1 | `skill_view(name)` | 完整 SKILL.md |
| 2 | `skill_view(name, path)` | 特定资源文件 |

系统提示中只注入 Level 0 元数据；详细内容仅在 agent 主动查看时加载。

### 4.3 Agent 自主写 Skill（`skill_manage` 工具）

这是 Hermes 自进化的核心入口：

```
复杂任务完成
    ↓
agent 调用 skill_manage create
    ↓
写入 SKILL.md（记录：采用的方法 + 遇到的边界情况 + 重建的领域知识）
    ↓
下次相似任务 → skills_list 发现 → skill_view 加载 → 跳过重新推理
    ↓
执行中发现不足 → skill_manage patch（精准搜索替换）→ 原地改进
```

四个操作：

| 操作 | 说明 |
|------|------|
| `create` | 新建技能目录 + SKILL.md |
| `edit` | 完整替换 skill 文件内容 |
| `patch` | 精准搜索替换（用于迭代改进） |
| `delete` | 只能删除用户/agent 创建的 skill |

**写保护**：bundle skill（仓库内置的）**不可被 agent 删除**，防止误操作破坏系统基础能力。

### 4.4 Skills Hub 与安全模型

外部 skill 安装必须经过人工触发，agent **不能**自主从外部注册表搜索和安装，保留人类控制权。

安装流程：`Source Router → Quarantine 安全扫描（skills_guard.py）→ 写入 ~/.hermes/skills/`

支持来源：GitHub 仓库（Contents API）、skills.sh 注册表、仓库内置可选 skill。

### 4.5 GEPA 自进化（独立仓库）

GEPA（Genetic-Pareto Evolution of Prompt Architectures）是独立仓库 `NousResearch/hermes-agent-self-evolution`，以流水线方式对 hermes-agent 进行系统性优化：

- 用 DSPy 分析完整执行 trace（错误信息、性能数据、推理链）
- 提出针对性的 Prompt / Skill / 工具描述改进
- 进化算法（多目标 Pareto 优化）筛选最优变体

实测：agent 积累 20+ 自生成 skill 后，重复任务速度提升约 **40%**。

---

## 5. Layer 3：SQLite 会话持久化（跨会话召回）

### 5.1 数据库设计

```
~/.hermes/sessions/state.db
├── WAL 模式（Write-Ahead Logging）
│   → 支持多进程并发读（CLI + Gateway + 后台 agent）
│   → 单写者无阻塞
├── FTS5 虚拟表
│   → 所有对话内容全文索引
│   → 支持关键词跨会话搜索
└── session_id：时间戳生成
    chat_key：确定性 hash，绑定消息来源（LOCAL/TELEGRAM/DISCORD/...）
```

原始 transcript → JSONL 文件（独立于 SQLite）；cron 定义 → 独立磁盘文件。

### 5.2 写冲突解决（多进程环境）

Hermes 不使用 SQLite 默认的 busy handler，而是实现了更精细的 `_execute_write`：

```python
# BEGIN IMMEDIATE 立即尝试获取写锁（不等默认超时）
# 失败时随机抖动 20-150ms 后重试
# 避免多进程同时重试造成的 convoy effect
```

### 5.3 跨会话召回流程

```
session_search_tool(query)
    ↓
FTS5 查询 → 命中消息列表
    ↓
_truncate_around_matches()
    → 以每个命中点为中心截取上下文窗口
    ↓
调用辅助 LLM 做摘要压缩
    ↓
摘要注入当前 context（不是原始历史文本）
```

关键设计：**摘要注入而非原文注入**，控制 token 消耗，同时过滤噪声。

### 5.4 RL 轨迹记录

Batch 模式下，所有 session 消息专门格式化为 JSONL 轨迹数据，用于强化学习训练。这使得 hermes-agent 的 Batch runtime 既是生产执行器，也是 RL 数据收集器。

---

## 6. Layer 4：可插拔记忆 Provider 系统

v0.7.0（2026-04-03）起，记忆变成完全插件化，通过统一 `MemoryProvider` 接口接入。官方支持 7 个 provider：

| Provider | 技术方案 | 适用场景 |
|----------|---------|---------|
| **Honcho** | 辩证多轮推理，建模用户思维方式 | 长期个性化协作 |
| **HRR（Holographic）** | 代数超向量，纯 SQLite，零依赖 | 本地部署，极低延迟 |
| **RetainDB** | vector + BM25 + reranking 混合 | 精确语义检索（付费） |
| **ByteRover** | Markdown 文件，完全透明可读 | 需要人工审查记忆 |
| **Mem0** | 托管向量存储 | 托管服务场景 |
| **Hindsight** | 向量 + 会话历史 | 通用向量检索 |
| **Supermemory** | 托管跨设备同步 | 多设备共享 |

---

## 7. Honcho 辩证用户建模（深度解析）

### 7.1 核心理念

Honcho 存储的不是"用户说了什么"，而是"用户的思维模式"。通过多轮辩证推理持续构建用户表示。

### 7.2 五种存储类型

| 类型 | 工具 | 说明 |
|------|------|------|
| **Peer Card** | `honcho_profile` | 用户关键事实列表 |
| **Context Snapshots** | `honcho_context` | 完整会话摘要 + card + 近期消息 |
| **Semantic Excerpts** | `honcho_search` | 按相关性排序的原始段落 |
| **Persistent Conclusions** | `honcho_conclude` | 可创建/删除的事实断言 |
| **Conversation Turns** | — | 对话消息本身 |

存储按 `workspace_id`（默认 "hermes"）做逻辑隔离。

### 7.3 多轮辩证推理流程

`dialecticDepth` 控制推理深度（1-3）：

```
Pass 0: 初始评估
  冷启动 → 聚焦通用事实
  热启动 → 优先处理本会话上下文

Pass 1: 自我审计
  识别 Pass 0 的盲点
  综合近期会话证据

Pass 2: 矛盾核查
  检查 Pass 0 和 Pass 1 之间的矛盾
  做出裁定，输出一致性结论
```

刷新频率：每 `dialecticCadence`（默认 2 轮）触发一次。

### 7.4 双层上下文注入

```
Base context（按 contextCadence 刷新）:
  会话摘要 + 用户表示 + Peer Card
      ↓
Dialectic supplement（按 dialecticCadence 刷新）:
  LLM 合成的"用户当前状态与需求推断"
      ↓
统一注入 system prompt（hybrid 模式）
```

**预取管道**：会话开始前在后台预热，若第 1 轮前未完成，则降级为同步调用（有超时上限）。

### 7.5 三种 Recall 模式

| 模式 | 自动注入 | Tools 可用 | 适用场景 |
|------|---------|-----------|---------|
| `hybrid` | ✅ | ✅ | 推荐，兼顾自动和手动 |
| `context` | ✅ | ❌ | 只需背景注入，不想暴露工具 |
| `tools` | ❌ | ✅ | Agent 主动按需查询 |

### 7.6 写入频率模式

| 模式 | 触发时机 | 特点 |
|------|---------|------|
| `async` | 后台 daemon thread + queue | 不阻塞主循环，最高性能 |
| `turn` | 每轮对话 | 最高持久性 |
| `session` | 会话结束时 | 低频写入 |
| `N`（数字） | 每 N 轮 | 可调节 |

---

## 8. HRR 代数记忆（Holographic Provider）

这是技术上最独特的 provider：

**核心思想**：不用向量相似度搜索，用代数运算（Holographic Reduced Representations）：
- 记忆存储为**叠加的复值向量**（superposed complex-valued vectors）
- 检索是代数运算，而非最近邻搜索
- 实现：纯 SQLite，无额外 pip 依赖，亚毫秒检索延迟

**设计哲学**：轻量、本地、自校正，而非富结构、外部托管。

**Trust Scoring（信任评分）**：跨会话多次被确认的记忆权重上升，被新信息反驳的权重下降，使记忆向**自校正**而非纯积累演进。

---

## 9. 与 Bourbon 对比及可吸收 Ideas

### 9.1 现状对比

| 能力 | Hermes | Bourbon 现状 |
|------|--------|--------------|
| 系统提示记忆（MEMORY.md） | ✅ 2200字符 + 冻结快照 | ✅ Phase 2 已实现 |
| 记忆 promote/reject | ✅ Trust scoring 自动衰减 | ✅ 手动 promote/reject |
| 跨会话 FTS5 召回 | ✅ + LLM 摘要注入 | ❌ 无 |
| **记忆安全扫描** | ✅ `_scan_memory_content` | ❌ 无 |
| **Agent 自主写 Skill** | ✅ `skill_manage` | ❌ 只有人工 Skill |
| Bundle Skill 写保护 | ✅ 区分用户/bundle | ❌ 无区分 |
| Skill 安全扫描 | ✅ quarantine 系统 | ❌ 无 |
| 辩证用户建模 | ✅ Honcho 多轮推理 | ❌ 无 |
| Trust scoring 自动衰减 | ✅ HRR provider | ❌ 无 |
| RL 轨迹记录 | ✅ JSONL Batch 模式 | ❌ 无 |
| 可插拔记忆后端 | ✅ 7 个 provider | ❌ 单一实现 |

### 9.2 优先吸收建议

**P0 — 安全性（低成本高价值）**

- **记忆安全扫描**：agent 能写记忆就必须扫注入攻击。在 `memory_write` 路径加 `_scan_memory_content`，检测 prompt injection / 外泄 / 零宽字符，成本极低但价值极高。

**P1 — 自进化（核心差距）**

- **Agent 自主写 Skill**：bourbon 的 skill 工具已有三级渐进式加载，只差给 agent 开放 `create/patch` 权限。加写保护区分 bundle/user skill 后即可落地。
- **任务完成触发 skill 提炼**：在对话循环结束时（类似 Hermes 的 stopHooks）判断是否应提炼当前任务为 skill。

**P2 — 记忆深度（长期价值）**

- **FTS5 跨会话召回 + LLM 摘要注入**：bourbon 已有 SQLite，加 FTS5 虚拟表 + 摘要注入是最低成本的跨会话记忆方案。
- **Trust scoring 自动衰减**：在现有 MemoryPromote/Reject 基础上加数值分数，让旧的、被反驳的记忆自动降权。

**P3 — 工程完善**

- **Bundle Skill 写保护**：防止 agent 自进化时误删内置 skill。
- **Frozen Snapshot 显式化**：确认 bourbon 的记忆注入也遵循"会话内不变"的 prefix cache 优化原则。

---

## 10. 参考资料

- [DeepWiki: NousResearch/hermes-agent](https://deepwiki.com/NousResearch/hermes-agent)
- [DeepWiki: Memory and Sessions](https://deepwiki.com/NousResearch/hermes-agent/4.3-context-management-and-compression)
- [DeepWiki: Skills System](https://deepwiki.com/NousResearch/hermes-agent/8-skills-system)
- [DeepWiki: Honcho Integration](https://deepwiki.com/NousResearch/hermes-agent/4.4-honcho-integration)
- [Hermes Agent 官方文档](https://hermes-agent.nousresearch.com/docs/)
- [Honcho Memory 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/honcho)
- [Memory Providers 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers)
- [Hermes Agent Holographic Memory: Technical Deep Dive](https://hindsight.vectorize.io/guides/2026/04/21/guide-hermes-agent-holographic-memory-technical-deep-dive)
- [How Hermes Agent Memory Actually Works](https://vectorize.io/articles/hermes-agent-memory-explained)
- [GitHub: NousResearch/hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution)
- [Inside Hermes Agent: How a Self-Improving AI Agent Actually Works](https://mranand.substack.com/p/inside-hermes-agent-how-a-self-improving)
