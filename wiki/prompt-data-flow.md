# Claude Code Prompt 数据流详解

本文档详细描述 Claude Code 中 Prompt 从构建到发送给 LLM 的完整数据流。

---

## 一、Prompt 构建流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           用户输入                                           │
│  "帮我分析一下这个项目的架构"                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Step 1: Agent 选择/创建                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   如果调用 AgentTool:                                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  判断路径:                                                          │   │
│   │  ┌─────────────┐    ┌─────────────┐                                │   │
│   │  │ Fork 路径   │    │ 标准路径    │                                │   │
│   │  │ (无 subagent_type)│ (指定 subagent_type)                       │   │
│   │  └──────┬──────┘    └──────┬──────┘                                │   │
│   │         │                   │                                       │   │
│   │         ▼                   ▼                                       │   │
│   │  继承父 Agent 上下文     使用指定 Agent 的系统提示词                  │   │
│   │  • 系统提示词            • 独立的系统提示词                          │   │
│   │  • 完整消息历史          • 简单的用户消息                            │   │
│   │  • 工具定义              • 组装的工具池                              │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   如果直接对话:                                                              │
│   • 使用主线程 Agent 定义（如果有）                                          │
│   • 或使用默认系统提示词                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 2: 系统提示词构建                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   buildEffectiveSystemPrompt()                                              │
│                                                                             │
│   优先级判断:                                                                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 1. overrideSystemPrompt? → 完全覆盖所有内容                         │   │
│   │ 2. isCoordinatorMode? → 使用 Coordinator 系统提示词                 │   │
│   │ 3. mainThreadAgentDefinition?                                       │   │
│   │    ├── isProactiveActive? → 追加到默认提示词                         │   │
│   │    └── 标准模式 → 替换默认提示词                                     │   │
│   │ 4. customSystemPrompt? → 使用自定义                                  │   │
│   │ 5. defaultSystemPrompt → 使用默认                                    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   系统提示词结构:                                                            │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ [0]  Simple Intro         - 身份介绍                                │   │
│   │ [1]  Simple System        - 系统规则                                │   │
│   │ [2]  Doing Tasks          - 任务指南                                │   │
│   │ [3]  Actions              - 行动注意事项                             │   │
│   │ [4]  Using Your Tools     - 工具使用                                 │   │
│   │ [5]  Tone and Style       - 语气风格                                 │   │
│   │ [6]  Output Efficiency    - Token 效率                               │   │
│   │ [7]  SYSTEM_PROMPT_DYNAMIC_BOUNDARY                                 │   │
│   │ [8+] Dynamic Sections     - 动态内容                                 │   │
│   │       • session_guidance                                             │   │
│   │       • memory                                                       │   │
│   │       • env_info_simple                                              │   │
│   │       • language                                                     │   │
│   │       • output_style                                                 │   │
│   │       • mcp_instructions                                             │   │
│   │       • token_budget                                                 │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   动态 Section 计算:                                                         │
│   • 使用 systemPromptSection() → 缓存跨轮次                                │
│   • 使用 DANGEROUS_uncachedSystemPromptSection() → 每轮重新计算            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 3: 上下文加载                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   用户上下文 (getUserContext):                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ • CLAUDE.md 文件内容                                                 │   │
│   │   - 按优先级加载: user → project → local                             │   │
│   │   - 支持 @include 指令                                               │   │
│   │   - 支持 paths frontmatter 过滤                                      │   │
│   │ • 当前日期                                                           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   系统上下文 (getSystemContext):                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ • Git 状态 (分支、最近提交、是否 clean)                               │   │
│   │ • 缓存破坏标记 (ant-only 调试)                                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   注入方式:                                                                  │
│   • 系统上下文 → 追加到系统提示词                                           │
│   • 用户上下文 → 包装为 <system-reminder> 前置到用户消息                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 4: 工具描述生成                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   每个工具的 prompt() 方法:                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ BashTool:                                                            │   │
│   │   - 工具偏好指导（优先使用专用工具）                                    │   │
│   │   - Git 操作安全协议                                                  │   │
│   │   - 后台任务使用说明                                                  │   │
│   │                                                                     │   │
│   │ FileReadTool:                                                        │   │
│   │   - 必须使用绝对路径                                                  │   │
│   │   - 最大 2000 行限制                                                  │   │
│   │   - 支持多媒体文件                                                    │   │
│   │                                                                     │   │
│   │ FileEditTool:                                                        │   │
│   │   - StrReplaceFile 使用指南                                           │   │
│   │   - 多行字符串支持                                                    │   │
│   │   - replace_all 参数说明                                              │   │
│   │                                                                     │   │
│   │ AgentTool:                                                           │   │
│   │   - Agent 类型列表                                                    │   │
│   │   - Fork vs 独立 Agent 的使用指导                                     │   │
│   │   - Prompt 编写最佳实践                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   工具 Schema 转换 (toolToAPISchema):                                        │
│   • 缓存基础 schema（名称、描述、input_schema）                             │
│   • 添加 per-request overlay:                                               │
│     - defer_loading（工具搜索功能）                                          │
│     - cache_control（提示缓存标记）                                          │
│     - strict（严格模式）                                                     │
│     - eager_input_streaming（细粒度工具流）                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 5: 消息列表组装                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   normalizeMessagesForAPI():                                                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 1. 重新排序附件，向上冒泡                                              │   │
│   │    附件消息会向前移动，直到遇到 tool result 或 assistant message       │   │
│   │                                                                     │   │
│   │ 2. 过滤虚拟消息                                                        │   │
│   │    isVirtual=true 的消息不发送到 API                                   │   │
│   │                                                                     │   │
│   │ 3. 处理错误消息的媒体块剥离                                            │   │
│   │    PDF/图片过大错误时移除媒体块                                         │   │
│   │                                                                     │   │
│   │ 4. 合并连续的 user messages                                            │   │
│   │                                                                     │   │
│   │ 5. 处理 tool_reference 块（工具搜索功能）                              │   │
│   │    - 启用时: 保留 tool_reference 块                                    │   │
│   │    - 禁用时: 剥离 tool_reference 块                                    │   │
│   │                                                                     │   │
│   │ 6. 注入 tool_reference 边界标记                                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   消息格式:                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ [0] system: 系统提示词数组                                            │   │
│   │ [1] user: <system-reminder>用户上下文</system-reminder>               │   │
│   │       用户实际输入                                                    │   │
│   │ [2] assistant: tool_use 调用                                         │   │
│   │ [3] user: tool_result + 新用户输入                                   │   │
│   │ ...                                                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 6: 缓存标记插入                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   addCacheBreakpoints():                                                    │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ • 最后一条用户消息获得 cache_control 标记                             │   │
│   │ • 支持 1h TTL（针对订阅者）                                           │   │
│   │ • 支持两种 scope:                                                     │   │
│   │   - global: 静态系统提示词内容                                        │   │
│   │   - org: 动态内容或启用 MCP 时                                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   splitSysPromptPrefix():                                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 系统提示词分割策略:                                                   │   │
│   │                                                                     │   │
│   │ 场景1: 无 MCP 工具 + 全局缓存启用                                      │   │
│   │   - 静态内容（DYNAMIC_BOUNDARY 之前）→ global scope                  │   │
│   │   - 动态内容 → 无缓存                                                 │   │
│   │                                                                     │   │
│   │ 场景2: 有 MCP 工具                                                    │   │
│   │   - 全部使用 org scope（MCP 工具导致无法使用全局缓存）                 │   │
│   │                                                                     │   │
│   │ 场景3: 全局缓存禁用                                                    │   │
│   │   - 全部使用 org scope                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 7: Token 计算与预算检查                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Token 计数服务 (services/tokenEstimation.ts):                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ • API Token 计数: 调用 Anthropic API 的计数端点                       │   │
│   │ • 粗略估算: content.length / 4（默认）                                │   │
│   │ • 按文件类型调整:                                                     │   │
│   │   - JSON: 2 bytes/token（更密的表示）                                  │   │
│   │   - 其他: 4 bytes/token                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Token 预算管理:                                                            │
│   • 检查输入 token 是否超过阈值                                             │
│   • 触发 compact/summarize 操作                                             │
│   • 跟踪累计 token 使用                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Step 8: LLM API 调用                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   API 请求结构:                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ {                                                                    │   │
│   │   model: "claude-3-opus-20240229",                                   │   │
│   │   max_tokens: 8192,                                                  │   │
│   │   system: [                                                          │   │
│   │     {                                                                │   │
│   │       type: "text",                                                  │   │
│   │       text: "系统提示词内容...",                                      │   │
│   │       cache_control: { type: "ephemeral", scope: "global" }          │   │
│   │     }                                                                │   │
│   │   ],                                                                 │   │
│   │   messages: [                                                        │   │
│   │     { role: "user", content: [...] },                                │   │
│   │     { role: "assistant", content: [...] },                           │   │
│   │     ...                                                              │   │
│   │   ],                                                                 │   │
│   │   tools: [tool definitions...],                                      │   │
│   │   tool_choice: { type: "auto" }                                      │   │
│   │ }                                                                    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   流式响应处理:                                                              │
│   • content_block_start                                                  │
│   • content_block_delta                                                  │
│   • content_block_stop                                                   │
│   • message_delta（包含 usage 信息）                                       │
│   • message_stop                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、关键数据转换详解

