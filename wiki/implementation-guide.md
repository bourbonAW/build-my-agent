# 用户确认机制实现指南

基于 Claude Code 架构的精简实现方案

---

## 概述

本指南提供一个简化的、可用于构建自己 Agent 系统的用户确认机制实现方案。

---

## 核心架构

### 1. 类型定义

```typescript
// types/permissions.ts

/** 权限决策类型 */
export type PermissionDecision<T = unknown> = 
  | { type: 'allow'; data?: T }
  | { type: 'deny'; reason: string }
  | { type: 'ask'; message: string; options?: PermissionOption[] };

/** 权限选项 */
export interface PermissionOption {
  value: string;
  label: string;
  description?: string;
  requireFeedback?: boolean;
}

/** 工具接口 */
export interface Tool<Input = unknown, Output = unknown> {
  name: string;
  description: string;
  
  /** 验证输入 */
  validateInput(input: unknown): Input;
  
  /** 检查权限 - 核心方法 */
  checkPermissions(input: Input, context: ToolContext): Promise<PermissionDecision>;
  
  /** 执行工具 */
  execute(input: Input, context: ToolContext): Promise<Output>;
  
  /** 是否需要用户交互 */
  requiresUserInteraction?(): boolean;
}

/** 工具上下文 */
export interface ToolContext {
  userId: string;
  sessionId: string;
  permissionRules: PermissionRule[];
  logger: Logger;
}

/** 权限规则 */
export interface PermissionRule {
  id: string;
  toolName: string;
  pattern: string | RegExp;
  action: 'allow' | 'deny' | 'ask';
  createdAt: Date;
}
```

### 2. 权限检查引擎

```typescript
// engine/PermissionEngine.ts

export class PermissionEngine {
  constructor(
    private ruleStore: RuleStore,
    private classifier?: AutoClassifier,
    private logger?: Logger
  ) {}

  async checkPermission<T>(
    tool: Tool<T>,
    input: T,
    context: ToolContext
  ): Promise<PermissionDecision<T>> {
    // 1. 获取工具特定的权限检查
    const toolDecision = await tool.checkPermissions(input, context);
    
    if (toolDecision.type !== 'ask') {
      return toolDecision;
    }

    // 2. 检查用户自定义规则
    const ruleDecision = this.checkRules(tool, input, context.permissionRules);
    if (ruleDecision) {
      return ruleDecision;
    }

    // 3. 自动分类器（可选）
    if (this.classifier) {
      const autoDecision = await this.classifier.classify(tool, input);
      if (autoDecision.confidence === 'high') {
        this.logger?.info(`Auto ${autoDecision.action} for ${tool.name}`);
        return { 
          type: autoDecision.action, 
          data: autoDecision.action === 'allow' ? input : undefined 
        };
      }
    }

    // 4. 需要用户确认
    return {
      type: 'ask',
      message: toolDecision.type === 'ask' 
        ? toolDecision.message 
        : `Confirm action: ${tool.description}`,
      options: [
        { value: 'allow', label: 'Yes' },
        { value: 'allow-once', label: 'Yes, just this once' },
        { value: 'deny', label: 'No' },
        { 
          value: 'allow-always', 
          label: 'Yes, and remember this choice',
          requireFeedback: true 
        }
      ]
    };
  }

  private checkRules<T>(
    tool: Tool<T>,
    input: T,
    rules: PermissionRule[]
  ): PermissionDecision<T> | null {
    for (const rule of rules) {
      if (rule.toolName !== tool.name) continue;
      
      const inputStr = JSON.stringify(input);
      const matches = typeof rule.pattern === 'string'
        ? inputStr.includes(rule.pattern)
        : rule.pattern.test(inputStr);
      
      if (matches) {
        return { 
          type: rule.action, 
          data: rule.action === 'allow' ? input : undefined 
        };
      }
    }
    return null;
  }
}
```

### 3. 工具执行器

