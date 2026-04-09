# Subagent 实现指南

> 本文档提供实现类似 Claude Code Subagent 系统的实战指南，包含核心代码示例和设计建议。

---

## 1. 最小可运行实现

### 1.1 基础类型定义

```typescript
// types.ts

// 基础消息类型
export type Message = 
  | { type: 'assistant'; content: ContentBlock[]; usage?: Usage }
  | { type: 'user'; content: ContentBlock[] };

export type ContentBlock =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; tool_use_id: string; content: ContentBlock[] };

export type Usage = {
  input_tokens: number;
  output_tokens: number;
};

// 子代理配置
export type SubagentConfig = {
  description: string;
  prompt: string;
  model?: string;
  maxTurns?: number;
  allowedTools?: string[];
  runInBackground?: boolean;
};

// 子代理结果
export type SubagentResult = {
  content: string;
  usage: Usage;
  durationMs: number;
  toolCallCount: number;
};

// 任务状态
export type TaskState = {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'killed';
  description: string;
  startTime: number;
  endTime?: number;
  result?: SubagentResult;
  error?: string;
  progress?: TaskProgress;
};

export type TaskProgress = {
  currentActivity?: string;
  toolCallCount: number;
  filesAccessed: string[];
};
```

### 1.2 核心 Subagent 执行器

