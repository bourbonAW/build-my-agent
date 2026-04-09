# Claude Code 用户二次确认机制 - 架构深度分析

> 本文档深入分析 Claude Code CLI 中处理需要用户二次确认操作的完整架构，包括权限系统、UI 组件、异步流程和状态管理。

---

## 目录

1. [系统概述](#系统概述)
2. [核心类型定义](#核心类型定义)
3. [权限检查架构](#权限检查架构)
4. [UI 确认组件系统](#ui-确认组件系统)
5. [异步确认流程](#异步确认流程)
6. [工具特定实现](#工具特定实现)
7. [状态管理与通信](#状态管理与通信)
8. [完整架构图](#完整架构图)

---

## 系统概述

Claude Code 的用户确认系统是一个**分层、异步、多通道**的权限控制架构，设计目标包括：

- **安全性**：防止未经授权的危险操作（文件修改、命令执行等）
- **灵活性**：支持多种权限模式（交互式、自动模式、计划模式等）
- **可扩展性**：支持 hooks、分类器、MCP 工具等扩展机制
- **用户体验**：清晰的权限提示、便捷的配置方式

### 核心设计特点

1. **声明式权限**：工具通过 `checkPermissions()` 方法声明需要确认的场景
2. **异步 Promise 流**：工具执行暂停等待用户输入，通过 Promise resolve 恢复
3. **多通道竞速**：用户确认、AI 分类器、自动化 Hook 并行执行，首个响应获胜
4. **防抖保护**：确保同一权限请求只被处理一次
5. **规则持久化**：用户可选择"记住选择"并保存为权限规则

---

## 核心类型定义

### 1. 权限上下文 (`ToolPermissionContext`)

```typescript
// src/types/permissions.ts
type PermissionMode = 
  | 'default'        // 标准权限检查
  | 'acceptEdits'    // 自动允许工作目录内的文件编辑
  | 'bypassPermissions' // 完全绕过权限检查
  | 'dontAsk'        // 不询问，自动拒绝
  | 'plan'           // 计划模式，需要用户批准
  | 'auto'           // 自动模式，使用 AI 分类器
  | 'bubble'         // 特殊模式

type PermissionBehavior = 'allow' | 'deny' | 'ask'

type PermissionDecision<Input> =
  | PermissionAllowDecision<Input>  // { behavior: 'allow', ... }
  | PermissionAskDecision<Input>    // { behavior: 'ask', message, ... }
  | PermissionDenyDecision          // { behavior: 'deny', message, ... }
```

### 2. 工具接口定义

```typescript
// src/Tool.ts
export type Tool<...> = {
  // ... 其他属性
  
  /**
   * 确定是否询问用户权限。在 validateInput() 通过后调用。
   * 通用权限逻辑在 permissions.ts 中，此方法包含工具特定逻辑。
   */
  checkPermissions(
    input: z.infer<Input>,
    context: ToolUseContext,
  ): Promise<PermissionResult>
  
  /** 当工具执行不可逆操作时返回 true */
  isDestructive?(input: z.infer<Input>): boolean
  
  /** 当工具需要用户交互才能完成时返回 true */
  requiresUserInteraction?(): boolean
}
```

### 3. 权限请求对象

```typescript
// src/components/permissions/PermissionRequest.tsx
export type ToolUseConfirm<Input extends AnyObject = AnyObject> = {
  assistantMessage: AssistantMessage;
  tool: Tool<Input>;
  description: string;
  input: z.infer<Input>;
  toolUseContext: ToolUseContext;
  toolUseID: string;
  permissionResult: PermissionDecision;
  permissionPromptStartTimeMs: number;
  
  // 用户交互回调
  onUserInteraction(): void;
  onAbort(): void;
  
  // 决策回调
  onAllow(updatedInput: z.infer<Input>, permissionUpdates: PermissionUpdate[], feedback?: string): void;
  onReject(feedback?: string): void;
  recheckPermission(): Promise<void>;
};
```

---

## 权限检查架构

### 1. 主入口点 (`hasPermissionsToUseTool`)

```typescript
// src/utils/permissions/permissions.ts
export const hasPermissionsToUseTool: CanUseToolFn = async (
  tool, input, context, assistantMessage, toolUseID
): Promise<PermissionDecision> => {
  // 1. 执行工具特定的 checkPermissions
  const result = await hasPermissionsToUseToolInner(tool, input, context)
  
  // 2. 处理 dontAsk 模式 - 将 ask 转为 deny
  if (result.behavior === 'ask' && context.mode === 'dontAsk') {
    return { behavior: 'deny', ... }
  }
  
  // 3. 处理 auto 模式 - 使用分类器自动决策
  if (result.behavior === 'ask' && context.mode === 'auto') {
    return handleAutoMode(result, tool, input, context)
  }
  
  // 4. 处理后台代理（无法显示 UI）
  if (result.behavior === 'ask' && context.shouldAvoidPermissionPrompts) {
    return runPermissionRequestHooksForHeadlessAgent(...)
  }
  
  return result
}
```

### 2. 权限处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     useCanUseTool Hook                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 1. 创建权限上下文 (createPermissionContext)               │  │
│  │ 2. 检查权限 (hasPermissionsToUseTool)                    │  │
│  │                                                          │  │
│  │    ├─ behavior: 'allow' → 直接 resolve(allow)           │  │
│  │    ├─ behavior: 'deny'  → 直接 resolve(deny)            │  │
│  │    └─ behavior: 'ask'   → 路由到对应处理器              │  │
│  │                                                          │  │
│  │       ├─ Coordinator 模式 → handleCoordinatorPermission │  │
│  │       ├─ Swarm Worker   → handleSwarmWorkerPermission   │  │
│  │       └─ 交互式模式     → handleInteractivePermission   │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3. 三种权限处理模式

#### A. 交互式处理 (`interactiveHandler.ts`)

适用于主代理（main agent），显示 UI 对话框让用户确认：

```typescript
function handleInteractivePermission(params, resolve): void {
  const { resolve: resolveOnce, claim } = createResolveOnce(resolve);
  
  // 1. 将权限请求推送到队列
  ctx.pushToQueue({
    tool, input, description,
    permissionResult: result,
    
    onUserInteraction() {
      // 用户开始交互，停止分类器
      clearClassifierChecking(ctx.toolUseID);
    },
    
    async onAllow(updatedInput, permissionUpdates, feedback) {
      if (!claim()) return; // 确保只处理一次
      
      // 用户允许，持久化权限更新
      await ctx.persistPermissions(permissionUpdates);
      resolveOnce(ctx.buildAllow(updatedInput));
    },
    
    onReject(feedback) {
      if (!claim()) return;
      resolveOnce(ctx.cancelAndAbort(feedback));
    },
    
    onAbort() {
      if (!claim()) return;
      resolveOnce(ctx.cancelAndAbort(undefined, true));
    }
  });
  
  // 2. 启动并行检查（与 UI 竞速）
  // - 权限 Hooks
  // - 分类器检查
  // - Bridge 转发
  // - Channel 转发
}
```

#### B. Coordinator 处理 (`coordinatorHandler.ts`)

适用于协调器工作器，先等待自动化检查再决定是否显示对话框：

```typescript
async function handleCoordinatorPermission(params): Promise<PermissionDecision | null> {
  // 1. 先运行权限 hooks
  const hookResult = await ctx.runHooks(...);
  if (hookResult) return hookResult;
  
  // 2. 运行分类器检查
  const classifierResult = await ctx.tryClassifier(...);
  if (classifierResult) return classifierResult;
  
  // 3. 都没有决策，返回 null，让调用方显示对话框
  return null;
}
```

#### C. Swarm Worker 处理 (`swarmWorkerHandler.ts`)

适用于代理群工作器，将权限请求转发给领导者：

```typescript
async function handleSwarmWorkerPermission(params): Promise<PermissionDecision | null> {
  // 1. 先尝试分类器自动批准
  const classifierResult = await ctx.tryClassifier(...);
  if (classifierResult) return classifierResult;
  
  // 2. 通过 mailbox 向领导者发送权限请求
  const request = createPermissionRequest({ toolName, toolUseId, input, ... });
  
  return new Promise(resolve => {
    // 注册回调等待领导者响应
    registerPermissionCallback({
      requestId: request.id,
      onAllow(...) { resolve(...) },
      onReject(...) { resolve(...) }
    });
  });
}
```

---

## UI 确认组件系统

### 1. 组件层次结构

```
PermissionRequest (src/components/permissions/PermissionRequest.tsx)
├── 工具类型路由 (permissionComponentForTool)
│   ├── BashPermissionRequest
│   ├── FileEditPermissionRequest
│   ├── FileWritePermissionRequest
│   ├── PowerShellPermissionRequest
│   ├── WebFetchPermissionRequest
│   ├── NotebookEditPermissionRequest
│   ├── SkillPermissionRequest
│   ├── AskUserQuestionPermissionRequest
│   └── FallbackPermissionRequest
└── PermissionDialog (通用对话框容器)
    ├── PermissionRequestTitle
    └── 子组件内容区域
```

### 2. 通用权限提示组件

```typescript
// src/components/permissions/PermissionPrompt.tsx
type PermissionPromptOption<T> = {
  value: T;
  label: ReactNode;
  feedbackConfig?: { 
    type: 'accept' | 'reject'; 
    placeholder?: string 
  };
  keybinding?: KeybindingAction;
};

export function PermissionPrompt<T>({
  options,
  onSelect,
  onCancel,
  question,
  toolAnalyticsContext
}) {
  // 处理选项选择、反馈输入、键盘快捷键
  // 支持 Tab 切换反馈输入模式
}
```

### 3. BashPermissionRequest 详解

```typescript
// src/components/permissions/BashPermissionRequest/BashPermissionRequest.tsx
export function BashPermissionRequest(props) {
  const { command, description } = BashTool.inputSchema.parse(input);
  
  // 检测 sed 编辑命令，转到专用组件
  const sedInfo = parseSedEditCommand(command);
  if (sedInfo) return <SedEditPermissionRequest ... />;
  
  // 使用 PermissionExplainer 显示命令解释
  const explainerState = usePermissionExplainerUI(...);
  
  // 生成选项（yes/yes-apply-suggestions/no）
  const options = bashToolUseOptions({ ... });
  
  // 显示分类器状态
  const classifierSubtitle = toolUseConfirm.classifierAutoApproved 
    ? <Text>✓ Auto-approved</Text>
    : toolUseConfirm.classifierCheckInProgress 
      ? <ClassifierCheckingSubtitle />
      : undefined;
  
  return (
    <PermissionDialog title="Bash command" subtitle={classifierSubtitle}>
      <Text>{command}</Text>
      <PermissionExplainerContent ... />
      <PermissionRuleExplanation ... />
      <Select options={options} ... />
    </PermissionDialog>
  );
}
```

### 4. 文件权限对话框

```typescript
// src/components/permissions/FilePermissionDialog/FilePermissionDialog.tsx
export function FilePermissionDialog<T>({
  toolUseConfirm,    // 包含 onAllow/onReject 回调
  title, subtitle, question,
  content,           // 差异预览等内容
  path,
  ideDiffSupport,    // IDE 差异支持配置
  ...
}: FilePermissionDialogProps<T>) {
  // 1. 处理 IDE diff 支持
  const ideDiffConfig = useMemo(() => ideDiffSupport?.getConfig(parsedInput), ...);
  const { closeTabInIDE, showingDiffInIDE } = useDiffInIDE(diffParams);
  
  // 2. 如果在 IDE 中显示 diff，渲染替代提示
  if (showingDiffInIDE) {
    return <ShowInIDEPrompt ... />;
  }
  
  // 3. 常规对话框渲染
  return (
    <PermissionDialog title={title} subtitle={subtitle}>
      {content}  {/* 差异预览 */}
      <Select options={options} onChange={...} />
    </PermissionDialog>
  );
}
```

---

## 异步确认流程

### 1. 完整流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           工具调用开始                                   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        validateInput() - 输入验证                        │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      checkPermissions() - 权限检查                       │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
   ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
   │   'allow'   │        │   'deny'    │        │    'ask'    │
   └──────┬──────┘        └──────┬──────┘        └──────┬──────┘
          │                       │                       │
          ▼                       ▼                       ▼
   ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
   │  直接执行   │        │ 返回拒绝结果 │        │ 显示权限对话框│
   │  工具调用   │        │             │        │             │
   └─────────────┘        └─────────────┘        └──────┬──────┘
                                                        │
                                          ┌─────────────┼─────────────┐
                                          │             │             │
                                          ▼             ▼             ▼
                                    ┌─────────┐  ┌─────────┐  ┌─────────┐
                                    │  Allow  │  │ Reject  │  │  Abort  │
                                    └────┬────┘  └────┬────┘  └────┬────┘
                                         │            │            │
                                         ▼            ▼            ▼
                                    ┌─────────┐  ┌─────────┐  ┌─────────┐
                                    │执行工具  │  │ 拒绝    │  │ 中止    │
                                    │调用     │  │         │  │         │
                                    └─────────┘  └─────────┘  └─────────┘
```

### 2. Promise 流实现

```typescript
// src/hooks/useCanUseTool.tsx
function useCanUseTool(setToolUseConfirmQueue, setToolPermissionContext) {
  return async (tool, input, toolUseContext, assistantMessage, toolUseID, forceDecision) => 
    new Promise(resolve => {
      // 1. 创建权限上下文
      const ctx = createPermissionContext(...);
      
      // 2. 检查权限
      const result = await hasPermissionsToUseTool(tool, input, ...);
      
      // 3. 根据结果处理
      switch (result.behavior) {
        case 'allow':
          resolve(ctx.buildAllow(result.updatedInput ?? input));
          break;
          
        case 'deny':
          resolve(result);
          break;
          
        case 'ask':
          // 4. 显示权限对话框，等待用户交互
          handleInteractivePermission({ ctx, description, result, ... }, resolve);
          break;
      }
    });
}
```

### 3. 回调绑定机制

```typescript
// 工具执行等待 Promise
const decision = await canUseTool(tool, input, toolUseContext, ...);

// UI 组件通过回调返回结果
toolUseConfirm.onAllow = (updatedInput, permissionUpdates, feedback) => {
  resolve({ behavior: 'allow', updatedInput, ... });
};

toolUseConfirm.onReject = (feedback) => {
  resolve({ behavior: 'deny', message: feedback, ... });
};

toolUseConfirm.onAbort = () => {
  resolve({ type: 'abort', ... });
};
```

---

## 工具特定实现

### 1. BashTool - 危险命令确认

```typescript
// src/tools/BashTool/bashPermissions.ts
export async function bashToolHasPermission(
  tool: BashToolType,
  input: BashToolInput,
  context: ToolPermissionContext,
): Promise<PermissionResult> {
  // 1. 检查是否被沙箱覆盖
  if (input.dangerouslyDisableSandbox && SandboxManager.isSandboxingEnabled()) {
    return { behavior: 'ask', decisionReason: { type: 'sandboxOverride', ... } };
  }
  
  // 2. 检查命令模式
  const modeResult = checkPermissionMode(command, context);
  if (modeResult) return modeResult;
  
  // 3. 检查前缀规则
  const prefixRule = checkPrefixRules(command, context);
  if (prefixRule) return prefixRule;
  
  // 4. 检查复合命令权限（cd && git status && ...）
  const compoundResult = await checkCompoundCommandPermissions(...);
  if (compoundResult) return compoundResult;
  
  // 5. 检查特定命令语义（rm -rf / 等危险命令）
  const semanticsResult = checkCommandSemantics(...);
  if (semanticsResult) return semanticsResult;
  
  // 6. 为分类器准备待检查的命令
  return {
    behavior: 'ask',
    pendingClassifierCheck: { command, cwd, descriptions },
    suggestions: generateSuggestions(command, ...)
  };
}
```

### 2. FileEditTool / FileWriteTool

```typescript
// src/tools/FileEditTool/FileEditTool.ts
export const FileEditTool = buildTool({
  name: FILE_EDIT_TOOL_NAME,
  
  async checkPermissions(input, context): Promise<PermissionDecision> {
    return checkWritePermissionForTool(
      FileEditTool, input, context.getAppState().toolPermissionContext
    );
  },
  // ...
});

// src/utils/permissions/filesystem.ts
export function checkWritePermissionForTool(
  tool: Tool,
  input: { file_path: string },
  context: ToolPermissionContext
): PermissionDecision {
  const filePath = expandPath(input.file_path);
  
  // 1. 路径安全检查（危险文件保护）
  const safetyCheck = checkPathSafetyForAutoEdit(filePath);
  if (!safetyCheck.safe) {
    return { behavior: 'ask', decisionReason: { type: 'safetyCheck', ... } };
  }
  
  // 2. 工作目录验证
  if (!pathInAllowedWorkingPath(filePath, context)) {
    return { behavior: 'ask', decisionReason: { type: 'workingDir', ... } };
  }
  
  // 3. 规则匹配
  const denyRule = matchingRuleForInput(filePath, context, 'edit', 'deny');
  if (denyRule) return { behavior: 'deny', decisionReason: { type: 'rule', rule: denyRule } };
  
  const allowRule = matchingRuleForInput(filePath, context, 'edit', 'allow');
  if (allowRule) return { behavior: 'allow', decisionReason: { type: 'rule', rule: allowRule } };
  
  // 4. 默认询问
  return { behavior: 'ask', suggestions: generateSuggestions(...) };
}
```

### 3. 危险文件保护

```typescript
// 受保护的危险文件列表
const DANGEROUS_FILES = [
  '.gitconfig',
  '.bashrc',
  '.zshrc',
  '.profile',
  '.bash_profile',
  '.bash_login',
  '.bash_logout',
  '.zshenv',
  '.zlogin',
  '.zlogout',
  '.zprofile',
  '.vimrc',
  '.npmrc',
  '.pypirc',
  'id_rsa',
  'id_dsa',
  'id_ecdsa',
  'id_ed25519',
  '.ssh/config',
  'known_hosts',
  'authorized_keys',
  ...
];

const DANGEROUS_DIRECTORIES = [
  '.git',
  '.vscode',
  '.idea',
  '.claude',
  'node_modules/.bin',
  '.ssh',
  ...
];
```

---

## 状态管理与通信

### 1. 权限队列管理

```typescript
// src/components/REPL.tsx
const [toolUseConfirmQueue, setToolUseConfirmQueue] = useState<ToolUseConfirm[]>([]);

// 当前展示的权限对话框
const toolPermissionOverlay = focusedInputDialog === 'tool-permission' 
  ? <PermissionRequest 
      key={toolUseConfirmQueue[0]?.toolUseID}
      onDone={() => setToolUseConfirmQueue(([_, ...tail]) => tail)}
      toolUseConfirm={toolUseConfirmQueue[0]!}
      toolUseContext={getToolUseContext(...)}
    /> 
  : null;
```

### 2. 输入处理 Hooks

```typescript
// src/hooks/useTextInput.ts
export function useTextInput(options: UseTextInputOptions) {
  const [value, setValue] = useState(options.defaultValue ?? '');
  const [cursor, setCursor] = useState(new Cursor(value, 0, 0));
  
  // 处理键盘输入
  useInput((input, key) => {
    if (key.return) {
      options.onSubmit(value);
    } else if (key.tab) {
      // 切换反馈输入模式
    } else if (key.escape) {
      options.onCancel?.();
    } else {
      // 字符输入处理
      const newValue = value.slice(0, cursor.col) + input + value.slice(cursor.col);
      setValue(newValue);
      setCursor(cursor.right(newValue));
    }
  });
  
  return { value, cursor, ... };
}
```

### 3. Select 组件状态

```typescript
// src/components/CustomSelect/select.tsx
type OptionWithDescription<T> = 
  | (BaseOption<T> & { type?: 'text' })
  | (BaseOption<T> & {
      type: 'input';
      onChange: (value: string) => void;
      placeholder?: string;
    });

// 支持：
// - 键盘导航（上下箭头）
// - 输入模式（Tab 切换）
// - 紧凑/展开布局
// - 描述文本显示
```

---

## 完整架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户交互层                                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ BashPermission  │  │ FilePermission  │  │    Fallback     │              │
│  │    Request      │  │     Dialog      │  │   Permission    │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                ▼                                            │
│                   ┌─────────────────────┐                                   │
│                   │   PermissionPrompt  │                                   │
│                   │    (通用确认对话框)  │                                   │
│                   └──────────┬──────────┘                                   │
└──────────────────────────────┼─────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼─────────────────────────────────────────────┐
│                              │              权限处理层                       │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      useCanUseTool Hook                              │   │
│  │  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────┐ │   │
│  │  │ hasPermissions- │ │ handleCoordin-  │ │  handleSwarmWorker      │ │   │
│  │  │   ToUseTool     │ │ atorPermission  │ │    Permission           │ │   │
│  │  └────────┬────────┘ └─────────────────┘ └─────────────────────────┘ │   │
│  │           │                                                          │   │
│  │           ▼                                                          │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │            handleInteractivePermission                         │  │   │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │   │
│  │  │  │  Hooks   │ │Classifier│ │  Bridge  │ │ Channel  │            │  │   │
│  │  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼─────────────────────────────────────────────┐
│                              │              工具检查层                       │
│                              ▼                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│  │   BashTool   │ │  FileEdit    │ │  FileWrite   │ │   WebFetch   │       │
│  │ checkPermis- │ │ checkPermis- │ │ checkPermis- │ │ checkPermis- │       │
│  │   sions()    │ │   sions()    │ │   sions()    │ │   sions()    │       │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘       │
│         │                │                │                │               │
│         └────────────────┴────────────────┴────────────────┘               │
│                                     │                                       │
│                                     ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              通用权限检查 (permissions.ts)                           │   │
│  │  ┌─────────────────┐ ┌─────────────────┐ ┌───────────────────────┐  │   │
│  │  │   Allow Rules   │ │   Deny Rules    │ │  Working Directory    │  │   │
│  │  │     Check       │ │     Check       │ │      Check            │  │   │
│  │  └─────────────────┘ └─────────────────┘ └───────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 关键设计模式总结

### 1. Resolve-Once 模式

```typescript
function createResolveOnce<T>(resolve: (value: T) => void) {
  let resolved = false;
  return {
    resolve: (value: T) => {
      if (!resolved) {
        resolved = true;
        resolve(value);
      }
    },
    isResolved: () => resolved,
    claim: () => {
      if (resolved) return false;
      resolved = true;
      return true;
    }
  };
}
```

防止竞态条件下的多次决议。

### 2. 队列模式

权限请求按 FIFO 顺序处理，通过 React state 管理队列：

```typescript
const [queue, setQueue] = useState<ToolUseConfirm[]>([]);

// 入队
setQueue(prev => [...prev, newRequest]);

// 出队（用户响应后）
setQueue(([_, ...tail]) => tail);
```

### 3. 回调注入

工具执行提供回调，UI 组件调用回调返回结果：

```typescript
// 工具执行侧
const decision = await new Promise(resolve => {
  showPermissionDialog({
    onAllow: (input) => resolve({ behavior: 'allow', input }),
    onReject: (reason) => resolve({ behavior: 'deny', reason })
  });
});

// UI 组件侧
<Select onChange={(option) => {
  if (option.value === 'yes') onAllow(input);
  if (option.value === 'no') onReject();
}} />
```

### 4. 竞速处理

用户交互、Bridge、Hooks、Classifier 同时运行，首个响应获胜：

```typescript
// 并行启动多个检查
void (async () => {
  const hookResult = await runHooks();
  if (hookResult) resolve(hookResult);
})();

void (async () => {
  const classifierResult = await runClassifier();
  if (classifierResult) resolve(classifierResult);
})();

// UI 交互也会调用 resolve
onAllow: () => resolve({ behavior: 'allow' });
```

---

## 实现建议

基于 Claude Code 的架构，实现类似的确认机制时应考虑：

1. **分层架构**：工具声明 → 权限检查 → UI 展示 → 用户决策 → 结果传递
2. **异步 Promise 流**：工具执行暂停等待用户输入，通过 Promise resolve 恢复
3. **多通道竞速**：支持多种决策来源（用户、分类器、Hook）并行执行
4. **防抖保护**：确保同一请求只被处理一次
5. **状态分离**：权限队列状态与 UI 渲染状态分离
6. **工具特定 UI**：不同工具类型可以有专门的确认 UI 组件
7. **规则持久化**：支持用户保存"记住选择"的权限规则
8. **后台代理支持**：考虑无 UI 环境（后台任务、协调器）的处理方式
