# Claude Code Prompt 代码模式与最佳实践

本文档展示 Claude Code 中使用的具体代码模式，供参考学习。

---

## 一、系统提示词构建模式

### 1.1 基础系统提示词构建

```typescript
// constants/prompts.ts

import { feature } from '../utils/feature';

// 使用功能标志进行条件编译
const hasComplexPrompts = feature('complexPrompts2024');

/**
 * 主入口：获取完整的系统提示词
 */
export async function getSystemPrompt(
  tools: Tools,
  model: string,
  outputContext: OutputContext,
  outputStyleConfig: OutputStyleConfig,
): Promise<string[]> {
  const enabledTools = getToolsAvailableToModel(tools, model);
  
  // 静态内容（可缓存）
  const staticSections = [
    getSimpleIntroSection(outputStyleConfig),
    getSimpleSystemSection(),
    getSimpleDoingTasksSection(),
    getActionsSection(),
    getUsingYourToolsSection(enabledTools),
    getSimpleToneAndStyleSection(),
    getOutputEfficiencySection(),
  ];
  
  // 动态边界标记 - 用于区分可缓存和不可缓存内容
  const boundary = [SYSTEM_PROMPT_DYNAMIC_BOUNDARY];
  
  // 动态内容（通过 systemPromptSection 管理）
  const dynamicSections = await resolveSystemPromptSections([
    sessionGuidanceSection,
    memorySection,
    envInfoSimpleSection,
    languageSection,
    outputStyleSection,
    mcpInstructionsSection,
    tokenBudgetSection,
  ]);
  
  return [...staticSections, ...boundary, ...dynamicSections];
}

/**
 * 动态 Section 定义示例
 */
export const envInfoSimpleSection = systemPromptSection(
  'env_info_simple',
  async () => {
    const envInfo = await computeSimpleEnvInfo();
    return `Environment Information:\n${envInfo}`;
  },
);

// 需要每轮重新计算的 Section
export const mcpInstructionsSection = DANGEROUS_uncachedSystemPromptSection(
  'mcp_instructions',
  async () => getMcpInstructions(),
  'MCP servers can change during session',
);
```

### 1.2 带优先级的系统提示词选择

```typescript
// utils/systemPrompt.ts

export type BuildSystemPromptParams = {
  mainThreadAgentDefinition?: AgentDefinition;
  toolUseContext: ToolUseContext;
  customSystemPrompt?: string;
  defaultSystemPrompt: SystemPrompt;
  appendSystemPrompt?: string;
  overrideSystemPrompt?: string;
};

export function buildEffectiveSystemPrompt({
  mainThreadAgentDefinition,
  toolUseContext,
  customSystemPrompt,
  defaultSystemPrompt,
  appendSystemPrompt,
  overrideSystemPrompt,
}: BuildSystemPromptParams): SystemPrompt {
  // 优先级 1: 完全覆盖
  if (overrideSystemPrompt) {
    return asSystemPrompt([overrideSystemPrompt]);
  }
  
  // 优先级 2: Coordinator 模式
  if (isCoordinatorMode() && !mainThreadAgentDefinition) {
    return asSystemPrompt([
      getCoordinatorSystemPrompt(),
      ...(appendSystemPrompt ? [appendSystemPrompt] : []),
    ]);
  }
  
  // 获取 Agent 系统提示词
  const agentSystemPrompt = mainThreadAgentDefinition
    ? isBuiltInAgent(mainThreadAgentDefinition)
      ? mainThreadAgentDefinition.getSystemPrompt({ toolUseContext })
      : mainThreadAgentDefinition.getSystemPrompt()
    : undefined;
  
  // 优先级 3: Proactive 模式（追加而非替换）
  if (agentSystemPrompt && isProactiveActive()) {
    return asSystemPrompt([
      ...defaultSystemPrompt,
      `\n# Custom Agent Instructions\n${agentSystemPrompt}`,
      ...(appendSystemPrompt ? [appendSystemPrompt] : []),
    ]);
  }
  
  // 标准模式：Agent 提示词替换默认提示词
  return asSystemPrompt([
    ...(agentSystemPrompt ?? customSystemPrompt ?? defaultSystemPrompt),
    ...(appendSystemPrompt ? [appendSystemPrompt] : []),
  ]);
}
```

---

## 二、Agent 定义模式

### 2.1 内置 Agent 定义

```typescript
// tools/AgentTool/built-in/exploreAgent.ts