```typescript
// executor.ts

import { EventEmitter } from 'events';

export class SubagentExecutor extends EventEmitter {
  private tasks = new Map<string, TaskState>();
  private abortControllers = new Map<string, AbortController>();

  /**
   * 执行子代理（同步模式）
   */
  async execute(config: SubagentConfig): Promise<SubagentResult> {
    const taskId = this.createTask(config);
    
    try {
      const result = await this.runAgentLoop(taskId, config);
      this.completeTask(taskId, result);
      return result;
    } catch (error) {
      this.failTask(taskId, error);
      throw error;
    }
  }

  /**
   * 执行子代理（异步模式）
   */
  async executeAsync(config: SubagentConfig): Promise<string> {
    const taskId = this.createTask(config);
    
    // 在后台运行
    this.runAgentLoop(taskId, config)
      .then(result => this.completeTask(taskId, result))
      .catch(error => this.failTask(taskId, error));
    
    // 立即返回任务 ID
    return taskId;
  }

  /**
   * 获取任务状态
   */
  getTask(taskId: string): TaskState | undefined {
    return this.tasks.get(taskId);
  }

  /**
   * 终止任务
   */
  killTask(taskId: string): void {
    const controller = this.abortControllers.get(taskId);
    if (controller) {
      controller.abort();
    }
    
    const task = this.tasks.get(taskId);
    if (task && task.status === 'running') {
      this.updateTask(taskId, { status: 'killed', endTime: Date.now() });
    }
  }

  /**
   * 列出所有任务
   */
  listTasks(): TaskState[] {
    return Array.from(this.tasks.values());
  }

  // ============ 私有方法 ============

  private createTask(config: SubagentConfig): string {
    const taskId = `task_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const abortController = new AbortController();
    
    const task: TaskState = {
      id: taskId,
      status: 'pending',
      description: config.description,
      startTime: Date.now(),
      progress: {
        toolCallCount: 0,
        filesAccessed: [],
      },
    };
    
    this.tasks.set(taskId, task);
    this.abortControllers.set(taskId, abortController);
    
    this.emit('taskCreated', task);
    return taskId;
  }

  private async runAgentLoop(
    taskId: string,
    config: SubagentConfig,
  ): Promise<SubagentResult> {
    this.updateTask(taskId, { status: 'running' });
    
    const abortController = this.abortControllers.get(taskId)!;
    const maxTurns = config.maxTurns ?? 100;
    const messages: Message[] = [
      { type: 'user', content: [{ type: 'text', text: config.prompt }] },
    ];
    
    let toolCallCount = 0;
    const startTime = Date.now();
    
    for (let turn = 0; turn < maxTurns; turn++) {
      // 检查取消信号
      if (abortController.signal.aborted) {
        throw new Error('Task aborted');
      }
      
      // 调用 LLM
      const response = await this.callLLM(messages, config.model);
      messages.push({
        type: 'assistant',
        content: response.content,
        usage: response.usage,
      });
      
      // 处理工具调用
      const toolCalls = response.content.filter(c => c.type === 'tool_use');
      
      if (toolCalls.length === 0) {
        // 没有工具调用，任务完成
        const textContent = response.content
          .filter(c => c.type === 'text')
          .map(c => c.text)
          .join('\n');
        
        return {
          content: textContent,
          usage: response.usage,
          durationMs: Date.now() - startTime,
          toolCallCount,
        };
      }
      
      // 执行工具调用
      const toolResults: ContentBlock[] = [];
      for (const toolCall of toolCalls) {
        toolCallCount++;
        this.updateProgress(taskId, toolCall.name);
        
        const result = await this.executeTool(toolCall, config.allowedTools);
        toolResults.push({
          type: 'tool_result',
          tool_use_id: toolCall.id,
          content: [{ type: 'text', text: JSON.stringify(result) }],
        });
      }
      
      messages.push({
        type: 'user',
        content: toolResults,
      });
    }
    
    throw new Error(`Max turns (${maxTurns}) exceeded`);
  }

  private async callLLM(
    messages: Message[],
    model?: string,
  ): Promise<{ content: ContentBlock[]; usage: Usage }> {
    // 这里集成实际的 LLM API 调用
    // 示例使用模拟实现
    throw new Error('Not implemented: integrate with actual LLM API');
  }

  private async executeTool(
    toolCall: Extract<ContentBlock, { type: 'tool_use' }>,
    allowedTools?: string[],
  ): Promise<unknown> {
    // 检查工具权限
    if (allowedTools && !allowedTools.includes(toolCall.name)) {
      throw new Error(`Tool ${toolCall.name} is not allowed`);
    }
    
    // 这里集成实际的工具执行
    // 示例使用模拟实现
    throw new Error('Not implemented: integrate with actual tool execution');
  }

  private updateTask(taskId: string, updates: Partial<TaskState>): void {
    const task = this.tasks.get(taskId);
    if (!task) return;
    
    const updated = { ...task, ...updates };
    this.tasks.set(taskId, updated);
    this.emit('taskUpdated', updated);
  }

  private updateProgress(taskId: string, activity: string): void {
    const task = this.tasks.get(taskId);
    if (!task || !task.progress) return;
    
    this.updateTask(taskId, {
      progress: {
        ...task.progress,
        currentActivity: activity,
        toolCallCount: task.progress.toolCallCount + 1,
      },
    });
  }

  private completeTask(taskId: string, result: SubagentResult): void {
    this.updateTask(taskId, {
      status: 'completed',
      endTime: Date.now(),
      result,
    });
    this.emit('taskCompleted', { taskId, result });
    this.cleanup(taskId);
  }

  private failTask(taskId: string, error: unknown): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    
    this.updateTask(taskId, {
      status: 'failed',
      endTime: Date.now(),
      error: errorMessage,
    });
    this.emit('taskFailed', { taskId, error: errorMessage });
    this.cleanup(taskId);
  }

  private cleanup(taskId: string): void {
    this.abortControllers.delete(taskId);
  }
}
```

### 1.3 使用示例

```typescript
// example.ts

import { SubagentExecutor } from './executor';

async function main() {
  const executor = new SubagentExecutor();
  
  // 监听事件
  executor.on('taskCreated', task => {
    console.log(`Task created: ${task.id} - ${task.description}`);
  });
  
  executor.on('taskUpdated', task => {
    if (task.progress) {
      console.log(`[${task.id}] ${task.progress.currentActivity}`);
    }
  });
  
  executor.on('taskCompleted', ({ taskId, result }) => {
    console.log(`Task ${taskId} completed:`);
    console.log(`- Duration: ${result.durationMs}ms`);
    console.log(`- Tokens: ${result.usage.input_tokens + result.usage.output_tokens}`);
    console.log(`- Tool calls: ${result.toolCallCount}`);
  });
  
  // 同步执行
  try {
    const result = await executor.execute({
      description: 'Analyze codebase',
      prompt: '请分析当前代码库的结构，找出所有 TypeScript 文件',
      maxTurns: 50,
      allowedTools: ['glob', 'readFile'],
    });
    console.log('Result:', result.content);
  } catch (error) {
    console.error('Execution failed:', error);
  }
  
  // 异步执行
  const taskId = await executor.executeAsync({
    description: 'Long running task',
    prompt: '执行一个长时间运行的任务...',
    runInBackground: true,
  });
  
  // 轮询检查状态
  const interval = setInterval(() => {
    const task = executor.getTask(taskId);
    console.log(`Status: ${task?.status}`);
    
    if (task?.status === 'completed' || task?.status === 'failed') {
      clearInterval(interval);
      console.log('Final result:', task.result || task.error);
    }
  }, 1000);
  
  // 5秒后终止任务
  setTimeout(() => {
    console.log('Killing task...');
    executor.killTask(taskId);
  }, 5000);
}

