# Claude Code Skill 调用流程图

## 1. 启动时 Skill 加载流程

```
┌─────────────┐
│ CLI 启动    │
└──────┬──────┘
       ▼
┌─────────────────────┐
│ initBundledSkills() │  ← 注册内置技能到内存
└──────────┬──────────┘
           ▼
┌─────────────────────────────┐
│ loadAllCommands(cwd)        │  ← Memoized
│ ┌─────────────────────────┐ │
│ │ getSkills(cwd)          │ │
│ │ • getSkillDirCommands   │ │ ← 加载 .claude/skills/
│ │ • getPluginSkills       │ │ ← 加载插件技能
│ │ • getBundledSkills      │ │ ← 获取内置技能
│ │ • getBuiltinPluginSkills│ │ ← 内置插件技能
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ getPluginCommands()     │ │ ← 加载插件命令
│ └─────────────────────────┘ │
│ ┌─────────────────────────┐ │
│ │ getWorkflowCommands()   │ │ ← 加载工作流
│ └─────────────────────────┘ │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 合并 & 去重                  │
│ [bundled, plugin, skills,   │
│  workflow, pluginCmds,      │
│  builtinCmds]               │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 过滤: meetsAvailability     │  ← auth/provider 检查
│ 过滤: isCommandEnabled      │  ← isEnabled() 检查
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 可用命令列表                 │  ← 返回给 UI 和 Tool
└─────────────────────────────┘
```

## 2. SkillTool 调用流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Model 决定调用 Skill                                            │
│ { skill: "commit", args: "-m 'fix bug'" }                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ SkillTool.validateInput()                                       │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 1. 格式检查: skill.trim() 非空                               │ │
│ │ 2. 去除前导斜杠: "/commit" → "commit"                        │ │
│ │ 3. 查找命令: findCommand(name, commands)                    │ │
│ │ 4. 检查 disableModelInvocation                              │ │
│ │ 5. 检查 type === 'prompt'                                   │ │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ SkillTool.checkPermissions()                                    │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 1. 检查 deny 规则                                            │ │
│ │    Skill(name) 匹配规则内容                                   │ │
│ │    例: deny Skill(commit)                                   │ │
│ │                                                             │ │
│ │ 2. 检查 allow 规则                                           │ │
│ │    例: allow Skill(commit)                                  │ │
│ │                                                             │ │
│ │ 3. 检查安全属性 (skillHasOnlySafeProperties)                 │ │
│ │    只有 SAFE_SKILL_PROPERTIES 中的属性 → auto-allow         │ │
│ │                                                             │ │
│ │ 4. 默认: behavior='ask'                                      │ │
│ │    显示权限对话框，提供建议规则                               │ │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ SkillTool.call()                                                │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
              ┌─────────────────────┐
              │  command.context    │
              │   === 'fork'?       │
              └──────────┬──────────┘
                    否 /     \ 是
                      /       \
                     ▼         ▼
┌──────────────────────────┐  ┌──────────────────────────────┐
│ Inline 执行              │  │ Fork 执行                    │
│                          │  │                              │
│ processPromptSlashCommand│  │ executeForkedSkill()         │
│                          │  │                              │
│ 1. getPromptForCommand() │  │ 1. prepareForkedCommandContext│
│    获取 SKILL.md 内容     │  │    - 创建子代理上下文         │
│                          │  │    - 准备 prompt messages    │
│ 2. 变量替换              │  │                              │
│    $ARGUMENTS            │  │ 2. runAgent()                │
│    ${CLAUDE_SKILL_DIR}   │  │    运行子代理                 │
│    ${CLAUDE_SESSION_ID}  │  │    - 独立的 token 预算        │
│    !`shell command`      │  │    - 独立的上下文             │
│                          │  │                              │
│ 3. 注册 Hooks            │  │ 3. 收集执行结果               │
│    registerSkillHooks()  │  │    - 进度消息                 │
│                          │  │    - 最终结果                 │
│ 4. addInvokedSkill()     │  │                              │
│    追踪技能调用           │  │ 4. clearInvokedSkillsForAgent│
│                          │  │    清理状态                   │
│ 5. 创建消息              │  │                              │
│    - metadata (XML tags) │  │ 5. 返回 forked 结果           │
│    - skill content       │  │    { status: 'forked', ... }  │
│    - attachments         │  │                              │
│    - command_permissions │  │                              │
│                          │  │                              │
│ 6. 返回结果              │  │                              │
│    { success: true,      │  │                              │
│      commandName,        │  │                              │
│      allowedTools,       │  │                              │
│      model,              │  │                              │
│      newMessages,        │  │                              │
│      contextModifier }   │  │                              │
└──────────┬───────────────┘  └──────────────┬───────────────┘
           │                                 │
           └──────────────┬──────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 返回 ToolResult                                                  │