```typescript
// engine/ToolExecutor.ts

export interface ExecutionResult<T> {
  success: boolean;
  data?: T;
  error?: string;
  decision?: PermissionDecision;
}

export class ToolExecutor {
  constructor(
    private permissionEngine: PermissionEngine,
    private uiRenderer: UIRenderer,
    private logger: Logger
  ) {}

  async execute<TInput, TOutput>(
    tool: Tool<TInput, TOutput>,
    rawInput: unknown,
    context: ToolContext
  ): Promise<ExecutionResult<TOutput>> {
    try {
      // 1. 验证输入
      const input = tool.validateInput(rawInput);
      
      // 2. 权限检查
      const decision = await this.permissionEngine.checkPermission(
        tool, input, context
      );

      if (decision.type === 'deny') {
        return {
          success: false,
          error: `Permission denied: ${decision.reason}`,
          decision
        };
      }

      let finalInput = input;

      // 3. 需要用户确认
      if (decision.type === 'ask') {
        const userDecision = await this.requestUserConfirmation(
          tool, 
          decision.message, 
          decision.options
        );

        if (userDecision.action === 'deny') {
          return {
            success: false,
            error: 'User denied permission',
            decision: { type: 'deny', reason: 'User denied' }
          };
        }

        // 保存用户规则
        if (userDecision.saveRule) {
          await this.savePermissionRule(
            context.userId,
            tool.name,
            input,
            userDecision.action === 'allow' ? 'allow' : 'ask'
          );
        }

        finalInput = userDecision.updatedInput ?? input;
      }

      // 4. 执行工具
      this.logger.info(`Executing tool: ${tool.name}`);
      const output = await tool.execute(finalInput, context);

      return {
        success: true,
        data: output,
        decision: { type: 'allow' }
      };

    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : String(error)
      };
    }
  }

  private async requestUserConfirmation<T>(
    tool: Tool<T>,
    message: string,
    options?: PermissionOption[]
  ): Promise<UserDecision<T>> {
    return new Promise((resolve) => {
      this.uiRenderer.renderPermissionPrompt({
        toolName: tool.name,
        message,
        options: options ?? [
          { value: 'allow', label: 'Yes' },
          { value: 'deny', label: 'No' }
        ],
        onDecision: (decision) => {
          resolve(decision);
        }
      });
    });
  }

  private async savePermissionRule(
    userId: string,
    toolName: string,
    input: unknown,
    action: 'allow' | 'deny' | 'ask'
  ): Promise<void> {
    const rule: PermissionRule = {
      id: generateId(),
      toolName,
      pattern: JSON.stringify(input),
      action,
      createdAt: new Date()
    };
    await this.permissionEngine.ruleStore.save(userId, rule);
  }
}

interface UserDecision<T> {
  action: 'allow' | 'deny';
  updatedInput?: T;
  saveRule?: boolean;
}
```

---

## UI 组件实现

### 基于 React + Ink（CLI 界面）

```typescript
// ui/PermissionPrompt.tsx
import React, { useState } from 'react';
import { Box, Text } from 'ink';
import SelectInput from 'ink-select-input';
import TextInput from 'ink-text-input';

interface PermissionPromptProps {
  toolName: string;
  message: string;
  options: PermissionOption[];
  onDecision: (decision: UserDecision) => void;
}

export const PermissionPrompt: React.FC<PermissionPromptProps> = ({
  toolName,
  message,
  options,
  onDecision
}) => {
  const [feedbackMode, setFeedbackMode] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [selectedOption, setSelectedOption] = useState<PermissionOption | null>(null);

  const handleSelect = (option: PermissionOption) => {
    if (option.requireFeedback && !feedbackMode) {
      setSelectedOption(option);
      setFeedbackMode(true);
      return;
    }

    const decision: UserDecision = {
      action: option.value.startsWith('allow') ? 'allow' : 'deny',
      saveRule: option.value === 'allow-always',
      feedback: feedbackMode ? feedback : undefined
    };

    onDecision(decision);
  };

  if (feedbackMode) {
    return (
      <Box flexDirection="column">
        <Text color="yellow">{message}</Text>
        <Text>Provide feedback (optional):</Text>
        <TextInput
          value={feedback}
          onChange={setFeedback}
          onSubmit={() => handleSelect(selectedOption!)}
        />
      </Box>
    );
  }

  const selectItems = options.map(opt => ({
    label: opt.description ? `${opt.label} - ${opt.description}` : opt.label,
    value: opt.value
  }));

  return (
    <Box flexDirection="column" borderStyle="single" padding={1}>
      <Text bold color="cyan">Permission Required</Text>
      <Text color="gray">Tool: {toolName}</Text>
      <Text>{message}</Text>
      <SelectInput
        items={selectItems}
        onSelect={(item: { value: string }) => {
          const option = options.find(o => o.value === item.value);
          if (option) handleSelect(option);
        }}
      />
    </Box>
  );
};
```