main();
```

---

## 2. 高级功能实现

### 2.1 生成器模式实现渐进式输出

```typescript
// generator.ts

export interface AgentMessage {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'content';
  data: unknown;
  timestamp: number;
}

export async function* runAgentGenerator(
  config: SubagentConfig,
  abortSignal: AbortSignal,
): AsyncGenerator<AgentMessage, SubagentResult, unknown> {
  const messages: Message[] = [];
  const startTime = Date.now();
  let toolCallCount = 0;
  
  for (let turn = 0; turn < (config.maxTurns ?? 100); turn++) {
    if (abortSignal.aborted) {
      throw new Error('Aborted');
    }
    
    // 调用 LLM
    const response = await callLLM(messages);
    
    // yield 思考过程
    const thinking = extractThinking(response);
    if (thinking) {
      yield {
        type: 'thinking',
        data: thinking,
        timestamp: Date.now(),
      };
    }
    
    // 处理工具调用
    for (const block of response.content) {
      if (block.type === 'tool_use') {
        toolCallCount++;
        
        // yield 工具调用
        yield {
          type: 'tool_call',
          data: {
            name: block.name,
            input: block.input,
          },
          timestamp: Date.now(),
        };
        
        // 执行工具
        const result = await executeTool(block);
        
        // yield 工具结果
        yield {
          type: 'tool_result',
          data: result,
          timestamp: Date.now(),
        };
      }
      
      if (block.type === 'text') {
        // yield 内容块
        yield {
          type: 'content',
          data: block.text,
          timestamp: Date.now(),
        };
      }
    }
    
    // 检查是否完成
    if (isComplete(response)) {
      const result: SubagentResult = {
        content: extractContent(response),
        usage: response.usage,
        durationMs: Date.now() - startTime,
        toolCallCount,
      };
      return result;
    }
  }
  
  throw new Error('Max turns exceeded');
}

// 使用生成器
async function consumeGenerator(config: SubagentConfig) {
  const abortController = new AbortController();
  
  const generator = runAgentGenerator(config, abortController.signal);
  
  for await (const message of generator) {
    switch (message.type) {
      case 'thinking':
        console.log('🤔 Thinking:', message.data);
        break;
      case 'tool_call':
        console.log('🔧 Tool call:', message.data);
        break;
      case 'tool_result':
        console.log('✅ Tool result:', message.data);
        break;
      case 'content':
        console.log('📝 Content:', message.data);
        break;
    }
  }
  
  // 获取最终结果
  const result = await generator.return?.();
  console.log('Final result:', result);
}
```

### 2.2 父子 AbortController 层级

```typescript
// abort.ts

export class AbortControllerManager {
  private controllers = new Map<string, AbortController>();
  private parentChildMap = new Map<string, Set<string>>();

  /**
   * 创建根控制器
   */
  createRoot(id: string): AbortController {
    const controller = new AbortController();
    this.controllers.set(id, controller);
    this.parentChildMap.set(id, new Set());
    return controller;
  }

  /**
   * 创建子控制器
   */
  createChild(parentId: string, childId: string): AbortController {
    const parent = this.controllers.get(parentId);
    if (!parent) {
      throw new Error(`Parent controller ${parentId} not found`);
    }
    
    const child = new AbortController();
    this.controllers.set(childId, child);
    
    // 建立父子关系
    const siblings = this.parentChildMap.get(parentId);
    if (siblings) {
      siblings.add(childId);
    }
    this.parentChildMap.set(childId, new Set());
    
    // 级联取消
    parent.signal.addEventListener('abort', () => {
      child.abort();
      this.cancelAllChildren(childId);
    });
    
    return child;
  }

