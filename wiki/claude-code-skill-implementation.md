# Claude Code Skill 实现细节

## 1. Skill 注册代码

### 1.1 Bundled Skill 注册

```typescript
// src/skills/bundledSkills.ts
export type BundledSkillDefinition = {
  name: string
  description: string
  aliases?: string[]
  whenToUse?: string
  argumentHint?: string
  allowedTools?: string[]
  model?: string
  disableModelInvocation?: boolean
  userInvocable?: boolean
  isEnabled?: () => boolean
  hooks?: HooksSettings
  context?: 'inline' | 'fork'
  agent?: string
  files?: Record<string, string>  // 附加文件
  getPromptForCommand: (
    args: string,
    context: ToolUseContext,
  ) => Promise<ContentBlockParam[]>
}

const bundledSkills: Command[] = []

export function registerBundledSkill(definition: BundledSkillDefinition): void {
  const { files } = definition
  
  let skillRoot: string | undefined
  let getPromptForCommand = definition.getPromptForCommand
  
  // 如果有附加文件，延迟提取到磁盘
  if (files && Object.keys(files).length > 0) {
    skillRoot = getBundledSkillExtractDir(definition.name)
    let extractionPromise: Promise<string | null> | undefined
    const inner = definition.getPromptForCommand
    
    getPromptForCommand = async (args, ctx) => {
      extractionPromise ??= extractBundledSkillFiles(definition.name, files)
      const extractedDir = await extractionPromise
      const blocks = await inner(args, ctx)
      if (extractedDir === null) return blocks
      return prependBaseDir(blocks, extractedDir)
    }
  }
  
  const command: Command = {
    type: 'prompt',
    name: definition.name,
    description: definition.description,
    // ... 其他属性
    source: 'bundled',
    loadedFrom: 'bundled',
    skillRoot,
    getPromptForCommand,
  }
  bundledSkills.push(command)
}
```

### 1.2 使用示例

```typescript
// src/skills/bundled/commit.ts
export function registerCommitSkill(): void {
  registerBundledSkill({
    name: 'commit',
    description: 'Create a git commit with an AI-generated message',
    whenToUse: 'Use when you have staged changes and want to commit them',
    allowedTools: ['Bash', 'Read', 'Glob'],
    model: 'haiku',  // 使用轻量级模型
    async getPromptForCommand(args, context) {
      return [{
        type: 'text',
        text: `Analyze the staged changes and create a commit message...`
      }]
    }
  })
}
```

## 2. Skill 文件加载代码

```typescript
// src/skills/loadSkillsDir.ts
async function loadSkillsFromSkillsDir(
  basePath: string,
  source: SettingSource,
): Promise<SkillWithPath[]> {
  const fs = getFsImplementation()
  
  let entries
  try {
    entries = await fs.readdir(basePath)
  } catch (e) {
    if (!isFsInaccessible(e)) logError(e)
    return []
  }
  
  const results = await Promise.all(
    entries.map(async (entry): Promise<SkillWithPath | null> => {
      try {
        // 只支持目录格式: skill-name/SKILL.md
        if (!entry.isDirectory() && !entry.isSymbolicLink()) {
          return null
        }
        
        const skillDirPath = join(basePath, entry.name)
        const skillFilePath = join(skillDirPath, 'SKILL.md')
        
        let content: string
        try {
          content = await fs.readFile(skillFilePath, { encoding: 'utf-8' })
        } catch (e) {
          if (!isENOENT(e)) {
            logForDebugging(`[skills] failed to read ${skillFilePath}: ${e}`)
          }
          return null
        }
        
        const { frontmatter, content: markdownContent } = parseFrontmatter(
          content,
          skillFilePath,
        )
        
        const skillName = entry.name
        const parsed = parseSkillFrontmatterFields(frontmatter, markdownContent, skillName)
        const paths = parseSkillPaths(frontmatter)
        
        return {
          skill: createSkillCommand({
            ...parsed,
            skillName,
            markdownContent,
            source,
            baseDir: skillDirPath,
            loadedFrom: 'skills',
            paths,
          }),
          filePath: skillFilePath,
        }
      } catch (error) {
        logError(error)
        return null
      }
    }),
  )
  
  return results.filter((r): r is SkillWithPath => r !== null)
}
```