### 基于 Web（浏览器界面）

```typescript
// ui/PermissionDialog.tsx (Web 版本)
import React, { useState } from 'react';

interface PermissionDialogProps {
  toolName: string;
  message: string;
  details?: React.ReactNode;
  options: PermissionOption[];
  onDecision: (decision: UserDecision) => void;
}

export const PermissionDialog: React.FC<PermissionDialogProps> = ({
  toolName,
  message,
  details,
  options,
  onDecision
}) => {
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [selectedValue, setSelectedValue] = useState<string | null>(null);

  const handleOptionClick = (option: PermissionOption) => {
    if (option.requireFeedback && !showFeedback) {
      setSelectedValue(option.value);
      setShowFeedback(true);
      return;
    }

    onDecision({
      action: option.value.startsWith('allow') ? 'allow' : 'deny',
      saveRule: option.value === 'allow-always',
      feedback: showFeedback ? feedback : undefined
    });
  };

  return (
    <div className="permission-dialog-overlay">
      <div className="permission-dialog">
        <h3>Permission Required: {toolName}</h3>
        <p className="permission-message">{message}</p>
        
        {details && (
          <div className="permission-details">
            {details}
          </div>
        )}

        {showFeedback ? (
          <div className="feedback-section">
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Why are you making this choice? (optional)"
            />
            <button onClick={() => {
              const option = options.find(o => o.value === selectedValue);
              if (option) handleOptionClick(option);
            }}>
              Confirm
            </button>
          </div>
        ) : (
          <div className="permission-options">
            {options.map(option => (
              <button
                key={option.value}
                className={`option-${option.value}`}
                onClick={() => handleOptionClick(option)}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
```

---

## 具体工具实现示例

### 1. 文件写入工具

```typescript
// tools/FileWriteTool.ts

export interface FileWriteInput {
  filePath: string;
  content: string;
  overwrite?: boolean;
}

export const FileWriteTool: Tool<FileWriteInput, { bytesWritten: number }> = {
  name: 'file_write',
  description: 'Write content to a file',

  validateInput(raw: unknown): FileWriteInput {
    const input = raw as FileWriteInput;
    if (!input.filePath) throw new Error('filePath is required');
    if (typeof input.content !== 'string') throw new Error('content must be a string');
    return {
      filePath: path.resolve(input.filePath),
      content: input.content,
      overwrite: input.overwrite ?? false
    };
  },

  async checkPermissions(input, context): Promise<PermissionDecision> {
    // 1. 检查文件是否存在
    const exists = await fs.access(input.filePath).then(() => true).catch(() => false);
    
    if (exists && !input.overwrite) {
      return {
        type: 'ask',
        message: `File ${path.basename(input.filePath)} already exists. Overwrite?`,
        options: [
          { value: 'allow', label: 'Yes, overwrite' },
          { value: 'deny', label: 'No, cancel' }
        ]
      };
    }

    // 2. 检查危险文件
    const dangerousFiles = ['.bashrc', '.zshrc', '.ssh/config', 'id_rsa'];
    const basename = path.basename(input.filePath);
    if (dangerousFiles.includes(basename)) {
      return {
        type: 'ask',
        message: `⚠️ Warning: ${basename} is a system configuration file. Edit with caution.`,
        options: [
          { value: 'allow', label: 'Yes, I understand the risk' },
          { value: 'deny', label: 'No, cancel' }
        ]
      };
    }

    // 3. 检查工作目录外写入
    const cwd = process.cwd();
    if (!input.filePath.startsWith(cwd)) {
      return {
        type: 'ask',
        message: `Write to file outside current directory: ${input.filePath}?`,
        options: [
          { value: 'allow', label: 'Yes' },
          { value: 'deny', label: 'No' }
        ]
      };
    }

    // 4. 默认允许
    return { type: 'allow' };
  },

  async execute(input, context): Promise<{ bytesWritten: number }> {
    await fs.mkdir(path.dirname(input.filePath), { recursive: true });
    await fs.writeFile(input.filePath, input.content, 'utf-8');
    
    context.logger.info(`Wrote ${input.content.length} bytes to ${input.filePath}`);
    
    return { bytesWritten: input.content.length };
  },

  isDestructive(input) {
    return true; // 文件写入是破坏性操作
  }
};
```

