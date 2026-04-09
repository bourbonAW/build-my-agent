# Claude Code Skill 处理架构深度解析

本文档深入分析 Claude Code 中 Skill（技能）系统的完整处理逻辑，包括管理、发现、加载、使用等核心环节。

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Claude Code Skill 架构                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Skill 来源  │    │  Skill 发现  │    │  Skill 加载  │    │  Skill 使用  │  │
│  ├─────────────┤    ├─────────────┤    ├─────────────┤    ├─────────────┤  │
│  │ • Bundled   │───▶│ • 文件扫描   │───▶│ • 解析 Front │───▶│ • SkillTool  │  │
│  │ • 文件系统   │    │ • 动态发现   │    │ • 创建命令   │    │ • 子代理执行 │  │
│  │ • Plugin    │    │ • 条件激活   │    │ • 注册 hooks │    │ • 权限检查   │  │
│  │ • MCP       │    │ • 缓存管理   │    │ • 去重合并   │    │ • 上下文修改 │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. Skill 来源 (Sources)

Claude Code 支持多种 Skill 来源，按优先级排列：

### 2.1 Bundled Skills（内置技能）
- **位置**: `src/skills/bundled/`
- **注册方式**: 程序启动时通过 `initBundledSkills()` 注册
- **特点**: 
  - 编译进 CLI 二进制文件
  - 通过 `registerBundledSkill()` 函数注册
  - 支持 feature flag 条件注册
  - 可携带附加文件（提取到临时目录）

```typescript
// src/skills/bundled/index.ts
export function initBundledSkills(): void {
  registerUpdateConfigSkill()
  registerKeybindingsSkill()
  registerVerifySkill()
  // ... 更多技能
  if (feature('KAIROS')) {
    const { registerDreamSkill } = require('./dream.js')
    registerDreamSkill()
  }
}
```

### 2.2 文件系统 Skills
- **位置**: `.claude/skills/` 目录
- **格式**: `skill-name/SKILL.md`
- **层级**: 
  - Managed: `~/.claude/.claude/skills/` (policy 设置)
  - User: `~/.claude/skills/` (用户设置)
  - Project: `<project>/.claude/skills/` (项目设置)
  - Additional: `--add-dir` 指定的目录

### 2.3 Legacy Commands
- **位置**: `.claude/commands/` 目录
- **格式**: 
  - `command-name.md` (单文件)
  - `command-name/SKILL.md` (目录格式)
- **状态**: 已弃用，向后兼容

### 2.4 Plugin Skills
- **来源**: 通过插件市场安装的插件
- **加载**: 通过 `loadPluginCommands.ts` 加载

### 2.5 MCP Skills
- **来源**: Model Context Protocol 服务器
- **特点**: 远程技能，声明式 markdown

## 3. Skill 发现 (Discovery)

### 3.1 启动时加载
```typescript
// src/skills/loadSkillsDir.ts
export const getSkillDirCommands = memoize(async (cwd: string): Promise<Command[]> => {
  // 并行加载所有来源
  const [
    managedSkills,
    userSkills,
    projectSkillsNested,
    additionalSkillsNested,
    legacyCommands,
  ] = await Promise.all([
    loadSkillsFromSkillsDir(managedSkillsDir, 'policySettings'),
    loadSkillsFromSkillsDir(userSkillsDir, 'userSettings'),
    // ...
  ])
  // 去重、合并、处理条件技能
})
```

### 3.2 动态发现
在文件操作过程中动态发现嵌套的技能目录：

```typescript
// src/skills/loadSkillsDir.ts
export async function discoverSkillDirsForPaths(
  filePaths: string[],
  cwd: string,
): Promise<string[]> {
  // 从文件路径向上遍历到 cwd
  // 发现 `.claude/skills` 目录
  // 检查 gitignore 排除
  // 按深度排序（最深的优先）
}
```

### 3.3 条件技能激活
支持基于文件路径的条件技能：

```yaml
# SKILL.md frontmatter
paths:
  - "src/**/*.ts"
  - "tests/**/*"
```