### 2.1 消息重新排序算法

```typescript
function reorderAttachmentsForAPI(messages: Message[]): Message[] {
  // 附件消息需要向上"冒泡"，直到遇到:
  // 1. 非附件消息
  // 2. tool_result 消息（附件属于该 tool result）
  // 3. assistant 消息（附件是 assistant 的上下文）
  
  // 这样可以确保附件紧接在相关的消息之后
}
```

### 2.2 Tool Result 配对检查

```typescript
function ensureToolResultPairing(messages: Message[]): Message[] {
  // 确保每个 tool_use 都有对应的 tool_result
  // 处理会话恢复时可能出现的不匹配情况
  
  // 算法:
  // 1. 收集所有 tool_use IDs
  // 2. 收集所有 tool_result IDs
  // 3. 对于不匹配的 tool_use，创建虚拟的 tool_result
}
```

### 2.3 系统提示词分割算法

```typescript
function splitSystemPromptForCaching(
  systemPrompt: string[],
  hasMcpTools: boolean
): SystemPromptBlock[] {
  if (hasMcpTools) {
    // MCP 工具会改变系统提示词，无法使用全局缓存
    return [{
      text: systemPrompt.join('\n'),
      cache_control: { type: 'ephemeral', scope: 'org' }
    }];
  }
  
  const boundaryIndex = systemPrompt.indexOf(SYSTEM_PROMPT_DYNAMIC_BOUNDARY);
  
  return [
    {
      // 静态部分 - 可使用全局缓存
      text: systemPrompt.slice(0, boundaryIndex).join('\n'),
      cache_control: { type: 'ephemeral', scope: 'global' }
    },
    {
      // 动态部分 - 不使用缓存
      text: systemPrompt.slice(boundaryIndex + 1).join('\n'),
      cache_control: null
    }
  ];
}
```