import type { BuiltInAgentDefinition } from '../loadAgentsDir';

export const EXPLORE_AGENT: BuiltInAgentDefinition = {
  agentType: 'Explore',
  description: 'Fast codebase exploration with prompt-enforced read-only behavior',
  whenToUse: 'Use this agent for: exploring codebases, finding files by patterns, ' +
    'searching code for keywords, answering questions about how code works',
  disallowedTools: [
    'Write',
    'Edit',
    'Bash:rm:*',
    'Bash:mv:*',
    'Bash:cp:*',
    'Bash:git:commit',
    'Bash:git:push',
    'Bash:git:checkout',
  ],
  model: 'inherit',  // 继承父 Agent 的模型
  omitClaudeMd: true,  // 排除 CLAUDE.md 以节省 token
  getSystemPrompt: () => getExploreSystemPrompt(),
};

function getExploreSystemPrompt(): string {
  return `You are a file search specialist for Claude Code...

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files
- Modifying existing files  
- Running commands that modify the filesystem
Your role is EXCLUSIVELY to search and analyze existing code...

## When to Use This Tool
- "quick": targeted lookups — find a specific file, function, or config value
- "medium": understand a module — how does auth work, what calls this API
- "thorough": cross-cutting analysis — architecture overview, dependency mapping`;
}
```

### 2.2 自定义 Agent（用户/项目级）

```typescript
// tools/AgentTool/loadAgentsDir.ts

const AgentJsonSchema = z.object({
  description: z.string().min(1),
  tools: z.array(z.string()).optional(),
  disallowedTools: z.array(z.string()).optional(),
  prompt: z.string().min(1),
  model: z.string().optional(),
  effort: z.union([z.enum(EFFORT_LEVELS), z.number().int()]).optional(),
  permissionMode: z.enum(PERMISSION_MODES).optional(),
  mcpServers: z.array(AgentMcpServerSpecSchema).optional(),
  hooks: HooksSchema().optional(),
  maxTurns: z.number().int().positive().optional(),
  skills: z.array(z.string()).optional(),
  initialPrompt: z.string().optional(),
  memory: z.enum(['user', 'project', 'local']).optional(),
  background: z.boolean().optional(),
  isolation: z.enum(['worktree', 'remote']).optional(),
});

// 从目录加载自定义 Agent
export async function loadAgentsFromDir(
  dir: string,
  source: SettingSource,
): Promise<CustomAgentDefinition[]> {
  const agents: CustomAgentDefinition[] = [];
  
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    
    const agentJsonPath = join(dir, entry.name, 'agent.json');
    const promptPath = join(dir, entry.name, 'prompt.md');
    
    if (!(await exists(agentJsonPath))) continue;
    
    const config = AgentJsonSchema.parse(
      JSON.parse(await readFile(agentJsonPath, 'utf-8'))
    );
    
    const prompt = await readFile(promptPath, 'utf-8');
    
    agents.push({
      agentType: entry.name,
      source,
      ...config,
      getSystemPrompt: () => prompt,
    });
  }
  
  return agents;
}
```

---

## 三、Skill 定义模式

### 3.1 SKILL.md 文件格式

```markdown
<!-- .claude/skills/analyze-architecture/SKILL.md -->

---
name: Analyze Architecture
description: Analyze project architecture and generate documentation
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(find:*)
  - Bash(tree:*)
when_to_use: |
  Use this skill when you need to:
  - Understand the overall architecture of a project
  - Identify the main modules and their relationships
  - Generate architecture documentation