```typescript
export function activateConditionalSkillsForPaths(
  filePaths: string[],
  cwd: string,
): string[] {
  // 使用 ignore 库进行 gitignore 风格匹配
  // 匹配的技能移至 dynamicSkills
}
```

## 4. Skill 加载 (Loading)

### 4.1 文件解析流程

```
SKILL.md 文件
    ↓
parseFrontmatter() ──▶ 提取元数据 + 内容
    ↓
parseSkillFrontmatterFields() ──▶ 解析各字段
    ↓
createSkillCommand() ──▶ 创建 Command 对象
    ↓
注册到命令系统
```

### 4.2 Frontmatter 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 显示名称 |
| `description` | string | 描述 |
| `allowed-tools` | string[] | 允许的工具 |
| `model` | string | 模型覆盖 |
| `effort` | string | 努力级别 |
| `context` | 'fork' \| 'inline' | 执行上下文 |
| `agent` | string | Fork 时的代理类型 |
| `user-invocable` | boolean | 用户是否可直接调用 |
| `disable-model-invocation` | boolean | 禁止模型调用 |
| `paths` | string[] | 条件路径模式 |
| `hooks` | object | 钩子设置 |
| `arguments` | string \| string[] | 参数名 |
| `argument-hint` | string | 参数提示 |
| `when_to_use` | string | 使用时机说明 |

### 4.3 变量替换

Skill 内容支持多种变量替换：

```typescript
// src/skills/loadSkillsDir.ts
async getPromptForCommand(args, toolUseContext) {
  // 1. 参数替换 $ARGUMENTS
  finalContent = substituteArguments(finalContent, args, ...)
  
  // 2. Skill 目录替换
  finalContent = finalContent.replace(/\$\{CLAUDE_SKILL_DIR\}/g, skillDir)
  
  // 3. Session ID 替换
  finalContent = finalContent.replace(/\$\{CLAUDE_SESSION_ID\}/g, getSessionId())
  
  // 4. Shell 命令执行 (!`command`)
  finalContent = await executeShellCommandsInPrompt(finalContent, ...)
}
```

## 5. Skill 使用 (Usage)

### 5.1 SkillTool - 核心执行工具

```typescript
// src/tools/SkillTool/SkillTool.ts
export const SkillTool = buildTool({
  name: SKILL_TOOL_NAME,
  
  // 1. 输入验证
  async validateInput({ skill }, context): Promise<ValidationResult> {
    // 检查技能格式
    // 检查技能存在性
    // 检查 disableModelInvocation
    // 检查是否为 prompt 类型
  },
  
  // 2. 权限检查
  async checkPermissions({ skill, args }, context): Promise<PermissionDecision> {
    // 检查 deny 规则
    // 检查 allow 规则
    // 自动允许安全属性技能
    // 返回用户确认建议
  },
  
  // 3. 执行
  async call({ skill, args }, context, ...): Promise<ToolResult<Output>> {
    // 处理远程技能
    // 处理 fork 执行
    // 处理 inline 执行
    // 返回结果和上下文修改
  }
})
```

### 5.2 执行模式

#### Inline 模式（默认）
- Skill 内容直接展开到当前对话
- 继承主对话的上下文和工具
- 支持 allowedTools 扩展

```typescript
// Skill 内容作为 user message 注入
const messages = [
  createUserMessage({ content: metadata }),
  createUserMessage({ content: mainMessageContent, isMeta: true }),
  ...attachmentMessages,
]
```

#### Fork 模式
- Skill 在子代理中执行
- 独立的 token 预算和上下文
- 支持 effort 级别覆盖

```typescript
async function executeForkedSkill(...) {
  const agentId = createAgentId()
  
  // 准备 fork 的上下文
  const { modifiedGetAppState, baseAgent, promptMessages } = 
    await prepareForkedCommandContext(command, args, context)
  
  // 运行子代理
  for await (const message of runAgent({
    agentDefinition,
    promptMessages,
    toolUseContext: { ...context, getAppState: modifiedGetAppState },
    // ...
  })) {
    // 收集消息、报告进度
  }
}
```

### 5.3 权限系统