│                                                                  │
│ Inline: { data: { success, commandName, ... },                  │
│           newMessages,                                          │
│           contextModifier }                                     │
│                                                                  │
│ Fork:   { data: { success, commandName, status:'forked',        │
│                   agentId, result } }                           │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Skill 内容处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│ getPromptForCommand(args, toolUseContext)                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. 准备基础内容                                                 │
│                                                                  │
│    如果有 baseDir:                                               │
│    "Base directory for this skill: {baseDir}\n\n{markdownContent}"│
│                                                                  │
│    否则:                                                         │
│    "{markdownContent}"                                          │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 参数替换 (substituteArguments)                               │
│                                                                  │
│    $0, $1, $2, ... → 位置参数                                   │
│    $ARGUMENTS      → 所有参数                                   │
│    $FLAGS          → 标志参数                                   │
│    $KEYWORD_ARGS    → 关键字参数                                 │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. 变量替换                                                     │
│                                                                  │
│    ${CLAUDE_SKILL_DIR}  → skill 目录路径                        │
│    ${CLAUDE_SESSION_ID} → 当前 session ID                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Shell 命令执行                                               │
│    (仅非 MCP 技能)                                              │
│                                                                  │
│    !`command` 或                                                │
│    ```!                                                         │
│    command                                                      │
│    ```                                                          │
│                                                                  │
│    执行流程:                                                    │
│    executeShellCommandsInPrompt()                               │
│    → parsePromptShellCommands()                                │
│    → executeShellCommand()                                     │
│    → 替换命令为输出                                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. 返回 ContentBlockParam[]                                     │
│                                                                  │
│    [{ type: 'text', text: finalContent }]                       │
└─────────────────────────────────────────────────────────────────┘
```

## 4. 动态 Skill 发现流程

```
┌─────────────────────────────────────────────────────────────────┐
│ 文件操作触发 (Read/Write/Edit/Glob)                             │
│ 例如: 用户编辑 src/components/Button.tsx                        │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ discoverSkillDirsForPaths(                                      │
│   ['/project/src/components/Button.tsx'],                      │
│   '/project'                                                    │
│ )                                                               │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 遍历每个文件路径                                                │
│                                                                  │
│ for filePath in filePaths:                                     │
│   currentDir = dirname(filePath)                               │
│                                                                  │
│   while currentDir startsWith(cwd + sep):                      │
│     skillDir = join(currentDir, '.claude', 'skills')           │
│                                                                  │
│     if skillDir not in dynamicSkillDirs:                       │
│        dynamicSkillDirs.add(skillDir)                          │
│        try stat(skillDir) → exists?                            │
│        check gitignore → not ignored?                          │
│        add to newDirs                                          │
│                                                                  │
│     currentDir = parent(currentDir)                            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 按深度排序（最深的优先）                                         │
│                                                                  │
│ newDirs.sort((a, b) => b.split(sep).length -                   │
│                       a.split(sep).length)                     │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ addSkillDirectories(newDirs)                                    │
│                                                                  │
│ for dir in newDirs:                                            │
│   skills = loadSkillsFromSkillsDir(dir)                        │
│   for skill in skills:                                         │
│     dynamicSkills.set(skill.name, skill)                       │
│                                                                  │
│ skillsLoaded.emit()  ← 触发缓存清除                             │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 后续 getCommands() 调用包含动态技能                             │
└─────────────────────────────────────────────────────────────────┘
```

## 5. 条件 Skill 激活流程

```
┌─────────────────────────────────────────────────────────────────┐
│ 文件操作触发                                                    │
│ activateConditionalSkillsForPaths(filePaths, cwd)               │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 遍历所有条件技能 (conditionalSkills Map)                        │
│                                                                  │
│ for [name, skill] of conditionalSkills:                        │
│   if skill.paths is empty: continue                            │
│                                                                  │
│   // 创建 gitignore 风格的匹配器                               │
│   skillIgnore = ignore().add(skill.paths)                      │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 检查每个文件路径是否匹配                                        │
│                                                                  │
│   for filePath in filePaths:                                   │
│     relativePath = relative(cwd, filePath)                     │
│                                                                  │
│     if relativePath invalid (empty, .., absolute):             │
│       continue                                                 │
│                                                                  │
│     if skillIgnore.ignores(relativePath):                      │
│       // 匹配成功!                                             │
│       dynamicSkills.set(name, skill)                           │
│       conditionalSkills.delete(name)                           │
│       activatedConditionalSkillNames.add(name)                 │
│       activated.push(name)                                     │
│       break                                                    │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 如果有技能被激活                                                │
│   skillsLoaded.emit()                                           │
│   logEvent('tengu_dynamic_skills_changed')                     │
└─────────────────────────────────────────────────────────────────┘
```

## 6. Slash Command 处理流程 (对比)

```
┌─────────────────────────────────────────────────────────────────┐
│ 用户输入: /commit -m "fix bug"                                  │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ processSlashCommand()                                           │
│                                                                  │
│ 1. parseSlashCommand(input)                                     │
│    → { commandName: 'commit', args: '-m "fix bug"', isMcp: false }│
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. 查找命令: getCommand(commandName, commands)                  │
│    → 找到 commit 命令                                           │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. 根据命令类型分发                                             │
│                                                                  │
│    switch (command.type):                                      │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ case 'local-jsx':                                       │ │
│    │   command.load().then(mod => mod.call(onDone, ctx, args))│ │
│    │   → 渲染 Ink UI                                         │ │
│    └─────────────────────────────────────────────────────────┘ │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ case 'local':                                           │ │
│    │   command.load().then(mod => mod.call(args, ctx))       │ │
│    │   → 返回文本结果                                        │ │
│    └─────────────────────────────────────────────────────────┘ │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ case 'prompt':                                          │ │
│    │   if command.context === 'fork':                        │ │
│    │     → executeForkedSlashCommand()                       │ │
│    │   else:                                                 │ │
│    │     → getMessagesForPromptSlashCommand()                │ │
│    │       (与 SkillTool 调用相同的逻辑)                     │ │
│    └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 7. Skill 与 Tool 的关系

