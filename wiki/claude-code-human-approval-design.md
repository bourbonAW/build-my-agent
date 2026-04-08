# Claude Code 人类批准机制深度研究报告

## 概述

Claude Code 的人类批准（Human Approval）机制是一个多层次、多模式的权限控制系统，用于确保 AI 在执行高危操作前获得人类用户的明确授权。该系统结合了**规则引擎**、**安全模式**、**AI 分类器**和**交互式 UI**等多种技术手段，形成了一个完整的安全防护体系。

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         人类批准机制架构图                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   工具调用    │───▶│  权限检查入口  │───▶│  决策流程引擎  │                   │
│  │  Tool.call() │    │hasPermissions│    │permissions.ts│                   │
│  └──────────────┘    │   ToUseTool  │    └──────┬───────┘                   │
│                      └──────────────┘           │                           │
│                                                 ▼                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        权限决策流程 (7步)                             │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │   │
│  │  │1. 拒绝规则│▶│2. 询问规则│▶│3. 工具检查│▶│4. 安全模式│▶│5. 允许规则│        │   │
│  │  │  检查   │ │  检查   │ │Permissions│ │  检查   │ │  检查   │        │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘        │   │
│  │       │           │           │           │           │              │   │
│  │       ▼           ▼           ▼           ▼           ▼              │   │
│  │    [拒绝]      [询问]      [通过/询问/拒绝]  [绕过/询问]   [允许]        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      模式特定处理层                                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │ default  │  │ dontAsk  │  │   auto   │  │  bypass  │            │   │
│  │  │ 模式     │  │ 模式     │  │ 模式     │  │Permissions│            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      交互式权限请求层                                 │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ 本地UI对话框  │  │ Bridge (CCR) │  │  Channel   │  │  Hooks      │ │   │
│  │  │PermissionRequest│ │  远程批准    │  │ 权限中继    │  │ 外部处理    │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、核心组件详解

### 2.1 权限类型系统 (types/permissions.ts)

```typescript
// 权限模式定义
export type PermissionMode = 
  | 'default'      // 默认模式：每次询问
  | 'acceptEdits'  // 接受编辑：自动允许文件编辑
  | 'dontAsk'      // 不询问：自动拒绝需要确认的操作
  | 'plan'         // 计划模式：批量确认
  | 'auto'         // 自动模式：AI 分类器决策
  | 'bypassPermissions' // 绕过权限：用于恢复会话

// 权限行为
export type PermissionBehavior = 'allow' | 'deny' | 'ask'

// 权限决策结果
export type PermissionDecision = 
  | { behavior: 'allow', updatedInput?, decisionReason? }
  | { behavior: 'ask', message, decisionReason?, suggestions? }
  | { behavior: 'deny', message, decisionReason }
```

### 2.2 权限检查入口 (utils/permissions/permissions.ts)

`hasPermissionsToUseTool` 是整个权限系统的核心入口函数，实现了 **7 步决策流程**：

```
┌────────────────────────────────────────────────────────┐
│              hasPermissionsToUseTool 决策流程           │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Step 1a: 检查拒绝规则 (Deny Rules)                     │
│     └── 如果工具被明确拒绝 → 返回 deny                  │
│                                                        │
│  Step 1b: 检查询问规则 (Ask Rules)                      │
│     └── 如果工具有 always-ask 规则 → 返回 ask          │
│     └── 例外：沙箱自动允许                              │
│                                                        │
│  Step 1c: 调用 tool.checkPermissions()                 │
│     └── 工具特定的权限检查                              │
│                                                        │
│  Step 1d: 工具拒绝 (Tool Deny)                         │
│     └── 如果工具返回 deny → 返回 deny                   │
│                                                        │
│  Step 1e: 需要用户交互 (requiresUserInteraction)        │
│     └── 如 AskUserQuestion, ExitPlanMode               │
│                                                        │
│  Step 1f: 内容特定的询问规则                            │
│     └── 如 Bash(npm publish:*) 的特定规则              │
│                                                        │
│  Step 1g: 安全检查 (Safety Checks) - 绕过免疫           │
│     └── .git/, .claude/, shell configs 等敏感路径       │
│                                                        │
│  Step 2a: 检查权限绕过模式 (bypassPermissions)          │
│                                                        │
│  Step 2b: 检查允许规则 (Allow Rules)                    │
│     └── 如果工具被明确允许 → 返回 allow                 │
│                                                        │
│  Step 3: 将 passthrough 转换为 ask                      │
│                                                        │
└────────────────────────────────────────────────────────┘
```