### 2. 命令执行工具

```typescript
// tools/BashTool.ts

export interface BashInput {
  command: string;
  cwd?: string;
  timeout?: number;
}

export const BashTool: Tool<BashInput, { stdout: string; stderr: string; exitCode: number }> = {
  name: 'bash',
  description: 'Execute a bash command',

  validateInput(raw: unknown): BashInput {
    const input = raw as BashInput;
    if (!input.command) throw new Error('command is required');
    return {
      command: input.command,
      cwd: input.cwd ? path.resolve(input.cwd) : process.cwd(),
      timeout: input.timeout ?? 60000
    };
  },

  async checkPermissions(input, context): Promise<PermissionDecision> {
    const cmd = input.command.trim();
    
    // 1. 检查危险命令
    const dangerousPatterns = [
      { pattern: /rm\s+-rf\s+\//, message: 'Attempting to delete entire filesystem!' },
      { pattern: />\s*\/dev\/(null|zero|random)/, message: 'Writing to device files' },
      { pattern: /dd\s+if=.*of=\/dev\//, message: 'Direct device write with dd' },
      { pattern: /:(){ :|:& };:/, message: 'Fork bomb detected' },
      { pattern: /mkfs\./, message: 'Filesystem formatting command' },
      { pattern: /curl.*\|\s*(bash|sh|zsh)/, message: 'Piping curl to shell' }
    ];

    for (const { pattern, message } of dangerousPatterns) {
      if (pattern.test(cmd)) {
        return {
          type: 'ask',
          message: `⚠️ Dangerous command detected: ${message}\n\n${cmd}`,
          options: [
            { value: 'deny', label: 'Block (Recommended)' },
            { value: 'allow', label: 'Execute anyway' }
          ]
        };
      }
    }

    // 2. 检查删除操作
    if (/^rm\s+/.test(cmd) && !cmd.includes('-i')) {
      return {
        type: 'ask',
        message: `Delete command: ${cmd}\n\nThis will permanently delete files.`,
        options: [
          { value: 'allow', label: 'Yes, delete' },
          { value: 'deny', label: 'No, cancel' }
        ]
      };
    }

    // 3. 检查网络操作
    if (/^(curl|wget|scp|rsync)\s+/.test(cmd)) {
      return {
        type: 'ask',
        message: `Network command: ${cmd}`,
        options: [
          { value: 'allow', label: 'Yes' },
          { value: 'deny', label: 'No' }
        ]
      };
    }

    // 4. 默认允许简单命令
    return { type: 'allow' };
  },

  async execute(input, context) {
    const { stdout, stderr, exitCode } = await execa('bash', ['-c', input.command], {
      cwd: input.cwd,
      timeout: input.timeout,
      reject: false
    });

    return { stdout, stderr, exitCode };
  },

  isDestructive(input) {
    const destructivePatterns = [/rm\s/, /mv\s/, />\s*/, /mkfs/, /dd\s/];
    return destructivePatterns.some(p => p.test(input.command));
  }
};
```

### 3. 子代理创建工具

```typescript
// tools/AgentTool.ts

export interface AgentInput {
  prompt: string;
  type?: 'coder' | 'explore' | 'plan';
  allowedTools?: string[];
}

export const AgentTool: Tool<AgentInput, { result: string }> = {
  name: 'agent',
  description: 'Spawn a sub-agent to complete a task',

  validateInput(raw: unknown): AgentInput {
    const input = raw as AgentInput;
    if (!input.prompt) throw new Error('prompt is required');
    return {
      prompt: input.prompt,
      type: input.type ?? 'coder',
      allowedTools: input.allowedTools
    };
  },

  async checkPermissions(input, context): Promise<PermissionDecision> {
    // 检查代理类型限制
    const allowedTypes = ['coder', 'explore', 'plan'];
    if (!allowedTypes.includes(input.type!)) {
      return {
        type: 'deny',
        reason: `Unknown agent type: ${input.type}`
      };
    }

    // 检查工具权限范围
    if (input.allowedTools) {
      const sensitiveTools = ['Bash', 'FileWrite', 'FileDelete'];
      const hasSensitive = input.allowedTools.some(t => 
        sensitiveTools.some(s => t.includes(s))
      );
      
      if (hasSensitive) {
        return {
          type: 'ask',
          message: `Sub-agent will have access to sensitive tools: ${input.allowedTools.join(', ')}`,
          options: [
            { value: 'allow', label: 'Yes' },
            { value: 'deny', label: 'No' }
          ]
        };
      }
    }

    return {
      type: 'ask',
      message: `Create ${input.type} agent to: ${input.prompt.substring(0, 100)}...`,
      options: [
        { value: 'allow', label: 'Yes' },
        { value: 'deny', label: 'No' }
      ]
    };
  },

  async execute(input, context) {
    const agent = new SubAgent({
      type: input.type,
      allowedTools: input.allowedTools,
      parentContext: context
    });

    const result = await agent.run(input.prompt);
    return { result };
  }
};
```