argument-hint: "[path-to-analyze]"
arguments:
  - path
context: fork
agent: Explore
---

# Analyze Architecture

This skill analyzes the project architecture at the specified path.

## Inputs

- `$path`: The directory path to analyze (default: current directory)

## Goal

Produce a comprehensive architecture analysis including:
1. Directory structure overview
2. Key modules and their purposes
3. Dependency relationships
4. Entry points and main flows

## Steps

1. Explore the directory structure using `find` or `tree`
2. Identify key configuration files (package.json, tsconfig.json, etc.)
3. Read main entry points and core module files
4. Analyze import/export relationships
5. Generate architecture summary

## Output Format

```markdown
# Architecture Analysis: [Project Name]

## Overview
[Brief description]

## Directory Structure
[Tree or description]

## Key Modules
- **module1**: [description]
- **module2**: [description]

## Dependencies
[Dependency graph or description]

## Entry Points
- [entry1]: [description]
```
```

### 3.2 Skill 注册与加载

```typescript
// skills/bundledSkills.ts

export type BundledSkillDefinition = {
  name: string;
  description: string;
  whenToUse?: string;
  allowedTools?: string[];
  userInvocable?: boolean;
  getPromptForCommand: (
    args: string,
    context: ToolUseContext
  ) => Promise<ContentBlockParam[]>;
};

const bundledSkills: Command[] = [];

export function registerBundledSkill(definition: BundledSkillDefinition): void {
  const command: Command = {
    type: 'prompt',
    name: definition.name,
    description: definition.description,
    allowedTools: definition.allowedTools ?? [],
    userInvocable: definition.userInvocable ?? true,
    source: 'bundled',
    loadedFrom: 'bundled',
    getPromptForCommand: async (args, context) => {
      const blocks = await definition.getPromptForCommand(args, context);
      return blocks;
    },
  };
  
  bundledSkills.push(command);
}

// 使用示例
registerBundledSkill({
  name: '/remember',
  description: 'Remember important information for future sessions',
  allowedTools: ['Read', 'Write'],
  getPromptForCommand: async (args, context) => {
    return [{
      type: 'text',
      text: `Remember the following information: ${args}\n\n` +
            `Store this in the appropriate memory location...`,
    }];
  },
});
```

---

## 四、工具 Prompt 模式

### 4.1 工具 Prompt 生成

```typescript
// tools/BashTool/prompt.ts

import type { ToolPromptOptions } from '../Tool';

export async function getPrompt(options: ToolPromptOptions): Promise<string> {
  const { getToolPermissionContext, tools } = options;
  const context = await getToolPermissionContext();
  
  const sections: string[] = [
    getBasicDescription(),
    getToolPreferenceGuidance(tools),
    getMultiCommandGuidance(),
    getGitSafetyProtocol(),
    getSandboxInfo(context),
    getBackgroundTaskGuidance(),
  ];
  
  return sections.filter(Boolean).join('\n\n');
}

function getBasicDescription(): string {
  return `## Bash

The Bash tool executes bash commands in a non-interactive shell.

Arguments:
- command: The bash command to execute
- timeout?: Maximum execution time in milliseconds (default: 60000)
- workdir?: Working directory for the command`;
}

function getToolPreferenceGuidance(tools: Tools): string {
  // 如果有专用工具可用，建议优先使用
  const hasGitTool = tools.some(t => t.name === 'Git');
  
  if (hasGitTool) {
    return `Guidance: When available, prefer using the Git tool over Bash for git operations.
The Git tool provides safer, more controlled git operations.`;
  }
  
  return '';
}

function getGitSafetyProtocol(): string {
  return `Git Safety Protocol:
- Always check git status before operations
- Use --no-pager for non-interactive output
- Avoid destructive operations without user confirmation`;
}

function getBackgroundTaskGuidance(): string {
  return `Background Tasks:
- Use run_in_background=true for long-running tasks
- Provide a short description for background tasks
- Background tasks will notify when complete`;
}
```

### 4.2 工具 Schema 定义

```typescript
// tools/FileReadTool/Tool.tsx