## 3. SkillTool 核心实现

```typescript
// src/tools/SkillTool/SkillTool.ts
export const SkillTool: Tool<InputSchema, Output, Progress> = buildTool({
  name: SKILL_TOOL_NAME,
  searchHint: 'invoke a slash-command skill',
  maxResultSizeChars: 100_000,
  
  get inputSchema(): InputSchema {
    return inputSchema()
  },
  get outputSchema(): OutputSchema {
    return outputSchema()
  },
  
  description: async ({ skill }) => `Execute skill: ${skill}`,
  prompt: async () => getPrompt(getProjectRoot()),
  
  // 用于自动分类器
  toAutoClassifierInput: ({ skill }) => skill ?? '',
  
  // 输入验证
  async validateInput({ skill }, context): Promise<ValidationResult> {
    const trimmed = skill.trim()
    if (!trimmed) {
      return { result: false, message: `Invalid skill format: ${skill}`, errorCode: 1 }
    }
    
    // 去除前导斜杠
    const commandName = trimmed.startsWith('/') ? trimmed.substring(1) : trimmed
    
    // 获取所有命令（包括 MCP 技能）
    const commands = await getAllCommands(context)
    
    // 查找命令
    const foundCommand = findCommand(normalizedCommandName, commands)
    if (!foundCommand) {
      return { result: false, message: `Unknown skill: ${normalizedCommandName}`, errorCode: 2 }
    }
    
    // 检查是否禁用模型调用
    if (foundCommand.disableModelInvocation) {
      return { result: false, message: `Skill ${normalizedCommandName} cannot be used...`, errorCode: 4 }
    }
    
    // 检查是否为 prompt 类型
    if (foundCommand.type !== 'prompt') {
      return { result: false, message: `Skill ${normalizedCommandName} is not a prompt-based skill`, errorCode: 5 }
    }
    
    return { result: true }
  },
  
  // 权限检查
  async checkPermissions({ skill, args }, context): Promise<PermissionDecision> {
    const commandName = skill.trim().startsWith('/') 
      ? skill.trim().substring(1) 
      : skill.trim()
    
    const appState = context.getAppState()
    const permissionContext = appState.toolPermissionContext
    
    // 获取命令对象作为元数据
    const commands = await getAllCommands(context)
    const commandObj = findCommand(commandName, commands)
    
    // 检查 deny 规则
    const denyRules = getRuleByContentsForTool(permissionContext, SkillTool as Tool, 'deny')
    for (const [ruleContent, rule] of denyRules.entries()) {
      if (ruleMatches(ruleContent, commandName)) {
        return { behavior: 'deny', message: 'Skill execution blocked by permission rules', ... }
      }
    }
    
    // 检查 allow 规则
    const allowRules = getRuleByContentsForTool(permissionContext, SkillTool as Tool, 'allow')
    for (const [ruleContent, rule] of allowRules.entries()) {
      if (ruleMatches(ruleContent, commandName)) {
        return { behavior: 'allow', updatedInput: { skill, args }, ... }
      }
    }
    
    // 自动允许安全属性技能
    if (commandObj?.type === 'prompt' && skillHasOnlySafeProperties(commandObj)) {
      return { behavior: 'allow', updatedInput: { skill, args }, ... }
    }
    
    // 默认询问用户
    return {
      behavior: 'ask',
      message: `Execute skill: ${commandName}`,
      suggestions: [
        { type: 'addRules', rules: [{ toolName: SKILL_TOOL_NAME, ruleContent: commandName }], behavior: 'allow', destination: 'localSettings' },
        { type: 'addRules', rules: [{ toolName: SKILL_TOOL_NAME, ruleContent: `${commandName}:*` }], behavior: 'allow', destination: 'localSettings' },
      ],
      metadata: commandObj ? { command: commandObj } : undefined,
    }
  },
  
  // 执行
  async call({ skill, args }, context, canUseTool, parentMessage, onProgress?): Promise<ToolResult<Output>> {
    const commandName = skill.trim().startsWith('/') ? skill.trim().substring(1) : skill.trim()
    
    const commands = await getAllCommands(context)
    const command = findCommand(commandName, commands)
    
    // 记录技能使用
    recordSkillUsage(commandName)
    
    // 检查是否为 fork 执行
    if (command?.type === 'prompt' && command.context === 'fork') {
      return executeForkedSkill(command, commandName, args, context, canUseTool, parentMessage, onProgress)
    }
    
    // Inline 执行
    const { processPromptSlashCommand } = await import('src/utils/processUserInput/processSlashCommand.js')
    const processedCommand = await processPromptSlashCommand(commandName, args || '', commands, context)
    
    if (!processedCommand.shouldQuery) {
      throw new Error('Command processing failed')
    }
    
    // 提取元数据
    const allowedTools = processedCommand.allowedTools || []
    const model = processedCommand.model
    const effort = command?.type === 'prompt' ? command.effort : undefined
    
    // 获取 tool use ID
    const toolUseID = getToolUseIDFromParentMessage(parentMessage, SKILL_TOOL_NAME)
    
    // 标记消息
    const newMessages = tagMessagesWithToolUseID(
      processedCommand.messages.filter((m) => /* ... */),
      toolUseID,
    )
    
    // 返回结果和上下文修改
    return {
      data: { success: true, commandName, allowedTools: allowedTools.length > 0 ? allowedTools : undefined, model },
      newMessages,
      contextModifier(ctx) {
        let modifiedContext = ctx
        
        // 更新允许的工具
        if (allowedTools.length > 0) {
          const previousGetAppState = modifiedContext.getAppState
          modifiedContext = {
            ...modifiedContext,
            getAppState() {
              const appState = previousGetAppState()
              return {
                ...appState,
                toolPermissionContext: {
                  ...appState.toolPermissionContext,
                  alwaysAllowRules: {
                    ...appState.toolPermissionContext.alwaysAllowRules,
                    command: [...new Set([...(appState.toolPermissionContext.alwaysAllowRules.command || []), ...allowedTools])],
                  },
                },
              }
            },
          }
        }
        
        // 覆盖模型
        if (model) {
          modifiedContext = {
            ...modifiedContext,
            options: {
              ...modifiedContext.options,
              mainLoopModel: resolveSkillModelOverride(model, ctx.options.mainLoopModel),
            },
          }
        }
        
        // 覆盖 effort 级别
        if (effort !== undefined) {
          const previousGetAppState = modifiedContext.getAppState
          modifiedContext = {
            ...modifiedContext,
            getAppState() {
              const appState = previousGetAppState()
              return { ...appState, effortValue: effort }
            },
          }
        }
        
        return modifiedContext
      },
    }
  },
  
  // UI 渲染函数
  renderToolResultMessage,
  renderToolUseMessage,
  renderToolUseProgressMessage,
  renderToolUseRejectedMessage,
  renderToolUseErrorMessage,
})
```