  /**
   * 取消控制器及其所有后代
   */
  abort(id: string): void {
    const controller = this.controllers.get(id);
    if (controller) {
      controller.abort();
      this.cancelAllChildren(id);
    }
  }

  /**
   * 递归取消所有子控制器
   */
  private cancelAllChildren(parentId: string): void {
    const children = this.parentChildMap.get(parentId);
    if (!children) return;
    
    for (const childId of children) {
      const childController = this.controllers.get(childId);
      if (childController) {
        childController.abort();
        this.cancelAllChildren(childId);
      }
    }
  }

  /**
   * 清理已完成的控制器
   */
  cleanup(id: string): void {
    this.controllers.delete(id);
    this.parentChildMap.delete(id);
    
    // 从父节点的子列表中移除
    for (const [parentId, children] of this.parentChildMap) {
      children.delete(id);
    }
  }

  /**
   * 获取控制器
   */
  get(id: string): AbortController | undefined {
    return this.controllers.get(id);
  }
}

// 使用示例
const manager = new AbortControllerManager();

// 创建父任务
const parentController = manager.createRoot('parent-task');

// 创建子任务
const child1Controller = manager.createChild('parent-task', 'child-1');
const child2Controller = manager.createChild('parent-task', 'child-2');

// 创建孙任务
const grandchildController = manager.createChild('child-1', 'grandchild');

// 取消父任务 - 会自动取消所有子任务和孙任务
manager.abort('parent-task');
```

### 2.3 工具过滤系统

```typescript
// tools.ts

export type Tool = {
  name: string;
  description: string;
  execute: (input: Record<string, unknown>) => Promise<unknown>;
};

export type ToolFilterConfig = {
  allowedTools?: string[];      // 白名单
  disallowedTools?: string[];   // 黑名单
  isAsync?: boolean;            // 是否异步代理
  isBuiltIn?: boolean;          // 是否内置代理
};

export class ToolRegistry {
  private tools = new Map<string, Tool>();
  
  // 预定义的工具分类
  private static DANGEROUS_TOOLS = new Set([
    'exit_plan_mode',
    'enter_plan_mode',
    'recursive_agent',
  ]);
  
  private static ASYNC_ALLOWED_TOOLS = new Set([
    'readFile',
    'writeFile',
    'editFile',
    'glob',
    'grep',
    'webSearch',
    'bash',
  ]);

  register(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  /**
   * 根据配置过滤工具
   */
  filterTools(config: ToolFilterConfig): Tool[] {
    return Array.from(this.tools.values()).filter(tool => {
      return this.isToolAllowed(tool.name, config);
    });
  }

  private isToolAllowed(name: string, config: ToolFilterConfig): boolean {
    // 1. 检查白名单
    if (config.allowedTools) {
      // 支持通配符 '*' 表示允许所有
      if (config.allowedTools.includes('*')) {
        // 但仍需检查黑名单
      } else if (!config.allowedTools.includes(name)) {
        return false;
      }
    }
    
    // 2. 检查黑名单
    if (config.disallowedTools?.includes(name)) {
      return false;
    }
    
    // 3. 检查危险工具
    if (ToolRegistry.DANGEROUS_TOOLS.has(name)) {
      return false;
    }
    
    // 4. 异步代理限制
    if (config.isAsync && !ToolRegistry.ASYNC_ALLOWED_TOOLS.has(name)) {
      return false;
    }
    
    return true;
  }

  /**
   * 获取工具的描述列表（用于 LLM 系统提示）
   */
  getToolDescriptions(config: ToolFilterConfig): string {
    const allowedTools = this.filterTools(config);
    return allowedTools
      .map(t => `- ${t.name}: ${t.description}`)
      .join('\n');
  }
}
```

---

## 3. 状态管理实现

### 3.1 基于事件的状态管理

```typescript
// state.ts

import { EventEmitter } from 'events';

export type StateListener<T> = (state: T) => void;

export class StateManager<T extends Record<string, unknown>> extends EventEmitter {
  private state: T;
  private listeners = new Map<keyof T, Set<StateListener<T[keyof T]>>>();

  constructor(initialState: T) {
    super();
    this.state = { ...initialState };
  }

  /**
   * 获取当前状态
   */
  get(): T {
    return { ...this.state };
  }