### 2.3 权限规则系统

```
┌─────────────────────────────────────────────────────────────┐
│                    权限规则结构                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  PermissionRule {                                           │
│    source: 'userSettings' | 'projectSettings' |            │
│            'localSettings' | 'cliArg' | 'command' |        │
│            'session' | 'policySettings' | 'flagSettings'   │
│    ruleBehavior: 'allow' | 'deny' | 'ask'                  │
│    ruleValue: {                                            │
│      toolName: string      // 例如: "Bash"                 │
│      ruleContent?: string  // 例如: "npm publish:*"        │
│    }                                                        │
│  }                                                          │
│                                                             │
│  示例规则：                                                  │
│  - "Bash"                   → 整个 Bash 工具               │
│  - "Bash(npm publish:*)"    → npm publish 命令             │
│  - "FileEdit"               → 整个文件编辑工具              │
│  - "mcp__server1"           → 整个 MCP 服务器              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、高危命令检测机制

### 3.1 Bash 安全验证 (tools/BashTool/bashSecurity.ts)

Bash 安全验证实现了 **20+ 种安全检查**，分为早期允许验证器和主验证器链：

#### 3.1.1 安全验证器列表

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Bash 安全验证器                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  早期允许验证器 (Early Allow Validators)                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 1. validateEmpty           - 空命令                          │   │
│  │ 2. validateGitCommit       - 安全的 git commit -m "msg"      │   │
│  │ 3. validateSafeCommandSubstitution - 安全的 heredoc 模式     │   │
│  │ 4. validateJqCommand       - jq 命令安全检查                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  主验证器链 (Main Validators)                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ 5.  validateIncompleteCommands  - 不完整命令检测              │   │
│  │ 6.  validateQuotedNewline       - 引号内换行检测              │   │
│  │ 7.  validateCarriageReturn      - 回车符检测                  │   │
│  │ 8.  validateDangerousPatterns   - 危险模式 ($(), ${}, <())   │   │
│  │ 9.  validateRedirections        - 重定向检测 (<, >)           │   │
│  │ 10. validateNewlines            - 多行命令检测               │   │
│  │ 11. validateObfuscatedFlags     - 混淆标志检测               │   │
│  │ 12. validateShellMetacharacters - Shell 元字符 (; | &)       │   │
│  │ 13. validateBraceExpansion      - 大括号扩展检测             │   │
│  │ 14. validateDangerousVariables  - 危险变量位置               │   │
│  │ 15. validateIfsInjection        - IFS 注入检测               │   │
│  │ 16. validateControlCharacters   - 控制字符检测               │   │
│  │ 17. validateUnicodeWhitespace   - Unicode 空白字符           │   │
│  │ 18. validateBackslashEscapedOps - 反斜杠转义操作符           │   │
│  │ 19. validateZshDangerousCommands - Zsh 危险命令              │   │
│  │ 20. validateProcEnvironAccess   - /proc/self/environ 访问    │   │
│  │ 21. validateMidWordHash         - 单词中间 # 检测            │   │
│  │ 22. validateCommentQuoteDesync  - 注释引号不同步             │   │
│  │ 23. validateMalformedTokens     - 畸形 Token 检测            │   │
│  │ 24. validateJqSystemFunction    - jq system() 函数           │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.2 危险模式定义

```typescript
// 命令替换和危险模式
const COMMAND_SUBSTITUTION_PATTERNS = [
  { pattern: /\$\(/, message: '$() command substitution' },
  { pattern: /`/, message: 'backtick command substitution' },
  { pattern: /\$\{/, message: '${} parameter substitution' },
  { pattern: /</, message: 'process substitution <()' },
  { pattern: />(\()/ message: 'process substitution >()' },
  // ... 更多模式
]

// Zsh 危险命令
const ZSH_DANGEROUS_COMMANDS = new Set([
  'zmodload', 'emulate', 'sysopen', 'sysread', 
  'syswrite', 'zpty', 'ztcp', 'zsocket'
])
```

### 3.2 破坏性命令警告 (tools/BashTool/destructiveCommandWarning.ts)

纯粹信息性的警告系统，不影响权限逻辑：

```
┌─────────────────────────────────────────────────────────────────┐
│                     破坏性命令模式                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Git 相关：                                                      │
│  - git reset --hard          → "可能丢弃未提交的更改"            │
│  - git push --force          → "可能覆盖远程历史"                │
│  - git clean -f              → "可能永久删除未跟踪的文件"         │
│  - git checkout .            → "可能丢弃所有工作区更改"          │
│                                                                 │
│  文件删除：                                                      │
│  - rm -rf                    → "可能递归强制删除文件"            │
│                                                                 │
│  数据库：                                                        │
│  - DROP TABLE                → "可能删除数据库对象"              │
│  - DELETE FROM               → "可能删除表中所有行"              │
│                                                                 │
│  基础设施：                                                      │
│  - kubectl delete            → "可能删除 Kubernetes 资源"        │
│  - terraform destroy         → "可能销毁 Terraform 基础设施"     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 危险权限规则 (utils/permissions/dangerousPatterns.ts)

用于检测可能被滥用的允许规则：

```typescript
// 跨平台代码执行入口点
export const CROSS_PLATFORM_CODE_EXEC = [
  // 解释器
  'python', 'python3', 'node', 'deno', 'tsx', 'ruby', 'perl', 'php', 'lua',
  // 包管理器运行器
  'npx', 'bunx', 'npm run', 'yarn run', 'pnpm run', 'bun run',
  // Shell
  'bash', 'sh', 'zsh', 'fish',
  // 远程命令
  'ssh', 'curl', 'wget',
  // 危险命令
  'eval', 'exec', 'env', 'xargs', 'sudo'
]

// Anthropic 内部额外规则 (USER_TYPE === 'ant')
const ANT_ONLY_PATTERNS = [
  'gh', 'gh api',          // GitHub CLI
  'git',                   // git config 等
  'kubectl', 'aws', 'gcloud', 'gsutil'  // 云工具
]
```

---

## 四、权限模式详解

### 4.1 Default 模式

```
┌─────────────────────────────────────────────────────────┐
│                   Default 模式                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  特点：                                                  │
│  - 每次执行高危命令前都询问用户                          │
│  - 最安全的交互模式                                      │
│                                                         │
│  流程：                                                  │
│  1. 工具调用 → 权限检查 → 发现需要确认                  │
│  2. 显示 PermissionRequest UI                           │
│  3. 等待用户输入 (Allow / Deny / 添加规则)              │
│  4. 根据用户选择执行或拒绝                               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 4.2 AcceptEdits 模式

```
┌─────────────────────────────────────────────────────────┐
│                  AcceptEdits 模式                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  特点：                                                  │
│  - 自动允许文件编辑操作                                  │
│  - 适用于重构、批量修改等场景                            │
│                                                         │
│  自动允许的操作：                                        │
│  - FileEditTool (在工作目录内的文件编辑)                 │
│  - FileWriteTool (在工作目录内的文件写入)                │
│  - NotebookEditTool                                     │
│                                                         │
│  仍会询问的操作：                                        │
│  - Bash 命令                                            │
│  - 工作目录外的文件操作                                  │
│  - 删除操作                                             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 4.3 Auto 模式 (YOLO/自动模式)

Auto 模式使用 **AI 分类器** 自动判断操作是否安全，无需用户确认。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Auto 模式架构                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     两阶段分类器 (XML)                             │   │
│  │                                                                  │   │
│  │   Stage 1: Fast (快速阶段)                                       │   │
│  │   - 模型: Claude Haiku 或同等快速模型                            │   │
│  │   - 目的: 快速识别明显安全的操作                                  │   │
│  │   - 输出: allow / block / 需要深入分析                           │   │
│  │                                                                  │   │
│  │        ┌──────────┐                                              │   │
│  │        │  Fast    │───▶ allow ──▶ 执行操作                       │   │
│  │        │Classifier│───▶ block ──▶ 拒绝操作                       │   │
│  │        └────┬─────┘                                              │   │
│  │             │ need_thinking                                      │   │
│  │             ▼                                                    │   │
│  │   ┌──────────────────┐                                           │   │
│  │   │ Stage 2: Thinking │───▶ allow/block ──▶ 相应操作             │   │
│  │   │ (深度分析阶段)    │                                           │   │
│  │   └──────────────────┘                                           │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  输入数据：                                                              │
│  - 完整对话历史 (User 消息 + Assistant tool_use)                        │
│  - 当前待执行的操作描述                                                  │
│  - CLAUDE.md 配置 (用户意图)                                            │
│  - 权限模板 (允许/拒绝/环境的规则)                                       │
│                                                                         │
│  分类器决策依据：                                                        │
│  - 操作是否在用户意图范围内                                              │
│  - 操作是否可能导致数据丢失或安全问题                                    │
│  - 操作是否是请求任务的必要步骤                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.3.1 Auto 模式快速路径

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Auto 模式快速路径 (Fast Paths)                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  为了优化性能，auto 模式在调用分类器前会检查快速路径：                      │
│                                                                         │
│  1. acceptEdits 检查                                                    │
│     └── 如果操作在 acceptEdits 模式下会被允许 → 直接允许                  │
│     └── 避免对安全文件编辑的昂贵分类器调用                                │
│                                                                         │
│  2. 安全工具白名单                                                       │
│     └── 只读工具 (Glob, Grep, FileRead 等) → 直接允许                   │
│     └── 低风险工具                                                       │
│                                                                         │
│  3. 安全 Bash 命令前缀                                                   │
│     └── 预定义的安全命令模式                                             │
│     └── 基于规则的快速匹配                                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.3.2 拒绝限制和回退机制

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Auto 模式拒绝限制                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  为了防止连续拒绝导致任务无法进行，系统实现了拒绝追踪：                     │
│                                                                         │
│  DenialTrackingState {                                                  │
│    consecutiveDenials: number  // 连续拒绝计数                           │
│    totalDenials: number        // 总会话拒绝计数                         │
│  }                                                                      │
│                                                                         │
│  限制阈值：                                                              │
│  - 连续拒绝 ≥ 3 次  → 回退到交互式提示                                  │
│  - 总会话拒绝 ≥ 10 次 → 回退到交互式提示                                │
│                                                                         │
│  回退行为：                                                              │
│  - 显示警告："N 个操作被阻止，请查看对话历史"                            │
│  - 切换到交互式权限请求                                                  │
│  - 用户可以手动批准或拒绝                                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Plan 模式

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Plan 模式                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  特点：                                                                  │
│  - 批量确认：用户一次性审阅和批准整个计划                                │
│  - 减少中断：计划执行期间不显示权限提示                                  │
│                                                                         │
│  流程：                                                                  │
│  1. AI 生成计划 (EnterPlanModeTool)                                     │
│  2. 用户审查计划并批准/修改                                              │
│  3. 进入计划执行阶段 (isInPlanMode = true)                              │
│  4. 执行计划中的操作，批量处理权限                                       │
│  5. 计划完成，退出计划模式 (ExitPlanModeV2Tool)                         │
│                                                                         │
│  权限处理：                                                              │
│  - 计划批准时：提示用户确认整个计划                                      │
│  - 计划执行时：使用特殊逻辑处理权限                                       │
│  - 支持从 bypassPermissions 恢复                                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 五、交互式权限请求系统

### 5.1 权限请求 UI 组件架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    权限请求 UI 组件层次                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  PermissionRequest (入口组件)                                            │
│  └── permissionComponentForTool() 根据工具类型选择具体组件              │
│      │                                                                  │
│      ├── BashPermissionRequest          - Bash 命令权限                 │
│      ├── PowerShellPermissionRequest    - PowerShell 权限               │
│      ├── FileEditPermissionRequest      - 文件编辑权限                  │
│      ├── FileWritePermissionRequest     - 文件写入权限                  │
│      ├── FilesystemPermissionRequest    - 文件系统操作权限              │
│      ├── NotebookEditPermissionRequest  - Notebook 编辑                 │
│      ├── WebFetchPermissionRequest      - Web 请求权限                  │
│      ├── SkillPermissionRequest         - Skill 执行权限                │
│      ├── AskUserQuestionPermissionRequest - 询问用户权限                │
│      ├── EnterPlanModePermissionRequest   - 进入计划模式                │
│      ├── ExitPlanModePermissionRequest    - 退出计划模式                │
│      ├── ReviewArtifactPermissionRequest  - 审查工件 (可选)             │
│      ├── WorkflowPermissionRequest        - 工作流权限 (可选)           │
│      ├── MonitorPermissionRequest         - 监控权限 (可选)             │
│      └── FallbackPermissionRequest        - 默认回退                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 交互式权限处理流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    交互式权限处理流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  handleInteractivePermission()                                          │
│  │                                                                      │
│  ├── 1. 推送到权限请求队列 (ToolUseConfirm)                             │
│  │   └── 显示 PermissionRequest UI                                     │
│  │                                                                      │
│  ├── 2. 并行启动多个"赛车"决策源                                        │
│  │   │                                                                  │
│  │   ├── 2a. 本地用户交互 (主路径)                                      │
│  │   │   └── onAllow / onReject / onAbort 回调                         │
│  │   │                                                                  │
│  │   ├── 2b. Bridge 远程批准 (CCR)                                      │
│  │   │   └── 发送到 claude.ai 进行远程确认                             │
│  │   │                                                                  │
│  │   ├── 2c. Channel 权限中继                                           │
│  │   │   └── 通过 Telegram/iMessage 等发送权限请求                      │
│  │   │                                                                  │
│  │   ├── 2d. PermissionRequest Hooks                                   │
│  │   │   └── 外部 hooks 可以自动批准/拒绝                               │
│  │   │                                                                  │
│  │   └── 2e. Bash Classifier (Auto 模式)                               │
│  │       └── 异步分类器检查，可能自动批准                                │
│  │                                                                      │
│  ├── 3. 第一个响应者获胜 (resolveOnce 机制)                            │
│  │   └── claim() 确保只有一个决策源能成功                               │
│  │                                                                      │
│  └── 4. 清理其他路径                                                    │
│      └── 取消 Bridge 请求、清除分类器指示器等                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 分类器自动批准 UI 反馈

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    分类器自动批准 UX                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  当分类器自动批准命令时，UI 会显示：                                      │
│                                                                         │
│  ┌─────────────────────────────────────────┐                           │
│  │  ✓ Bash command allowed by auto mode   │                           │
│  │    ls -la                               │                           │
│  │                                         │                           │
│  │    [选项变暗，不可选择]                  │                           │
│  │    (Allow Once) (Always Allow) (Deny)  │                           │
│  │                                         │                           │
│  │    3秒后自动关闭...                     │                           │
│  └─────────────────────────────────────────┘                           │
│                                                                         │
│  用户可以在 3 秒内按 Esc 取消自动关闭，查看详情                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 六、工具执行与权限集成

### 6.1 工具执行流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    工具执行完整流程                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  runToolUse()                                                           │
│  │                                                                      │
│  ├── 1. 查找工具                                                        │
│  │   └── 通过工具名称查找对应的 Tool 实例                               │
│  │                                                                      │
│  ├── 2. 输入验证                                                        │
│  │   ├── Zod schema 验证                                                │
│  │   └── 工具特定的 validateInput() 验证                                │
│  │                                                                      │
│  ├── 3. 预工具钩子 (PreToolUse Hooks)                                   │
│  │   └── 并行执行所有注册的 preToolUse hooks                            │
│  │                                                                      │
│  ├── 4. 权限检查                                                        │
│  │   └── canUseTool() → hasPermissionsToUseTool()                       │
│  │       ├── allow → 继续执行                                           │
│  │       ├── deny  → 返回拒绝结果                                       │
│  │       └── ask   → 显示权限请求 UI                                     │
│  │                                                                      │
│  ├── 5. 执行工具                                                        │
│  │   └── tool.call()                                                    │
│  │                                                                      │
│  ├── 6. 后工具钩子 (PostToolUse Hooks)                                  │
│  │   └── 执行 postToolUse hooks                                         │
│  │                                                                      │
│  └── 7. 返回结果                                                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.2 权限 Hook 系统

```typescript
// 权限请求 Hook
interface PermissionRequestHook {
  // 返回权限决策或 null (表示不干预)
  (params: PermissionRequestHookParams): Promise<PermissionRequestResult | null>
}

interface PermissionRequestResult {
  behavior: 'allow' | 'deny'
  message?: string           // deny 时的拒绝消息
  updatedInput?: object      // 允许时可以修改输入
  updatedPermissions?: PermissionUpdate[]  // 允许时可以更新权限
  interrupt?: boolean        // deny 时是否中断执行
}
```

---

## 七、安全配置与持久化

### 7.1 权限配置层级

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    权限配置层级 (优先级从高到低)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. policySettings   - 策略设置 (管理员配置，只读)                       │
│  2. flagSettings     - 功能标志设置 (只读)                               │
│  3. cliArg          - 命令行参数 (--permission-mode)                     │
│  4. session         - 会话级别 (运行时添加)                              │
│  5. localSettings   - 本地设置 (.claude/settings.json)                   │
│  6. projectSettings - 项目设置 (项目根目录的 .claude.json)               │
│  7. userSettings    - 用户设置 (~/.claude/settings.json)                 │
│                                                                         │
│  层级规则：                                                              │
│  - 高优先级的配置可以覆盖低优先级的配置                                  │
│  - 用户只能修改用户级别的配置                                            │
│  - policySettings 可以强制限制权限行为                                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 权限更新操作

```typescript
type PermissionUpdate =
  | { type: 'addRules', destination, rules, behavior }      // 添加规则
  | { type: 'replaceRules', destination, rules, behavior }  // 替换规则
  | { type: 'removeRules', destination, rules, behavior }   // 删除规则
  | { type: 'setMode', destination, mode }                  // 设置模式
  | { type: 'addDirectories', destination, directories }    // 添加工作目录
  | { type: 'removeDirectories', destination, directories } // 移除工作目录
```

---

## 八、安全考虑

### 8.1 安全设计原则

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    安全设计原则                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 默认拒绝 (Default Deny)                                             │
│     - 未知的、未明确允许的操作默认需要确认                               │
│                                                                         │
│  2. 防御性编程 (Defense in Depth)                                       │
│     - 多层安全检查，即使一层被绕过还有其他层                             │
│                                                                         │
│  3. 显式优于隐式 (Explicit over Implicit)                               │
│     - 权限规则必须明确，不支持通配符滥用                                 │
│                                                                         │
│  4. 绕过免疫 (Bypass Immunity)                                          │
│     - 某些安全检查在 bypassPermissions 模式下仍然有效                    │
│     - 例如 .git/, .claude/, shell 配置文件的操作                         │
│                                                                         │
│  5. 解析器安全 (Parser Safety)                                          │
│     - 防范 shell-quote 和 bash 之间的解析差异                            │
│     - 例如回车符 \r 的处理差异                                           │
│                                                                         │
│  6. 可见性 (Visibility)                                                 │
│     - 所有权限决策都有明确的理由 (decisionReason)                        │
│     - 支持调试日志记录                                                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 已知绕过防护

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    已知绕过技术及其防护                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 命令注入                                                            │
│     攻击: echo "test" && rm -rf /                                       │
│     防护: validateShellMetacharacters, validateDangerousPatterns        │
│                                                                         │
│  2. 命令替换                                                            │
│     攻击: echo $(rm -rf /)                                              │
│     防护: COMMAND_SUBSTITUTION_PATTERNS 检测                            │
│                                                                         │
│  3. 编码绕过                                                            │
│     攻击: $'\x72\x6d' (ANSI-C quoting)                                  │
│     防护: validateControlCharacters, hasUnescapedChar                   │
│                                                                         │
│  4. 解析差异                                                            │
│     攻击: TZ=UTC\recho curl evil.com (\r 解析差异)                      │
│     防护: validateCarriageReturn                                        │
│                                                                         │
│  5. Zsh 特定攻击                                                        │
│     攻击: =cmd (Zsh equals expansion)                                   │
│     防护: COMMAND_SUBSTITUTION_PATTERNS 中的 Zsh 检测                   │
│                                                                         │
│  6. Heredoc 注入                                                        │
│     攻击: $(cat <<EOF; evil; EOF)                                       │
│     防护: isSafeHeredoc 详细验证                                        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 九、代码架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    人类批准机制代码架构                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  types/                                                                     │
│  └── permissions.ts              # 核心类型定义                             │
│      ├── PermissionMode                                                  │
│      ├── PermissionRule                                                  │
│      ├── PermissionDecision                                              │
│      ├── YoloClassifierResult                                            │
│      └── ToolPermissionContext                                           │
│                                                                             │
│  utils/permissions/                                                         │
│  ├── permissions.ts              # 核心权限检查入口                         │
│  │   └── hasPermissionsToUseTool()                                       │
│  ├── dangerousPatterns.ts        # 危险模式定义                             │
│  ├── yoloClassifier.ts           # Auto 模式 AI 分类器                      │
│  ├── classifierDecision.ts       # 分类器决策逻辑                           │
│  ├── denialTracking.ts           # 拒绝追踪和限制                           │
│  ├── autoModeState.ts            # Auto 模式状态管理                        │
│  ├── bashClassifier.ts           # Bash 分类器                              │
│  ├── PermissionResult.ts         # 权限结果类型                             │
│  ├── PermissionRule.ts           # 权限规则定义                             │
│  ├── PermissionUpdate.ts         # 权限更新操作                             │
│  └── permissionSetup.ts          # 权限上下文初始化                         │
│                                                                             │
│  tools/BashTool/                                                            │
│  ├── bashSecurity.ts             # Bash 安全验证 (20+ 检查)                 │
│  ├── destructiveCommandWarning.ts # 破坏性命令警告                          │
│  ├── bashPermissions.ts          # Bash 权限集成                            │
│  └── pathValidation.ts           # 路径验证                                 │
│                                                                             │
│  tools/PowerShellTool/                                                      │
│  ├── powershellSecurity.ts       # PowerShell 安全验证                      │
│  └── destructiveCommandWarning.ts # PowerShell 破坏性警告                   │
│                                                                             │
│  hooks/                                                                     │
│  ├── useCanUseTool.tsx           # 权限检查 Hook                            │
│  └── toolPermission/                                                        │
│      ├── PermissionContext.ts    # 权限上下文                               │
│      ├── permissionLogging.ts    # 权限日志                                 │
│      └── handlers/                                                          │
│          ├── interactiveHandler.ts   # 交互式处理                           │
│          ├── swarmWorkerHandler.ts   # Swarm Worker 处理                    │
│          └── coordinatorHandler.ts   # Coordinator 处理                     │
│                                                                             │
│  components/permissions/                                                    │
│  ├── PermissionRequest.tsx       # 权限请求入口组件                         │
│  ├── PermissionDialog.tsx        # 权限对话框基础                           │
│  ├── FallbackPermissionRequest.tsx # 默认回退组件                           │
│  └── [Tool]PermissionRequest/    # 各工具的权限请求组件                      │
│      ├── BashPermissionRequest.tsx                                        │
│      ├── FileEditPermissionRequest.tsx                                    │
│      └── ...                                                              │
│                                                                             │
│  services/tools/                                                            │
│  ├── toolExecution.ts            # 工具执行服务                             │
│  │   └── checkPermissionsAndCallTool()                                    │
│  └── toolHooks.ts                # 工具钩子                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 十、总结

Claude Code 的人类批准机制是一个**精心设计的多层次安全系统**，其核心特点包括：

1. **灵活的权限模式**：从完全交互式到全自动 AI 决策，适应不同使用场景

2. **多层次的安全检查**：
   - 规则引擎 (允许/拒绝/询问)
   - 工具特定的安全检查 (Bash 20+ 种验证)
   - AI 分类器 (两阶段 XML 分类)

3. **丰富的交互方式**：
   - 本地 UI 对话框
   - 远程 Bridge 批准 (claude.ai)
   - Channel 权限中继 (Telegram/iMessage)
   - Hooks 扩展点

4. **安全优先的设计**：
   - 默认拒绝
   - 绕过免疫的安全检查
   - 解析器差异防护
   - 拒绝限制和回退机制

5. **可扩展性**：
   - Hook 系统允许外部扩展
   - MCP 工具权限支持
   - 分类器规则可配置

这个设计展示了如何在 AI 辅助编程工具中平衡**效率**和**安全性**，既允许 AI 自动处理常规任务，又确保高危操作得到人类监督。