import { z } from 'zod';

const InputSchema = z.object({
  file_path: z.string().describe('The absolute path to the file to read'),
  offset: z.number().optional().describe('Line number to start reading from'),
  limit: z.number().max(2000).optional().describe('Maximum number of lines to read'),
});

type Input = z.infer<typeof InputSchema>;

export class FileReadTool implements Tool {
  name = 'Read';
  description = 'Read the contents of a file';
  inputSchema = InputSchema;
  
  async prompt(options: ToolPromptOptions): Promise<string> {
    return `## Read

Read the contents of a file.

Guidance:
- Use absolute paths only
- Maximum limit: 2000 lines per call
- Supports images, PDFs, and Jupyter notebooks
- Use offset/limit for large files
- For multiple related files, prefer parallel Read calls`;
  }
  
  async call(input: Input, context: ToolUseContext): Promise<ToolResult> {
    // 实现...
  }
}
```

---

## 五、消息构建模式

### 5.1 创建各类消息

```typescript
// utils/messages.ts

import type { MessageParam, ContentBlockParam } from '@anthropic-ai/sdk/resources';

export interface UserMessage {
  type: 'user';
  content: string | ContentBlockParam[];
  isVirtual?: boolean;
}

export interface AssistantMessage {
  type: 'assistant';
  message: Message;
  isVirtual?: boolean;
}

/**
 * 创建用户消息
 */
export function createUserMessage({
  content,
  isVirtual = false,
}: {
  content: string | ContentBlockParam[];
  isVirtual?: boolean;
}): UserMessage {
  return { type: 'user', content, isVirtual };
}

/**
 * 创建助手消息
 */
export function createAssistantMessage({
  content,
  isVirtual = false,
}: {
  content: ContentBlockParam[];
  isVirtual?: boolean;
}): AssistantMessage {
  return {
    type: 'assistant',
    message: {
      id: generateMessageId(),
      type: 'message',
      role: 'assistant',
      content,
      model: '',
      stop_reason: 'end_turn',
      stop_sequence: null,
      usage: { input_tokens: 0, output_tokens: 0 },
    },
    isVirtual,
  };
}

/**
 * 创建工具结果消息
 */
export function createToolResultMessage(
  toolUseId: string,
  content: string | ContentBlockParam[],
  isError: boolean = false,
): UserMessage {
  return createUserMessage({
    content: [{
      type: 'tool_result',
      tool_use_id: toolUseId,
      content: typeof content === 'string' 
        ? [{ type: 'text', text: content }]
        : content,
      is_error: isError,
    }],
  });
}
```

### 5.2 消息标准化（API 发送前处理）

```typescript
// utils/messages.ts

export function normalizeMessagesForAPI(
  messages: Message[],
  tools: Tools = [],
): (UserMessage | AssistantMessage)[] {
  // 1. 重新排序附件
  let normalized = reorderAttachmentsForAPI(messages);
  
  // 2. 过滤虚拟消息
  normalized = normalized.filter(m => 
    !((m.type === 'user' || m.type === 'assistant') && m.isVirtual)
  );
  
  // 3. 处理错误消息的媒体块剥离
  normalized = normalized.map(m => {
    if (m.type === 'user' && hasMediaError(m)) {
      return stripMediaBlocks(m);
    }
    return m;
  });
  
  // 4. 合并连续的 user messages
  normalized = mergeConsecutiveUserMessages(normalized);
  
  // 5. 处理 tool_reference 块
  normalized = handleToolReferences(normalized, tools);
  
  // 6. 确保 tool_use/tool_result 配对
  normalized = ensureToolResultPairing(normalized);
  
  return normalized;
}

/**
 * 重新排序附件 - 向上冒泡直到遇到非附件消息
 */