## 4. Fork 执行实现

```typescript
// src/tools/SkillTool/SkillTool.ts
async function executeForkedSkill(
  command: Command & { type: 'prompt' },
  commandName: string,
  args: string | undefined,
  context: ToolUseContext,
  canUseTool: CanUseToolFn,
  parentMessage: AssistantMessage,
  onProgress?: ToolCallProgress<Progress>,
): Promise<ToolResult<Output>> {
  const startTime = Date.now()
  const agentId = createAgentId()
  
  // 准备 fork 的上下文
  const { modifiedGetAppState, baseAgent, promptMessages, skillContent } =
    await prepareForkedCommandContext(command, args || '', context)
  
  // 合并技能的 effort 设置
  const agentDefinition = command.effort !== undefined
    ? { ...baseAgent, effort: command.effort }
    : baseAgent
  
  const agentMessages: Message[] = []
  
  try {
    // 运行子代理
    for await (const message of runAgent({
      agentDefinition,
      promptMessages,
      toolUseContext: { ...context, getAppState: modifiedGetAppState },
      canUseTool,
      isAsync: false,
      querySource: 'agent:custom',
      model: command.model as ModelAlias | undefined,
      availableTools: context.options.tools,
      override: { agentId },
    })) {
      agentMessages.push(message)
      
      // 报告进度
      if ((message.type === 'assistant' || message.type === 'user') && onProgress) {
        const normalizedNew = normalizeMessages([message])
        for (const m of normalizedNew) {
          const hasToolContent = m.message.content.some(
            c => c.type === 'tool_use' || c.type === 'tool_result'
          )
          if (hasToolContent) {
            onProgress({
              toolUseID: `skill_${parentMessage.message.id}`,
              data: { message: m, type: 'skill_progress', prompt: skillContent, agentId },
            })
          }
        }
      }
    }
    
    const resultText = extractResultText(agentMessages, 'Skill execution completed')
    agentMessages.length = 0  // 释放内存
    
    return {
      data: {
        success: true,
        commandName,
        status: 'forked',
        agentId,
        result: resultText,
      },
    }
  } finally {
    // 清理状态
    clearInvokedSkillsForAgent(agentId)
  }
}
```