  /**
   * 获取特定字段
   */
  getKey<K extends keyof T>(key: K): T[K] {
    return this.state[key];
  }

  /**
   * 更新状态（批量）
   */
  set(updates: Partial<T>): void {
    const prevState = { ...this.state };
    this.state = { ...this.state, ...updates };
    
    // 通知整体变更
    this.emit('change', this.state, prevState);
    
    // 通知字段级变更
    for (const key of Object.keys(updates) as Array<keyof T>) {
      if (updates[key] !== prevState[key]) {
        this.emit(`change:${String(key)}`, this.state[key], prevState[key]);
        
        const keyListeners = this.listeners.get(key);
        if (keyListeners) {
          for (const listener of keyListeners) {
            listener(this.state[key]);
          }
        }
      }
    }
  }

  /**
   * 函数式更新
   */
  update(updater: (prev: T) => T): void {
    const newState = updater(this.get());
    this.set(newState);
  }

  /**
   * 订阅特定字段变更
   */
  subscribe<K extends keyof T>(
    key: K,
    listener: StateListener<T[K]>,
  ): () => void {
    if (!this.listeners.has(key)) {
      this.listeners.set(key, new Set());
    }
    this.listeners.get(key)!.add(listener);
    
    // 立即返回当前值
    listener(this.state[key]);
    
    // 返回取消订阅函数
    return () => {
      this.listeners.get(key)?.delete(listener);
    };
  }

  /**
   * 订阅所有变更
   */
  subscribeAll(listener: StateListener<T>): () => void {
    this.on('change', listener);
    listener(this.get());
    
    return () => {
      this.off('change', listener);
    };
  }
}

// 任务状态管理器类型
type AppState = {
  tasks: Record<string, TaskState>;
  activeTaskCount: number;
  settings: {
    maxConcurrentTasks: number;
    enableNotifications: boolean;
  };
};

// 使用示例
const stateManager = new StateManager<AppState>({
  tasks: {},
  activeTaskCount: 0,
  settings: {
    maxConcurrentTasks: 10,
    enableNotifications: true,
  },
});

// 订阅任务列表变更
stateManager.subscribe('tasks', tasks => {
  console.log(`Active tasks: ${Object.keys(tasks).length}`);
});

// 添加任务
stateManager.update(prev => ({
  ...prev,
  tasks: {
    ...prev.tasks,
    'new-task': {
      id: 'new-task',
      status: 'running',
      description: 'New task',
      startTime: Date.now(),
    },
  },
  activeTaskCount: prev.activeTaskCount + 1,
}));
```

---

## 4. 最佳实践

### 4.1 错误处理策略

```typescript
// error-handling.ts

export class AgentError extends Error {
  constructor(
    message: string,
    public code: string,
    public recoverable: boolean = false,
  ) {
    super(message);
    this.name = 'AgentError';
  }
}

export async function executeWithRetry<T>(
  fn: () => Promise<T>,
  options: {
    maxRetries?: number;
    delayMs?: number;
    onRetry?: (error: Error, attempt: number) => void;
  } = {},
): Promise<T> {
  const { maxRetries = 3, delayMs = 1000, onRetry } = options;
  
  let lastError: Error;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      
      if (attempt < maxRetries) {
        onRetry?.(lastError, attempt + 1);
        await sleep(delayMs * Math.pow(2, attempt)); // 指数退避
      }
    }
  }
  
  throw lastError!;
}

export async function executeWithTimeout<T>(
  fn: () => Promise<T>,
  timeoutMs: number,
): Promise<T> {
  return Promise.race([
    fn(),
    new Promise<never>((_, reject) => {
      setTimeout(() => reject(new Error('Timeout')), timeoutMs);
    }),
  ]);
}

// 使用示例
const result = await executeWithRetry(
  () => executeWithTimeout(() => runSubagent(config), 30000),
  {
    maxRetries: 3,
    onRetry: (error, attempt) => {
      console.log(`Retry ${attempt} after error: ${error.message}`);
    },
  },
);
```

### 4.2 资源管理

```typescript
// resource-management.ts

export class ResourceManager {
  private resources = new Map<string, () => Promise<void>>();
  private cleanupCallbacks = new Set<() => Promise<void>>();