function reorderAttachmentsForAPI(messages: Message[]): Message[] {
  const result: Message[] = [];
  const pendingAttachments: AttachmentMessage[] = [];
  
  for (const message of messages) {
    if (message.type === 'attachment') {
      pendingAttachments.push(message);
      continue;
    }
    
    // 如果遇到 tool_result 或 assistant，先附加待处理的附件
    if (
      pendingAttachments.length > 0 &&
      (message.type === 'user' && hasToolResult(message) ||
       message.type === 'assistant')
    ) {
      result.push(...pendingAttachments);
      pendingAttachments.length = 0;
    }
    
    result.push(message);
  }
  
  // 剩余的附件添加到末尾
  result.push(...pendingAttachments);
  
  return result;
}

/**
 * 合并连续的 user messages
 */
function mergeConsecutiveUserMessages(messages: Message[]): Message[] {
  const result: Message[] = [];
  
  for (const message of messages) {
    const lastMessage = result[result.length - 1];
    
    if (
      message.type === 'user' &&
      lastMessage?.type === 'user' &&
      typeof lastMessage.content !== 'string' &&
      typeof message.content !== 'string'
    ) {
      // 合并内容块
      lastMessage.content = [...lastMessage.content, ...message.content];
    } else {
      result.push(message);
    }
  }
  
  return result;
}
```

---

## 六、Fork Subagent 实现模式

### 6.1 Fork 消息构建

```typescript
// tools/AgentTool/forkSubagent.ts

export function buildForkedMessages(
  directive: string,
  assistantMessage: AssistantMessage,
): MessageType[] {
  // 1. 克隆完整的父 Assistant 消息（包含所有 tool_use 块）
  const fullAssistantMessage = cloneAssistantMessage(assistantMessage);
  
  // 2. 收集所有 tool_use 块
  const toolUseBlocks = assistantMessage.message.content.filter(
    (block): block is ToolUseBlock => block.type === 'tool_use'
  );
  
  // 3. 为每个 tool_use 创建占位符 tool_result
  const toolResultBlocks: ToolResultBlock[] = toolUseBlocks.map(block => ({
    type: 'tool_result',
    tool_use_id: block.id,
    content: [{ 
      type: 'text', 
      text: 'Fork started — processing in background' 
    }],
  }));
  
  // 4. 构建包含指令的用户消息
  const toolResultMessage = createUserMessage({
    content: [
      ...toolResultBlocks,
      { 
        type: 'text', 
        text: buildChildMessage(directive) 
      },
    ],
  });
  
  return [fullAssistantMessage, toolResultMessage];
}

function buildChildMessage(directive: string): string {
  return `You've been forked from the parent conversation to handle a task in parallel.

Parent's directive:
${directive}

Execute this task to the best of your ability. When complete, your results will be returned to the parent conversation.`;
}
```

### 6.2 Agent 执行核心

```typescript
// tools/AgentTool/runAgent.ts

export async function* runAgent({
  agentDefinition,
  promptMessages,
  toolUseContext,
  canUseTool,
  isAsync,
  querySource,
  model,
  maxTurns,
  availableTools,
  allowedTools,
  override,
  worktreePath,
  description,
}: RunAgentParams): AsyncGenerator<AgentMessage, AgentResult, unknown> {
  const agentId = generateAgentId();
  
  // 1. 初始化 Agent MCP 服务器
  const mcpServers = await initializeAgentMcpServers(agentDefinition.mcpServers);
  
  // 2. 设置文件状态缓存
  const fileStateCache = cloneFileStateCache(toolUseContext.fileStateCache);
  
  // 3. 构建 Agent 上下文
  const agentContext: SubagentContext = {
    agentId,
    parentSessionId: toolUseContext.sessionId,
    agentType: 'subagent',
    subagentName: agentDefinition.agentType,
    isBuiltIn: isBuiltInAgent(agentDefinition),
    invokingRequestId: toolUseContext.requestId,
    invocationKind: 'spawn',
  };
  
  // 4. 运行查询循环
  yield* runWithAgentContext(agentContext, async function* () {
    const result = await runQueryLoop({
      agentDefinition,
      promptMessages,
      toolUseContext: {
        ...toolUseContext,
        mcp: { tools: mcpServers },
        fileStateCache,
      },
      canUseTool,
      model,
      maxTurns,
      availableTools,
      allowedTools,
      querySource,
      override,
    });
    
    return result;
  });
}
```

---

## 七、上下文管理模式

### 7.1 使用 AsyncLocalStorage 跟踪 Agent 上下文

```typescript
// utils/agentContext.ts