## 5. Prompt 生成代码

```typescript
// src/utils/processUserInput/processSlashCommand.tsx
async function getMessagesForPromptSlashCommand(
  command: CommandBase & PromptCommand,
  args: string,
  context: ToolUseContext,
  precedingInputBlocks: ContentBlockParam[] = [],
  imageContentBlocks: ContentBlockParam[] = [],
  uuid?: string,
): Promise<SlashCommandResult> {
  // 获取技能内容
  const result = await command.getPromptForCommand(args, context)
  
  // 注册 hooks
  const hooksAllowedForThisSkill = !isRestrictedToPluginOnly('hooks') || isSourceAdminTrusted(command.source)
  if (command.hooks && hooksAllowedForThisSkill) {
    const sessionId = getSessionId()
    registerSkillHooks(context.setAppState, sessionId, command.hooks, command.name, command.type === 'prompt' ? command.skillRoot : undefined)
  }
  
  // 记录调用的技能
  const skillPath = command.source ? `${command.source}:${command.name}` : command.name
  const skillContent = result.filter((b): b is TextBlockParam => b.type === 'text').map(b => b.text).join('\n\n')
  addInvokedSkill(command.name, skillPath, skillContent, getAgentContext()?.agentId ?? null)
  
  // 格式化加载元数据
  const metadata = formatCommandLoadingMetadata(command, args)
  const additionalAllowedTools = parseToolListFromCLI(command.allowedTools ?? [])
  
  // 创建主要内容
  const mainMessageContent: ContentBlockParam[] = imageContentBlocks.length > 0 || precedingInputBlocks.length > 0
    ? [...imageContentBlocks, ...precedingInputBlocks, ...result]
    : result
  
  // 提取附件
  const attachmentMessages = await toArray(getAttachmentMessages(
    result.filter((block): block is TextBlockParam => block.type === 'text').map(block => block.text).join(' '),
    context,
    null,
    [],
    context.messages,
    'repl_main_thread',
    { skipSkillDiscovery: true }
  ))
  
  // 组装消息
  const messages = [
    createUserMessage({ content: metadata, uuid }),
    createUserMessage({ content: mainMessageContent, isMeta: true }),
    ...attachmentMessages,
    createAttachmentMessage({ type: 'command_permissions', allowedTools: additionalAllowedTools, model: command.model }),
  ]
  
  return {
    messages,
    shouldQuery: true,
    allowedTools: additionalAllowedTools,
    model: command.model,
    effort: command.effort,
    command,
  }
}
```

## 6. 关键常量定义

```typescript
// src/tools/SkillTool/constants.ts
export const SKILL_TOOL_NAME = 'Skill'

// src/constants/xml.ts
export const COMMAND_MESSAGE_TAG = 'command_message'
export const COMMAND_NAME_TAG = 'command_name'

// src/tools/SkillTool/prompt.ts
export const SKILL_BUDGET_CONTEXT_PERCENT = 0.01  // 1% 上下文预算
export const CHARS_PER_TOKEN = 4
export const DEFAULT_CHAR_BUDGET = 8_000
export const MAX_LISTING_DESC_CHARS = 250
```