  /**
   * 注册资源
   */
  register(id: string, cleanup: () => Promise<void>): void {
    this.resources.set(id, cleanup);
  }

  /**
   * 释放特定资源
   */
  async release(id: string): Promise<void> {
    const cleanup = this.resources.get(id);
    if (cleanup) {
      await cleanup();
      this.resources.delete(id);
    }
  }

  /**
   * 注册清理回调
   */
  onCleanup(callback: () => Promise<void>): void {
    this.cleanupCallbacks.add(callback);
  }

  /**
   * 释放所有资源
   */
  async releaseAll(): Promise<void> {
    // 执行所有清理回调
    for (const callback of this.cleanupCallbacks) {
      try {
        await callback();
      } catch (error) {
        console.error('Cleanup callback failed:', error);
      }
    }
    this.cleanupCallbacks.clear();
    
    // 释放所有注册的资源
    for (const [id, cleanup] of this.resources) {
      try {
        await cleanup();
      } catch (error) {
        console.error(`Failed to release resource ${id}:`, error);
      }
    }
    this.resources.clear();
  }
}

// 使用示例
const resourceManager = new ResourceManager();

// 注册临时文件
const tempFile = await createTempFile();
resourceManager.register(`temp:${tempFile}`, async () => {
  await fs.unlink(tempFile);
});

// 注册数据库连接
const dbConnection = await connectToDatabase();
resourceManager.register('db:connection', async () => {
  await dbConnection.close();
});

// 确保清理
try {
  // 执行业务逻辑
} finally {
  await resourceManager.releaseAll();
}
```

---

## 5. 性能优化建议

### 5.1 Prompt Caching

```typescript
// caching.ts

export class PromptCache {
  private cache = new Map<string, {
    content: string;
    timestamp: number;
    hits: number;
  }>();
  
  private maxSize: number;
  private ttlMs: number;

  constructor(options: { maxSize?: number; ttlMs?: number } = {}) {
    this.maxSize = options.maxSize ?? 100;
    this.ttlMs = options.ttlMs ?? 5 * 60 * 1000; // 5分钟
  }

  get(key: string): string | undefined {
    const entry = this.cache.get(key);
    
    if (!entry) return undefined;
    
    // 检查过期
    if (Date.now() - entry.timestamp > this.ttlMs) {
      this.cache.delete(key);
      return undefined;
    }
    
    entry.hits++;
    return entry.content;
  }

  set(key: string, content: string): void {
    // 如果缓存满了，移除最少使用的
    if (this.cache.size >= this.maxSize) {
      const lruKey = this.findLRU();
      if (lruKey) this.cache.delete(lruKey);
    }
    
    this.cache.set(key, {
      content,
      timestamp: Date.now(),
      hits: 0,
    });
  }

  private findLRU(): string | undefined {
    let minHits = Infinity;
    let lruKey: string | undefined;
    
    for (const [key, entry] of this.cache) {
      if (entry.hits < minHits) {
        minHits = entry.hits;
        lruKey = key;
      }
    }
    
    return lruKey;
  }
}

// 在 Fork 子代理中复用父代理的缓存
export function createChildCache(parentCache: PromptCache): PromptCache {
  // 子代理可以读取父缓存，但写入独立缓存
  const childCache = new PromptCache();
  
  return new Proxy(childCache, {
    get(target, prop) {
      if (prop === 'get') {
        return (key: string) => {
          // 先查子缓存
          const childResult = target.get(key);
          if (childResult) return childResult;
          
          // 再查父缓存
          return parentCache.get(key);
        };
      }
      return target[prop as keyof PromptCache];
    },
  });
}
```

### 5.2 并发控制

```typescript
// concurrency.ts

export class ConcurrencyLimiter {
  private running = 0;
  private queue: Array<{
    fn: () => Promise<void>;
    resolve: () => void;
    reject: (error: Error) => void;
  }> = [];

  constructor(private maxConcurrency: number) {}

  async run<T>(fn: () => Promise<T>): Promise<T> {
    // 如果未达到并发上限，直接执行
    if (this.running < this.maxConcurrency) {
      return this.execute(fn);
    }
    
    // 否则加入队列等待
    return new Promise((resolve, reject) => {
      this.queue.push({
        fn: async () => {
          try {
            const result = await fn();
            resolve(result);
          } catch (error) {
            reject(error instanceof Error ? error : new Error(String(error)));
          }
        },
        resolve: () => {},
        reject,
      });
    });
  }