import { AsyncLocalStorage } from 'async_hooks';

export type SubagentContext = {
  agentId: string;
  parentSessionId?: string;
  agentType: 'subagent';
  subagentName?: string;
  isBuiltIn?: boolean;
  invokingRequestId?: string;
  invocationKind?: 'spawn' | 'resume';
};

export type MainAgentContext = {
  agentType: 'main';
  sessionId: string;
};

export type AgentContext = SubagentContext | MainAgentContext;

const agentContextStorage = new AsyncLocalStorage<AgentContext>();

/**
 * 在 Agent 上下文中运行函数
 */
export function runWithAgentContext<T>(
  context: AgentContext,
  fn: () => T,
): T {
  return agentContextStorage.run(context, fn);
}

/**
 * 获取当前 Agent 上下文
 */
export function getAgentContext(): AgentContext | undefined {
  return agentContextStorage.getStore();
}

/**
 * 检查当前是否在 Subagent 中
 */
export function isInSubagent(): boolean {
  const context = getAgentContext();
  return context?.agentType === 'subagent';
}

/**
 * 获取当前 Agent ID
 */
export function getCurrentAgentId(): string | undefined {
  const context = getAgentContext();
  return context?.agentType === 'subagent' ? context.agentId : undefined;
}
```

### 7.2 Memoized 上下文加载

```typescript
// context.ts

import { memoize } from './utils/memoize';

/**
 * 用户上下文 - 跨轮次缓存
 */
export const getUserContext = memoize(async (): Promise<Record<string, string>> => {
  const [memoryFiles, claudeMdFiles] = await Promise.all([
    getMemoryFiles(),
    getClaudeMdFiles(),
  ]);
  
  const filteredMemory = filterInjectedMemoryFiles(memoryFiles);
  const claudeMd = getClaudeMds(filteredMemory, claudeMdFiles);
  
  return {
    ...(claudeMd && { claudeMd }),
    currentDate: `Today's date is ${getLocalISODate()}.`,
  };
});

/**
 * 系统上下文 - 跨轮次缓存
 */
export const getSystemContext = memoize(async (): Promise<Record<string, string>> => {
  const gitStatus = await getGitStatus();
  const injection = getSystemPromptInjection();
  
  return {
    ...(gitStatus && { gitStatus }),
    ...(injection && { cacheBreaker: `[CACHE_BREAKER: ${injection}]` }),
  };
});

/**
 * 清除上下文缓存（当相关文件变化时调用）
 */
export function clearContextCache(): void {
  getUserContext.clear();
  getSystemContext.clear();
}
```

---

## 八、缓存控制模式

### 8.1 系统提示词分割与缓存标记

```typescript
// utils/api.ts

export function splitSysPromptPrefix(
  systemPrompt: string[],
  hasMcpTools: boolean,
): { prefixBlocks: string[]; remainingBlocks: string[] } {
  // 如果有 MCP 工具，无法使用全局缓存
  if (hasMcpTools) {
    return {
      prefixBlocks: [],
      remainingBlocks: systemPrompt,
    };
  }
  
  const boundaryIndex = systemPrompt.indexOf(SYSTEM_PROMPT_DYNAMIC_BOUNDARY);
  
  if (boundaryIndex === -1) {
    return {
      prefixBlocks: systemPrompt,
      remainingBlocks: [],
    };
  }
  
  return {
    prefixBlocks: systemPrompt.slice(0, boundaryIndex),
    remainingBlocks: systemPrompt.slice(boundaryIndex + 1),
  };
}