## 7. 安全属性白名单

```typescript
// src/tools/SkillTool/SkillTool.ts
const SAFE_SKILL_PROPERTIES = new Set([
  // PromptCommand 属性
  'type',
  'progressMessage',
  'contentLength',
  'argNames',
  'model',
  'effort',
  'source',
  'pluginInfo',
  'disableNonInteractive',
  'skillRoot',
  'context',
  'agent',
  'getPromptForCommand',
  'frontmatterKeys',
  // CommandBase 属性
  'name',
  'description',
  'hasUserSpecifiedDescription',
  'isEnabled',
  'isHidden',
  'aliases',
  'isMcp',
  'argumentHint',
  'whenToUse',
  'paths',
  'version',
  'disableModelInvocation',
  'userInvocable',
  'loadedFrom',
  'immediate',
  'userFacingName',
])

function skillHasOnlySafeProperties(command: Command): boolean {
  for (const key of Object.keys(command)) {
    if (SAFE_SKILL_PROPERTIES.has(key)) continue
    
    // 属性不在白名单中 - 检查是否有有意义的值
    const value = (command as Record<string, unknown>)[key]
    if (value === undefined || value === null) continue
    if (Array.isArray(value) && value.length === 0) continue
    if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) continue
    
    return false
  }
  return true
}
```

## 8. 文件提取安全实现

```typescript
// src/skills/bundledSkills.ts
const O_NOFOLLOW = fsConstants.O_NOFOLLOW ?? 0
const SAFE_WRITE_FLAGS = process.platform === 'win32'
  ? 'wx'
  : fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL | O_NOFOLLOW

async function safeWriteFile(p: string, content: string): Promise<void> {
  const fh = await open(p, SAFE_WRITE_FLAGS, 0o600)
  try {
    await fh.writeFile(content, 'utf8')
  } finally {
    await fh.close()
  }
}

function resolveSkillFilePath(baseDir: string, relPath: string): string {
  const normalized = normalize(relPath)
  if (
    isAbsolute(normalized) ||
    normalized.split(pathSep).includes('..') ||
    normalized.split('/').includes('..')
  ) {
    throw new Error(`bundled skill file path escapes skill dir: ${relPath}`)
  }
  return join(baseDir, normalized)
}
```

## 9. Skill 使用追踪

```typescript
// src/utils/suggestions/skillUsageTracking.ts
const skillUsageCounts = new Map<string, number>()

export function recordSkillUsage(skillName: string): void {
  const count = skillUsageCounts.get(skillName) ?? 0
  skillUsageCounts.set(skillName, count + 1)
}

export function getSkillUsageCount(skillName: string): number {
  return skillUsageCounts.get(skillName) ?? 0
}

export function getTopSkills(limit: number = 5): string[] {
  return [...skillUsageCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([name]) => name)
}
```

## 10. 条件技能匹配

```typescript
// src/skills/loadSkillsDir.ts
export function activateConditionalSkillsForPaths(
  filePaths: string[],
  cwd: string,
): string[] {
  if (conditionalSkills.size === 0) return []
  
  const activated: string[] = []
  
  for (const [name, skill] of conditionalSkills) {
    if (skill.type !== 'prompt' || !skill.paths || skill.paths.length === 0) {
      continue
    }
    
    // 创建 gitignore 风格的匹配器
    const skillIgnore = ignore().add(skill.paths)
    
    for (const filePath of filePaths) {
      const relativePath = isAbsolute(filePath) ? relative(cwd, filePath) : filePath
      
      // 忽略无效路径
      if (!relativePath || relativePath.startsWith('..') || isAbsolute(relativePath)) {
        continue
      }
      
      // 检查是否匹配
      if (skillIgnore.ignores(relativePath)) {
        // 激活技能
        dynamicSkills.set(name, skill)
        conditionalSkills.delete(name)
        activatedConditionalSkillNames.add(name)
        activated.push(name)
        logForDebugging(`[skills] Activated conditional skill '${name}' (matched path: ${relativePath})`)
        break
      }
    }
  }
  
  if (activated.length > 0) {
    skillsLoaded.emit()
  }
  
  return activated
}
```