```typescript
// 权限检查流程
async checkPermissions({ skill, args }, context) {
  // 1. 检查 deny 规则（优先）
  const denyRules = getRuleByContentsForTool(permissionContext, SkillTool, 'deny')
  for (const [ruleContent, rule] of denyRules) {
    if (ruleMatches(ruleContent)) {
      return { behavior: 'deny', ... }
    }
  }
  
  // 2. 检查 allow 规则
  const allowRules = getRuleByContentsForTool(permissionContext, SkillTool, 'allow')
  for (const [ruleContent, rule] of allowRules) {
    if (ruleMatches(ruleContent)) {
      return { behavior: 'allow', ... }
    }
  }
  
  // 3. 自动允许安全属性技能
  if (skillHasOnlySafeProperties(commandObj)) {
    return { behavior: 'allow', ... }
  }
  
  // 4. 默认：询问用户
  return { behavior: 'ask', suggestions: [...], ... }
}
```

### 5.4 安全属性白名单

```typescript
const SAFE_SKILL_PROPERTIES = new Set([
  'type', 'progressMessage', 'contentLength', 'argNames',
  'model', 'effort', 'source', 'pluginInfo',
  'disableNonInteractive', 'skillRoot', 'context', 'agent',
  'getPromptForCommand', 'frontmatterKeys',
  'name', 'description', 'hasUserSpecifiedDescription',
  'isEnabled', 'isHidden', 'aliases', 'isMcp',
  // ... 更多安全属性
])
```

## 6. 状态管理

### 6.1 全局状态 (bootstrap/state.ts)

```typescript
type State = {
  // ... 其他状态
  
  // 追踪已调用的技能（用于 compaction 保留）
  invokedSkills: Map<string, {
    skillName: string
    skillPath: string
    content: string
    invokedAt: number
    agentId: string | null
  }>
}
```

### 6.2 技能调用追踪

```typescript
// 添加调用的技能
export function addInvokedSkill(
  skillName: string,
  skillPath: string,
  content: string,
  agentId: string | null,
): void {
  const key = `${agentId ?? ''}:${skillName}`
  STATE.invokedSkills.set(key, {
    skillName,
    skillPath,
    content,
    invokedAt: Date.now(),
    agentId,
  })
}

// 清除特定代理的技能
export function clearInvokedSkillsForAgent(agentId: string): void {
  for (const [key, value] of STATE.invokedSkills) {
    if (value.agentId === agentId) {
      STATE.invokedSkills.delete(key)
    }
  }
}
```

## 7. 命令系统集成

### 7.1 命令类型定义

```typescript
// src/types/command.ts
type PromptCommand = {
  type: 'prompt'
  progressMessage: string
  contentLength: number
  argNames?: string[]
  allowedTools?: string[]
  model?: string
  source: SettingSource | 'builtin' | 'mcp' | 'plugin' | 'bundled'
  context?: 'inline' | 'fork'
  agent?: string
  effort?: EffortValue
  paths?: string[]
  hooks?: HooksSettings
  skillRoot?: string
  userInvocable?: boolean
  disableModelInvocation?: boolean
  getPromptForCommand(args: string, context: ToolUseContext): Promise<ContentBlockParam[]>
}
```

### 7.2 命令加载优先级

```typescript
// src/commands.ts - loadAllCommands
const loadAllCommands = memoize(async (cwd: string): Promise<Command[]> => {
  const [
    { skillDirCommands, pluginSkills, bundledSkills, builtinPluginSkills },
    pluginCommands,
    workflowCommands,
  ] = await Promise.all([
    getSkills(cwd),
    getPluginCommands(),
    getWorkflowCommands ? getWorkflowCommands(cwd) : Promise.resolve([]),
  ])

  return [
    ...bundledSkills,        // 1. 内置技能
    ...builtinPluginSkills,  // 2. 内置插件技能
    ...skillDirCommands,     // 3. 文件系统技能
    ...workflowCommands,     // 4. 工作流命令
    ...pluginCommands,       // 5. 插件命令
    ...pluginSkills,         // 6. 插件技能
    ...COMMANDS(),           // 7. 内置命令
  ]
})
```

## 8. Hooks 系统