/**
 * 为消息添加缓存控制标记
 */
export function addCacheBreakpoints(
  messages: Message[],
  options: { scope?: CacheScope; ttl?: '1h' },
): Message[] {
  if (messages.length === 0) return messages;
  
  // 为最后一条用户消息添加缓存标记
  const lastUserMessageIndex = findLastIndex(
    messages,
    m => m.type === 'user' && !m.isVirtual
  );
  
  if (lastUserMessageIndex === -1) return messages;
  
  const message = messages[lastUserMessageIndex];
  
  return messages.map((m, i) => {
    if (i !== lastUserMessageIndex) return m;
    
    return {
      ...m,
      cache_control: {
        type: 'ephemeral',
        ...(options.ttl && { ttl: options.ttl }),
        ...(options.scope && { scope: options.scope }),
      },
    };
  });
}
```

### 8.2 Section 缓存管理

```typescript
// constants/systemPromptSections.ts

type SectionCache<T> = {
  value: T;
  timestamp: number;
};

const sectionCache = new Map<string, SectionCache<unknown>>();

/**
 * 创建可缓存的 Section
 */
export function systemPromptSection<T>(
  name: string,
  compute: () => Promise<T>,
): SystemPromptSection<T> {
  return {
    name,
    async resolve(): Promise<T> {
      const cached = sectionCache.get(name);
      
      if (cached) {
        return cached.value as T;
      }
      
      const value = await compute();
      sectionCache.set(name, { value, timestamp: Date.now() });
      return value;
    },
    clearCache(): void {
      sectionCache.delete(name);
    },
  };
}

/**
 * 创建不缓存的 Section（每轮重新计算）
 */
export function DANGEROUS_uncachedSystemPromptSection<T>(
  name: string,
  compute: () => Promise<T>,
  reason: string,
): SystemPromptSection<T> {
  return {
    name,
    async resolve(): Promise<T> {
      return compute();
    },
    clearCache(): void {
      // No-op
    },
  };
}

/**
 * 解析所有 Section
 */
export async function resolveSystemPromptSections(
  sections: SystemPromptSection<unknown>[],
): Promise<unknown[]> {
  const results = await Promise.all(sections.map(s => s.resolve()));
  return results.filter(Boolean);
}

/**
 * 清除所有 Section 缓存
 */
export function clearSystemPromptSections(): void {
  sectionCache.clear();
}
```

---

## 九、安全与防护模式

### 9.1 Prompt Injection 检测

```typescript
// utils/security/promptInjection.ts

const SUSPICIOUS_PATTERNS = [
  /ignore\s+(?:previous|above|earlier)\s+instructions/i,
  /disregard\s+(?:the\s+)?system\s+prompt/i,
  /system\s*:\s*you\s+are\s+now/i,
  /\[system\s*:\s*admin\s+mode\]/i,
];

export function detectPromptInjection(content: string): boolean {
  return SUSPICIOUS_PATTERNS.some(pattern => pattern.test(content));
}

// 在工具结果处理中使用
export function sanitizeToolResult(content: string): string {
  if (detectPromptInjection(content)) {
    // 标记可疑内容但不过滤（让模型自己判断）
    return `[⚠️ Suspicious content detected - possible prompt injection attempt]\n\n${content}`;
  }
  return content;
}
```

### 9.2 Unicode 字符清理

```typescript
// utils/sanitize.ts

const DANGEROUS_UNICODE_RANGES = [
  /[\u200B-\u200F]/g,  // Zero-width characters
  /[\u2060-\u2064]/g,  // Word joiners
  /[\uFEFF]/g,         // BOM
  /[\u180E]/g,         // Mongolian vowel separator
];

export function sanitizeHiddenUnicode(text: string): string {
  return DANGEROUS_UNICODE_RANGES.reduce(
    (acc, pattern) => acc.replace(pattern, ''),
    text
  );
}

