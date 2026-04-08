# Claude Code Prompt 架构研究报告

本目录包含对 Claude Code CLI 工具中 Prompt 设计的深度研究报告。

---

## 文档导航

| 文档 | 内容 | 适合读者 |
|------|------|----------|
| [claude-code-prompt-architecture.md](./claude-code-prompt-architecture.md) | 完整架构概览 | 所有人 |
| [prompt-data-flow.md](./prompt-data-flow.md) | Prompt 数据流详解 | 需要深入理解流程的读者 |
| [prompt-code-patterns.md](./prompt-code-patterns.md) | 代码模式与最佳实践 | 开发者 |

---

## 快速概览

### 核心架构特点

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code Prompt 架构核心特点                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 分层模块化设计                                           │
│     • 基础系统提示词 → Agent 特定 → Skill → 用户上下文        │
│                                                             │
│  2. 缓存优先设计                                              │
│     • 静态/动态内容分离 (DYNAMIC_BOUNDARY)                   │
│     • 多层次缓存策略                                         │
│                                                             │
│  3. 双路径 Agent 执行                                         │
│     • Fork 路径: 继承父 Agent 上下文（Cache-Safe）           │
│     • 标准路径: 独立 Agent 执行                               │
│                                                             │
│  4. Skill 系统                                                │
│     • SKILL.md 文件定义                                       │
│     • 支持 Inline 和 Fork 两种执行模式                       │
│                                                             │
│  5. 安全内建                                                  │
│     • Prompt Injection 防护                                   │
│     • Unicode 字符清理                                        │
│     • 敏感信息过滤                                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 关键文件索引

| 文件路径 | 行数 | 核心功能 |
|----------|------|----------|
| `constants/prompts.ts` | ~900 | 系统提示词主构建逻辑 |
| `utils/systemPrompt.ts` | ~150 | 系统提示词优先级系统 |
| `constants/systemPromptSections.ts` | ~200 | 动态 Section 管理 |
| `tools/AgentTool/prompt.ts` | ~200 | Agent 工具提示词 |
| `tools/AgentTool/forkSubagent.ts` | ~150 | Fork 子 Agent 逻辑 |
| `utils/messages.ts` | ~500 | 消息构建与格式化 |
| `skills/loadSkillsDir.ts` | ~300 | Skill 加载器 |

---

## 关键洞察

### 1. Prompt 即代码

Claude Code 将 Prompt 视为一等公民，拥有完整的类型系统和构建流程：

```typescript
// 品牌类型确保类型安全
export type SystemPrompt = readonly string[] & {
  readonly __brand: 'SystemPrompt';
};

// 优先级系统管理提示词选择
buildEffectiveSystemPrompt({
  overrideSystemPrompt,      // 优先级 1
  mainThreadAgentDefinition, // 优先级 2
  customSystemPrompt,        // 优先级 3
  defaultSystemPrompt,       // 优先级 4
  appendSystemPrompt,        // 优先级 5
});
```

### 2. 缓存优先的架构设计

```
静态内容 (可缓存)                    动态内容 (不缓存)
┌─────────────────────┐             ┌─────────────────────┐
│ • Simple Intro      │             │ • session_guidance  │
│ • System Rules      │  DYNAMIC    │ • memory            │
│ • Task Guidelines   │  BOUNDARY   │ • env_info_simple   │
│ • Actions           │  ─────────▶ │ • mcp_instructions  │
│ • Tool Usage        │             │ • token_budget      │
└─────────────────────┘             └─────────────────────┘
         │                                    │
         └────────────┬───────────────────────┘
                      ▼
         [global scope cache]          [no cache]
```

### 3. Agent 即函数

通过 `AsyncLocalStorage` 在异步操作中传递 Agent 上下文：

```typescript
const agentContextStorage = new AsyncLocalStorage<AgentContext>();

export function runWithAgentContext<T>(context: AgentContext, fn: () => T): T {
  return agentContextStorage.run(context, fn);
}
```

### 4. Fork 子 Agent 的 Cache-Safe 设计

Fork Subagent 通过复用父 Agent 的完整上下文实现 API 级别的 prompt cache 共享：

```typescript
// 1. 复用系统提示词
forkParentSystemPrompt = toolUseContext.renderedSystemPrompt;

// 2. 复用工具定义
availableTools = toolUseContext.options.tools;
useExactTools = true;

// 3. 继承消息历史
forkContextMessages = toolUseContext.messages;
```

---

## 适合学习的场景

### 如果你想要...

| 目标 | 推荐阅读 |
|------|----------|
| 快速理解整体架构 | [claude-code-prompt-architecture.md](./claude-code-prompt-architecture.md) |
| 实现类似的 Prompt 系统 | [prompt-code-patterns.md](./prompt-code-patterns.md) |
| 理解数据流向和缓存策略 | [prompt-data-flow.md](./prompt-data-flow.md) |
| 了解 Agent 系统设计 | [claude-code-prompt-architecture.md](./claude-code-prompt-architecture.md) 第4节 |
| 学习 Skill 系统 | [claude-code-prompt-architecture.md](./claude-code-prompt-architecture.md) 第5节 |
| 了解安全防护措施 | [claude-code-prompt-architecture.md](./claude-code-prompt-architecture.md) 第8节 |

---

## 相关资源

- [Claude Code 官方文档](https://docs.anthropic.com/en/docs/claude-code/overview)
- [Anthropic API 文档](https://docs.anthropic.com/en/api/getting-started)
- [Prompt Caching 指南](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)

---

*研究日期: 2026-04-01*