```
┌─────────────────────────────────────────────────────────────────┐
│                    Skill vs Tool 对比                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐             │
│  │       Skill         │    │        Tool         │             │
│  ├─────────────────────┤    ├─────────────────────┤             │
│  │                     │    │                     │             │
│  │ 定义: 高级指令模板   │    │ 定义: 具体执行能力   │             │
│  │                     │    │                     │             │
│  │ 形式: Markdown 文件 │    │ 形式: TypeScript 类 │             │
│  │       (+ Frontmatter)│   │                     │             │
│  │                     │    │                     │             │
│  │ 用途: 封装工作流     │    │ 用途: 执行原子操作   │             │
│  │       提供领域知识   │    │       (读/写/执行)  │             │
│  │                     │    │                     │             │
│  │ 执行: 通过 SkillTool│    │ 执行: 直接由 LLM    │             │
│  │       展开为 Prompt │    │       调用          │             │
│  │                     │    │                     │             │
│  │ 例子: /commit       │    │ 例子: FileReadTool  │             │
│  │       /review-pr    │    │       BashTool      │             │
│  │       /pdf          │    │       WebSearchTool │             │
│  │                     │    │                     │             │
│  └─────────────────────┘    └─────────────────────┘             │
│                                                                  │
│  关系: Skill 可以封装 Tool 的使用模式                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  SkillTool 是连接两者的桥梁                              │   │
│  │                                                          │   │
│  │  Model ──▶ SkillTool ──▶ Skill 展开 ──▶ 新 Prompt      │   │
│  │                                      ──▶ Tool 调用      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```