---

## 三、Skill 执行的数据流

```
用户输入: "/<skill-name> <args>"
        │
        ▼
┌─────────────────────────────────────────────┐
│ 1. 解析 Skill 命令                           │
│    - 从 skillRegistry 查找 skill             │
│    - 解析参数                                │
└─────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│ 2. 确定执行模式                              │
│    ┌──────────────┐  ┌──────────────┐       │
│    │ Inline 模式  │  │ Fork 模式    │       │
│    │ (context:    │  │ (context:    │       │
│    │  inline)     │  │  fork)       │       │
│    └──────┬───────┘  └──────┬───────┘       │
│           │                  │               │
│           ▼                  ▼               │
│    在当前对话中       创建子 Agent           │
│    执行 Skill         执行 Skill             │
└─────────────────────────────────────────────┘
        │
        ├── Inline 路径 ──────────────────────┐
        │                                      ▼
        │   ┌─────────────────────────────────────────────┐
        │   │ 3a. 构建 Skill Prompt                        │
        │   │    • 读取 SKILL.md 内容                      │
        │   │    • 解析 frontmatter                        │
        │   │    • 替换参数变量 ($arg1, $arg2...)          │
        │   └─────────────────────────────────────────────┘
        │                          │
        │                          ▼
        │   ┌─────────────────────────────────────────────┐
        │   │ 4a. 作为用户消息发送                         │
        │   │    • Skill 内容作为用户输入                  │
        │   │    • 限制工具权限（allowed-tools）           │
        │   └─────────────────────────────────────────────┘
        │
        └── Fork 路径 ─────────────────────────┐
                                                ▼
           ┌─────────────────────────────────────────────┐
           │ 3b. 准备 Fork 上下文                         │
           │    • 解析 SKILL.md                           │
           │    • 确定使用的 Agent                        │
           │    • 组装工具池                              │
           └─────────────────────────────────────────────┘
                              │
                              ▼
           ┌─────────────────────────────────────────────┐
           │ 4b. 创建子 Agent                             │
           │    • 设置独立系统提示词                      │
           │    • 初始化 Token 预算                       │
           │    • 运行 Agent 生命周期                     │
           └─────────────────────────────────────────────┘
                              │
                              ▼
           ┌─────────────────────────────────────────────┐
           │ 5b. 流式返回结果                             │
           │    • 通过 <task> 标签包装                    │
           │    • 父 Agent 接收流式更新                   │
           └─────────────────────────────────────────────┘
```