---

## 高级功能

### 1. 自动分类器

```typescript
// engine/AutoClassifier.ts

interface ClassifierResult {
  action: 'allow' | 'deny' | 'ask';
  confidence: 'high' | 'medium' | 'low';
  reason: string;
}

export class AutoClassifier {
  constructor(private llmClient: LLMClient) {}

  async classify<T>(tool: Tool<T>, input: T): Promise<ClassifierResult> {
    // 快速路径：基于模式的简单检查
    const fastResult = this.fastCheck(tool, input);
    if (fastResult) return fastResult;

    // 使用 LLM 进行分类
    const prompt = `
You are a security classifier for an AI agent system.
Tool: ${tool.name}
Description: ${tool.description}
Input: ${JSON.stringify(input, null, 2)}

Classify this action as one of:
- allow: Safe, routine operation
- deny: Dangerous, malicious, or inappropriate
- ask: Uncertain, requires human review

Respond in JSON format:
{
  "action": "allow|deny|ask",
  "confidence": "high|medium|low",
  "reason": "brief explanation"
}
`;

    const response = await this.llmClient.complete(prompt);
    return JSON.parse(response);
  }

  private fastCheck<T>(tool: Tool<T>, input: T): ClassifierResult | null {
    const inputStr = JSON.stringify(input);
    
    // 已知安全模式
    const safePatterns = [
      { tool: 'bash', pattern: /^git\s+(status|log|show|diff)/ },
      { tool: 'bash', pattern: /^ls\s/ },
      { tool: 'bash', pattern: /^cat\s/ },
      { tool: 'file_read', pattern: /\.md$/ },
      { tool: 'file_read', pattern: /\.txt$/ }
    ];

    for (const { tool: t, pattern } of safePatterns) {
      if (tool.name === t && pattern.test(inputStr)) {
        return { action: 'allow', confidence: 'high', reason: 'Known safe pattern' };
      }
    }

    // 已知危险模式
    const dangerousPatterns = [
      { tool: 'bash', pattern: /rm\s+-rf\s+\// },
      { tool: 'bash', pattern: /:(){ :|:& }:/ },
      { tool: 'bash', pattern: /mkfs\./ },
      { tool: 'file_write', pattern: /\.ssh\/authorized_keys/ }
    ];

    for (const { tool: t, pattern } of dangerousPatterns) {
      if (tool.name === t && pattern.test(inputStr)) {
        return { action: 'deny', confidence: 'high', reason: 'Known dangerous pattern' };
      }
    }

    return null;
  }
}
```

### 2. 权限规则持久化

```typescript
// storage/RuleStore.ts

export interface RuleStore {
  get(userId: string, toolName?: string): Promise<PermissionRule[]>;
  save(userId: string, rule: PermissionRule): Promise<void>;
  delete(userId: string, ruleId: string): Promise<void>;
}

// 文件存储实现
export class FileRuleStore implements RuleStore {
  constructor(private basePath: string) {}

  async get(userId: string, toolName?: string): Promise<PermissionRule[]> {
    const filePath = path.join(this.basePath, `${userId}.json`);
    
    try {
      const data = await fs.readFile(filePath, 'utf-8');
      const rules: PermissionRule[] = JSON.parse(data);
      
      if (toolName) {
        return rules.filter(r => r.toolName === toolName);
      }
      return rules;
    } catch {
      return [];
    }
  }

  async save(userId: string, rule: PermissionRule): Promise<void> {
    const filePath = path.join(this.basePath, `${userId}.json`);
    
    const rules = await this.get(userId);
    const existingIndex = rules.findIndex(r => 
      r.toolName === rule.toolName && r.pattern === rule.pattern
    );
    
    if (existingIndex >= 0) {
      rules[existingIndex] = rule;
    } else {
      rules.push(rule);
    }
    
    await fs.mkdir(this.basePath, { recursive: true });
    await fs.writeFile(filePath, JSON.stringify(rules, null, 2));
  }

  async delete(userId: string, ruleId: string): Promise<void> {
    const filePath = path.join(this.basePath, `${userId}.json`);
    const rules = await this.get(userId);
    const filtered = rules.filter(r => r.id !== ruleId);
    await fs.writeFile(filePath, JSON.stringify(filtered, null, 2));
  }
}
```