Skill 可以注册 hooks，在特定事件时执行：

```typescript
// src/utils/hooks/registerSkillHooks.ts
export function registerSkillHooks(
  setAppState: SetAppStateFn,
  sessionId: string,
  hooks: HooksSettings,
  skillName: string,
  skillRoot: string | undefined,
): void {
  // 解析 hook 配置
  // 注册到全局 hooks 系统
  // 支持多种事件类型
}
```

## 9. 缓存与性能

### 9.1 缓存策略

| 缓存 | 位置 | 说明 |
|------|------|------|
| `getSkillDirCommands` | `loadSkillsDir.ts` | Memoized，按 cwd 缓存 |
| `getCommands` | `commands.ts` | Memoized，但可用性检查每次执行 |
| `getSkillToolCommands` | `commands.ts` | Memoized 技能工具命令 |
| Frontmatter 解析 | 运行时 | 按需解析，无持久缓存 |

### 9.2 缓存清除

```typescript
export function clearCommandsCache(): void {
  clearCommandMemoizationCaches()
  clearPluginCommandCache()
  clearPluginSkillsCache()
  clearSkillCaches()
}

export function clearSkillCaches(): void {
  getSkillDirCommands.cache?.clear?.()
  loadMarkdownFilesForSubdir.cache?.clear?.()
  conditionalSkills.clear()
  activatedConditionalSkillNames.clear()
}
```

## 10. 远程技能 (实验性)

```typescript
// src/tools/SkillTool/SkillTool.ts
async function executeRemoteSkill(
  slug: string,
  commandName: string,
  parentMessage: AssistantMessage,
  context: ToolUseContext,
): Promise<ToolResult<Output>> {
  // 1. 获取已发现的远程技能元数据
  const meta = getDiscoveredRemoteSkill(slug)
  
  // 2. 从 AKI/GCS 加载 SKILL.md（带本地缓存）
  const loadResult = await loadRemoteSkill(slug, meta.url)
  
  // 3. 直接注入内容作为 user message
  // 远程技能是声明式 markdown，无需 !command / $ARGUMENTS 展开
}
```

## 11. 关键设计模式

### 11.1 懒加载 (Lazy Loading)
```typescript
// 使用动态 import 避免循环依赖
const remoteSkillModules = feature('EXPERIMENTAL_SKILL_SEARCH')
  ? {
      ...(require('../../services/skillSearch/remoteSkillState.js')),
      ...(require('../../services/skillSearch/remoteSkillLoader.js')),
    }
  : null
```

### 11.2 特征标志 (Feature Flags)
```typescript
// 使用 bun:bundle 进行死代码消除
const cronTools = feature('AGENT_TRIGGERS')
  ? [
      require('./tools/ScheduleCronTool/CronCreateTool.js').CronCreateTool,
      // ...
    ]
  : []
```

### 11.3 信号系统 (Signals)
```typescript
// 动态技能加载通知
const skillsLoaded = createSignal()

export function onDynamicSkillsLoaded(callback: () => void): () => void {
  return skillsLoaded.subscribe(() => {
    try { callback() } catch (error) { logError(error) }
  })
}
```

## 12. 安全考虑

1. **路径遍历保护**: 所有文件路径经过规范化处理
2. **Gitignore 检查**: 动态发现的技能目录检查是否在 gitignore 中
3. **权限白名单**: 只有安全属性的技能自动通过权限
4. **Shell 命令限制**: MCP 技能禁止执行内联 shell 命令
5. **文件提取安全**: 使用 O_NOFOLLOW | O_EXCL 防止符号链接攻击

## 13. 总结

Claude Code 的 Skill 系统是一个精心设计的多层级架构：

- **灵活性**: 支持多种来源（内置、文件系统、插件、MCP）
- **动态性**: 运行时动态发现和激活条件技能
- **安全性**: 多层权限检查和安全属性白名单
- **性能**: 智能缓存和懒加载策略
- **可扩展性**: Hooks 系统和特征标志支持功能扩展

这个架构使得 Claude Code 能够在一个统一的框架下管理从简单提示到复杂工作流的各种能力扩展。