  private async execute<T>(fn: () => Promise<T>): Promise<T> {
    this.running++;
    
    try {
      return await fn();
    } finally {
      this.running--;
      this.processQueue();
    }
  }

  private processQueue(): void {
    if (this.queue.length === 0) return;
    if (this.running >= this.maxConcurrency) return;
    
    const next = this.queue.shift();
    if (next) {
      this.execute(next.fn);
    }
  }
}

// 使用示例
const limiter = new ConcurrencyLimiter(5); // 最多5个并发

// 启动多个子代理
const tasks = Array.from({ length: 10 }, (_, i) =>
  limiter.run(() => runSubagent({
    description: `Task ${i}`,
    prompt: `Execute task ${i}`,
  }))
);

await Promise.all(tasks);
```

---

## 6. 测试策略

```typescript
// tests.ts

import { describe, it, expect, vi } from 'vitest';

describe('SubagentExecutor', () => {
  it('should execute a simple task', async () => {
    const executor = new SubagentExecutor();
    
    // Mock LLM 调用
    vi.spyOn(executor as any, 'callLLM').mockResolvedValue({
      content: [{ type: 'text', text: 'Task completed' }],
      usage: { input_tokens: 100, output_tokens: 50 },
    });
    
    const result = await executor.execute({
      description: 'Test task',
      prompt: 'Do something',
    });
    
    expect(result.content).toBe('Task completed');
    expect(result.usage.input_tokens).toBe(100);
  });

  it('should handle task cancellation', async () => {
    const executor = new SubagentExecutor();
    
    // 延迟的 LLM 调用
    vi.spyOn(executor as any, 'callLLM').mockImplementation(
      () => new Promise(resolve => setTimeout(resolve, 1000))
    );
    
    const taskPromise = executor.execute({
      description: 'Long task',
      prompt: 'Take your time',
    });
    
    // 立即取消
    const tasks = executor.listTasks();
    executor.killTask(tasks[0].id);
    
    await expect(taskPromise).rejects.toThrow('Task aborted');
  });

  it('should respect max turns limit', async () => {
    const executor = new SubagentExecutor();
    
    // 总是返回工具调用的 Mock
    vi.spyOn(executor as any, 'callLLM').mockResolvedValue({
      content: [{
        type: 'tool_use',
        id: '1',
        name: 'testTool',
        input: {},
      }],
      usage: { input_tokens: 10, output_tokens: 10 },
    });
    
    vi.spyOn(executor as any, 'executeTool').mockResolvedValue({});
    
    await expect(
      executor.execute({
        description: 'Infinite loop',
        prompt: 'Keep going',
        maxTurns: 5,
      })
    ).rejects.toThrow('Max turns (5) exceeded');
  });

  it('should filter tools correctly', async () => {
    const registry = new ToolRegistry();
    
    registry.register({
      name: 'safeTool',
      description: 'A safe tool',
      execute: async () => 'safe',
    });
    
    registry.register({
      name: 'exit_plan_mode',
      description: 'Dangerous',
      execute: async () => {},
    });
    
    const filtered = registry.filterTools({
      allowedTools: ['safeTool', 'exit_plan_mode'],
    });
    
    // exit_plan_mode 应该在危险工具列表中被过滤
    expect(filtered.map(t => t.name)).toContain('safeTool');
    expect(filtered.map(t => t.name)).not.toContain('exit_plan_mode');
  });
});
```

---

## 7. 总结

实现一个健壮的 Subagent 系统需要考虑以下关键点：

1. **清晰的架构分层**: 入口层、执行层、状态管理层职责分离
2. **灵活的执行模式**: 同步/异步、前台/后台多种模式支持
3. **完善的取消机制**: AbortController 层级结构实现优雅取消
4. **精细的权限控制**: 工具过滤系统确保安全性
5. **可靠的状态管理**: 函数式更新确保数据一致性
6. **优雅的错误处理**: 多层捕获、部分结果保留、自动重试
7. **性能优化**: Prompt Caching、并发控制、资源管理

以上代码示例提供了实现这些功能的基础框架，可以根据具体需求进行扩展和定制。