// 在解析用户输入时使用
export function parseUserInput(input: string): string {
  return sanitizeHiddenUnicode(input.trim());
}
```

### 9.3 环境变量隔离

```typescript
// utils/subprocessEnv.ts

/**
 * 获取安全的子进程环境变量
 * 移除敏感信息以防止 prompt injection 泄露
 */
export function getSafeSubprocessEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  
  // 移除敏感的环境变量
  const sensitiveKeys = [
    'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY',
    'GITHUB_TOKEN',
    'AWS_SECRET_ACCESS_KEY',
    // ... 其他敏感 key
  ];
  
  for (const key of sensitiveKeys) {
    delete env[key];
  }
  
  // 添加安全标记
  env.CLAUDE_CODE_SAFE_ENV = 'true';
  
  return env;
}
```

---

## 十、测试模式

### 10.1 测试系统提示词构建

```typescript
// __tests__/systemPrompt.test.ts

import { buildEffectiveSystemPrompt } from '../utils/systemPrompt';

describe('buildEffectiveSystemPrompt', () => {
  const defaultPrompt = ['Default system prompt'] as SystemPrompt;
  
  it('should use overrideSystemPrompt when provided', () => {
    const result = buildEffectiveSystemPrompt({
      defaultSystemPrompt: defaultPrompt,
      overrideSystemPrompt: 'Override prompt',
      toolUseContext: mockToolUseContext(),
    });
    
    expect(result).toEqual(['Override prompt']);
  });
  
  it('should use agent system prompt when available', () => {
    const agentPrompt = 'Agent specific prompt';
    const agentDef = createMockAgent({ getSystemPrompt: () => agentPrompt });
    
    const result = buildEffectiveSystemPrompt({
      defaultSystemPrompt: defaultPrompt,
      mainThreadAgentDefinition: agentDef,
      toolUseContext: mockToolUseContext(),
    });
    
    expect(result).toEqual([agentPrompt]);
  });
  
  it('should append system prompt in proactive mode', () => {
    const agentPrompt = 'Agent specific prompt';
    const agentDef = createMockAgent({ getSystemPrompt: () => agentPrompt });
    
    mockProactiveMode(true);
    
    const result = buildEffectiveSystemPrompt({
      defaultSystemPrompt: defaultPrompt,
      mainThreadAgentDefinition: agentDef,
      toolUseContext: mockToolUseContext(),
    });
    
    expect(result[0]).toBe('Default system prompt');
    expect(result[1]).toContain('Agent specific prompt');
  });
});
```

### 10.2 测试消息标准化

```typescript
// __tests__/messages.test.ts

import { normalizeMessagesForAPI, createUserMessage, createAssistantMessage } from '../utils/messages';

describe('normalizeMessagesForAPI', () => {
  it('should merge consecutive user messages', () => {
    const messages = [
      createUserMessage({ content: 'Hello' }),
      createUserMessage({ content: 'World' }),
    ];
    
    const result = normalizeMessagesForAPI(messages);
    
    expect(result).toHaveLength(1);
    expect(result[0].content).toHaveLength(2);
  });
  
  it('should filter out virtual messages', () => {
    const messages = [
      createUserMessage({ content: 'Real message' }),
      createUserMessage({ content: 'Virtual message', isVirtual: true }),
    ];
    
    const result = normalizeMessagesForAPI(messages);
    
    expect(result).toHaveLength(1);
    expect(result[0].content).toBe('Real message');
  });
  
  it('should reorder attachments to follow relevant messages', () => {
    const messages = [
      createUserMessage({ content: 'Query' }),
      { type: 'attachment', source: 'skill', content: 'Skill info' },
      createAssistantMessage({ content: [{ type: 'text', text: 'Response' }] }),
    ];
    
    const result = normalizeMessagesForAPI(messages);
    
    // Attachment 应该在 assistant message 之后
    expect(result[2].type).toBe('attachment');
  });
});
```

---

*文档结束*