---

## 四、Fork Subagent 的 Cache-Safe 设计

Fork Subagent 的核心优势在于能够共享父 Agent 的 Prompt Cache，这需要满足严格的匹配条件：

### 4.1 Cache-Safe 参数定义

```typescript
type CacheSafeParams = {
  // 必须完全匹配父 Agent 的值
  systemPrompt: SystemPrompt;              // 相同的系统提示词
  userContext: { [k: string]: string };    // 相同的用户上下文
  systemContext: { [k: string]: string };  // 相同的系统上下文
  toolUseContext: ToolUseContext;          // 相同的工具上下文
  forkContextMessages: Message[];          // 父 Agent 的完整消息历史
};
```

### 4.2 确保 Cache 命中的措施

1. **系统提示词复用**
   ```typescript
   // 直接使用父 Agent 渲染后的系统提示词
   forkParentSystemPrompt = toolUseContext.renderedSystemPrompt;
   ```

2. **工具定义复用**
   ```typescript
   // 使用完全相同的工具定义
   availableTools: toolUseContext.options.tools,
   useExactTools: true,
   ```

3. **消息历史继承**
   ```typescript
   // 传递完整的消息历史
   forkContextMessages: toolUseContext.messages,
   ```

4. **避免 GrowthBook 状态差异**
   ```typescript
   // 如果父 Agent 系统提示词未缓存，重新计算时可能因功能标志状态略有不同
   // 这种情况下会回退到重新计算，但可能导致 cache miss
   ```

### 4.3 Fork 消息的特殊结构