### 3. 批量确认

```typescript
// engine/BatchPermissionHandler.ts

interface BatchPermissionRequest {
  id: string;
  tool: Tool;
  input: unknown;
  decision?: PermissionDecision;
}

export class BatchPermissionHandler {
  private requests: Map<string, BatchPermissionRequest> = new Map();

  add(request: BatchPermissionRequest): void {
    this.requests.set(request.id, request);
  }

  async confirmAll(
    onBatchDecision: (decisions: Map<string, PermissionDecision>) => void
  ): Promise<void> {
    // 分组显示
    const grouped = this.groupByTool();
    
    for (const [toolName, requests] of grouped) {
      if (requests.length > 3) {
        // 批量确认
        const decision = await this.requestBatchConfirmation(toolName, requests);
        for (const req of requests) {
          req.decision = decision;
        }
      } else {
        // 单独确认
        for (const req of requests) {
          req.decision = await this.requestIndividualConfirmation(req);
        }
      }
    }

    const decisions = new Map<string, PermissionDecision>();
    for (const [id, req] of this.requests) {
      decisions.set(id, req.decision!);
    }
    
    onBatchDecision(decisions);
  }

  private groupByTool(): Map<string, BatchPermissionRequest[]> {
    const grouped = new Map<string, BatchPermissionRequest[]>();
    
    for (const req of this.requests.values()) {
      const existing = grouped.get(req.tool.name) ?? [];
      existing.push(req);
      grouped.set(req.tool.name, existing);
    }
    
    return grouped;
  }

  private async requestBatchConfirmation(
    toolName: string,
    requests: BatchPermissionRequest[]
  ): Promise<PermissionDecision> {
    return new Promise((resolve) => {
      // 显示批量确认 UI
      console.log(`\n${toolName}: ${requests.length} pending operations`);
      // ... UI 渲染
    });
  }
}
```

---

## 完整使用示例

```typescript
// main.ts
import { ToolExecutor } from './engine/ToolExecutor';
import { PermissionEngine } from './engine/PermissionEngine';
import { FileRuleStore } from './storage/RuleStore';
import { FileWriteTool } from './tools/FileWriteTool';
import { BashTool } from './tools/BashTool';

async function main() {
  // 初始化组件
  const ruleStore = new FileRuleStore('./data/rules');
  const permissionEngine = new PermissionEngine(ruleStore);
  const uiRenderer = new CLIRenderer(); // 或 WebRenderer
  const executor = new ToolExecutor(permissionEngine, uiRenderer, console);

  // 创建上下文
  const context: ToolContext = {
    userId: 'user-123',
    sessionId: 'session-456',
    permissionRules: await ruleStore.get('user-123'),
    logger: console
  };

  // 执行工具
  const result = await executor.execute(
    FileWriteTool,
    {
      filePath: './output.txt',
      content: 'Hello, World!'
    },
    context
  );

  if (result.success) {
    console.log('Success:', result.data);
  } else {
    console.error('Failed:', result.error);
  }
}

main().catch(console.error);
```

---

## 总结

实现用户确认机制的关键点：

1. **清晰的类型定义**：PermissionDecision、Tool、ToolContext
2. **分层架构**：权限检查 → UI 展示 → 用户决策 → 结果传递
3. **异步 Promise 流**：工具执行暂停等待用户输入
4. **工具特定的检查**：每个工具实现自己的 checkPermissions()
5. **UI 组件化**：支持不同平台（CLI、Web）的渲染
6. **规则持久化**：保存用户的"记住选择"
7. **可扩展性**：支持自动分类器、批量确认等高级功能