```typescript
// Fork 消息 = 完整父 Assistant 消息 + 占位符 Tool Results + Fork 指令

// 消息结构示例:
[
  {
    role: "assistant",
    content: [
      { type: "text", text: "我来帮你分析..." },
      { type: "tool_use", id: "tool_1", name: "Read", input: {...} },
      { type: "tool_use", id: "tool_2", name: "Glob", input: {...} },
      // ... 所有其他的 tool_use
    ]
  },
  {
    role: "user",
    content: [
      { type: "tool_result", tool_use_id: "tool_1", content: "Fork started..." },
      { type: "tool_result", tool_use_id: "tool_2", content: "Fork started..." },
      { type: "text", text: "Fork directive: 详细分析这些文件..." }
    ]
  }
]
```

这种结构使得 API 层面的 Prompt 缓存能够识别这是从同一个对话分叉出来的请求。

---

## 五、Token 计算详细算法

### 5.1 精确计数（API 方式）

```typescript
async function countTokensWithAPI(messages, tools): Promise<number> {
  const response = await anthropic.messages.countTokens({
    model: 'claude-3-opus-20240229',
    messages: normalizeMessagesForAPI(messages),
    tools: tools.map(t => t.schema),
  });
  return response.input_tokens;
}
```

### 5.2 粗略估算（本地方式）

```typescript
function roughTokenCount(content: string, bytesPerToken: number = 4): number {
  return Math.round(content.length / bytesPerToken);
}

function bytesPerTokenForFileType(ext: string): number {
  switch (ext) {
    case 'json':
    case 'jsonl':
    case 'jsonc':
      return 2;  // JSON 有更小的 token 比率
    default:
      return 4;
  }
}
```

### 5.3 混合计数策略

```typescript
function tokenCountWithEstimation(messages: Message[]): number {
  // 1. 找到最后一个有 usage 数据的 assistant message
  const lastUsageIndex = findLastIndex(messages, m => 
    m.type === 'assistant' && m.message.usage
  );
  
  if (lastUsageIndex === -1) {
    // 没有历史 usage 数据，全部使用估算
    return roughTokenCountForMessages(messages);
  }
  
  // 2. 获取最后一个已知 usage 的 token 数
  const baseCount = getTokenCountFromUsage(
    messages[lastUsageIndex].message.usage
  );
  
  // 3. 为之后的消息添加粗略估算
  const remainingMessages = messages.slice(lastUsageIndex + 1);
  const estimated = roughTokenCountForMessages(remainingMessages);
  
  return baseCount + estimated;
}
```

---

## 六、Prompt 缓存命中率优化策略

### 6.1 多层次缓存

| 缓存层级 | 内容 | 有效期 |
|----------|------|--------|
| API Prompt Cache | 系统提示词 + 消息历史 | 1小时（TTL）|
| 系统提示词节缓存 | 各 Section 计算结果 | 跨轮次（内存）|
| 工具 Schema 缓存 | 工具描述文本 | 应用生命周期 |
| CLAUDE.md 缓存 | 文件内容 | 文件修改时间检查 |

### 6.2 缓存失效策略

```typescript
// 1. 动态 Section 标记
const dynamicSection = DANGEROUS_uncachedSystemPromptSection(
  'mcp_instructions',
  computeMcpInstructions,
  'MCP servers can change during session'
);

// 2. 功能标志状态检查
if (hasFeatureFlagChanged('newToolDescriptions')) {
  clearToolSchemaCache();
}

// 3. 文件修改时间检查
if (claideMdMtime > claudeMdCacheMtime) {
  reloadClaudeMdFiles();
}
```

### 6.3 缓存友好的 Prompt 设计

1. **静态内容前置**: 将所有可缓存的内容放在 `DYNAMIC_BOUNDARY` 之前
2. **确定性顺序**: 系统提示词节的顺序必须确定，避免随机化
3. **避免时间戳**: 除非必要，否则不要在静态内容中包含时间戳
4. **参数化动态内容**: 使用 Section 函数封装动态计算

---

*文档结束*
