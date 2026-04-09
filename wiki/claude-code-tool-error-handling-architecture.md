# Claude Code Tool/MCP 工具接口调用失败处理逻辑架构分析

## 概述

Claude Code 是一个复杂的 AI 辅助编程工具，其工具系统（Tool System）和 MCP（Model Context Protocol）集成具有完善的错误处理机制。本文档深入分析其工具调用失败的处理架构。

---

## 1. 整体架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           QueryEngine / query.ts                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     主查询循环 (queryLoop)                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │   │
│  │  │ API 调用     │→│ 工具执行     │→│ 结果处理 & 错误恢复      │  │   │
│  │  │ (callModel)  │  │ (runTools)   │  │ (reactive compact等)     │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      services/tools/toolExecution.ts                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    工具执行核心逻辑                                 │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────┐  │   │
│  │  │ 输入验证    │→│ 权限检查    │→│ 工具调用    │→│ 后处理 Hooks │  │   │
│  │  │ (Zod)       │  │ (canUseTool)│  │ (tool.call) │  │              │  │   │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └──────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                      services/mcp/client.ts                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    MCP 客户端管理                                   │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐    │   │
│  │  │ 连接管理     │ │ 工具调用     │ │ 错误处理 & 重连机制      │    │   │
│  │  │ (connectTo)  │ │ (callMCP)    │ │ (session expiry, 401)    │    │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Tool 调用失败处理流程

### 2.1 错误分类体系

Claude Code 将工具调用错误分为以下几类：

| 错误类型 | 说明 | 处理位置 |
|---------|------|---------|
| `InputValidationError` | Zod 输入校验失败 | `toolExecution.ts:615-680` |
| `PermissionDenied` | 权限检查未通过 | `toolExecution.ts:995-1103` |
| `ToolNotFound` | 工具不存在 | `toolExecution.ts:369-410` |
| `ExecutionError` | 工具执行抛异常 | `toolExecution.ts:1589-1744` |
| `AbortError` | 用户中断 | `toolExecution.ts:415-453` |
| `McpAuthError` | MCP 认证失败 | `mcp/client.ts:152-159` |
| `McpSessionExpiredError` | MCP 会话过期 | `mcp/client.ts:165-170` |

### 2.2 详细错误处理流程

```
工具调用开始
     ↓
┌─────────────────┐
│ 1. 查找工具     │ ──→ 工具不存在 ──→ 返回 ToolNotFound 错误
└─────────────────┘
     ↓ 找到工具
┌─────────────────┐
│ 2. 检查中断状态 │ ──→ 已中断 ──→ 返回 AbortError
└─────────────────┘
     ↓ 未中断
┌─────────────────┐
│ 3. Zod 输入验证 │ ──→ 验证失败 ──→ 返回 InputValidationError
└─────────────────┘
     ↓ 验证通过
┌─────────────────┐
│ 4. 运行 PreHooks│ ──→ Hook 返回停止 ──→ 返回 HookStop 错误
└─────────────────┘
     ↓ Hooks 通过
┌─────────────────┐
│ 5. 权限检查     │ ──→ 权限拒绝 ──→ 返回 PermissionDenied + 可选图片
└─────────────────┘
     ↓ 权限允许
┌─────────────────┐
│ 6. 执行工具调用 │ ──→ 执行异常 ──→ 捕获异常, 运行 PostFailureHooks
└─────────────────┘
     ↓ 执行成功
┌─────────────────┐
│ 7. 运行 PostHooks│
└─────────────────┘
     ↓
返回结果
```

### 2.3 核心错误处理代码

**`services/tools/toolExecution.ts` 中的错误处理：**

```typescript
// 行 469-490: 顶层错误捕获
try {
  for await (const update of streamedCheckPermissionsAndCallTool(...)) {
    yield update
  }
} catch (error) {
  logError(error)
  const errorMessage = error instanceof Error ? error.message : String(error)
  const toolInfo = tool ? ` (${tool.name})` : ''
  const detailedError = `Error calling tool${toolInfo}: ${errorMessage}`

  yield {
    message: createUserMessage({
      content: [{
        type: 'tool_result',
        content: `<tool_use_error>${detailedError}</tool_use_error>`,
        is_error: true,
        tool_use_id: toolUse.id,
      }],
      toolUseResult: detailedError,
      sourceToolAssistantUUID: assistantMessage.uuid,
    }),
  }
}
```

**`services/tools/toolExecution.ts` 行 1589-1744: 工具执行错误处理**

```typescript
try {
  const result = await tool.call(...)
  // ... 成功处理
} catch (error) {
  const durationMs = Date.now() - startTime
  addToToolDuration(durationMs)

  endToolExecutionSpan({
    success: false,
    error: errorMessage(error),
  })
  endToolSpan()

  // MCP 认证错误特殊处理
  if (error instanceof McpAuthError) {
    toolUseContext.setAppState(prevState => {
      // 更新客户端状态为 'needs-auth'
      const serverName = error.serverName
      // ... 状态更新逻辑
    })
  }

  // 记录错误日志和遥测数据
  if (!(error instanceof AbortError)) {
    logEvent('tengu_tool_use_error', {
      toolName: sanitizeToolNameForAnalytics(tool.name),
      error: classifyToolError(error),
      // ... 其他元数据
    })
  }

  // 运行 PostToolUseFailure Hooks
  const hookMessages = []
  for await (const hookResult of runPostToolUseFailureHooks(...)) {
    hookMessages.push(hookResult)
  }

  // 返回错误结果
  return [{
    message: createUserMessage({
      content: [{
        type: 'tool_result',
        content: formatError(error),
        is_error: true,
        tool_use_id: toolUseID,
      }],
      toolUseResult: `Error: ${formatError(error)}`,
      // ... MCP 元数据传递
    }),
  }, ...hookMessages]
}
```

---

## 3. MCP 工具调用失败处理

### 3.1 MCP 错误类型定义

**`services/mcp/client.ts` 行 146-186:**

```typescript
/**
 * MCP 认证错误 - OAuth token 过期返回 401
 */
export class McpAuthError extends Error {
  serverName: string
  constructor(serverName: string, message: string) {
    super(message)
    this.name = 'McpAuthError'
    this.serverName = serverName
  }
}

/**
 * MCP 会话过期错误 - 会话缓存被清除
 */
class McpSessionExpiredError extends Error {
  constructor(serverName: string) {
    super(`MCP server "${serverName}" session expired`)
    this.name = 'McpSessionExpiredError'
  }
}

/**
 * MCP 工具调用错误 - 携带 _meta 供 SDK 消费
 */
export class McpToolCallError extends TelemetrySafeError {
  constructor(
    message: string,
    telemetryMessage: string,
    readonly mcpMeta?: { _meta?: Record<string, unknown> },
  ) {
    super(message, telemetryMessage)
    this.name = 'McpToolCallError'
  }
}
```

### 3.2 MCP 会话过期检测

**`services/mcp/client.ts` 行 193-206:**

```typescript
export function isMcpSessionExpiredError(error: Error): boolean {
  const httpStatus =
    'code' in error ? (error as Error & { code?: number }).code : undefined
  if (httpStatus !== 404) {
    return false
  }
  // MCP 服务器返回: {"error":{"code":-32001,"message":"Session not found"},...}
  return (
    error.message.includes('"code":-32001') ||
    error.message.includes('"code": -32001')
  )
}
```

### 3.3 MCP 工具调用重试机制

**`services/mcp/client.ts` 行 1859-1970: 带会话恢复的重试逻辑**

```typescript
async call(args: Record<string, unknown>, context, ...) {
  const MAX_SESSION_RETRIES = 1
  for (let attempt = 0; ; attempt++) {
    try {
      const connectedClient = await ensureConnectedClient(client)
      const mcpResult = await callMCPToolWithUrlElicitationRetry({
        client: connectedClient,
        tool: tool.name,
        args,
        signal: context.abortController.signal,
        // ... 其他参数
      })
      return {
        data: mcpResult.content,
        mcpMeta: {
          _meta: mcpResult._meta,
          structuredContent: mcpResult.structuredContent,
        },
      }
    } catch (error) {
      // 会话过期重试
      if (
        error instanceof McpSessionExpiredError &&
        attempt < MAX_SESSION_RETRIES
      ) {
        logMCPDebug(client.name, `Retrying tool after session recovery`)
        continue  // 重试
      }

      // 错误包装转换
      if (error instanceof Error && !(error instanceof TelemetrySafeError)) {
        const name = error.constructor.name
        if (name === 'McpError' && 'code' in error) {
          throw new TelemetrySafeError(
            error.message,
            `McpError ${error.code}`,
          )
        }
      }
      throw error
    }
  }
}
```

### 3.4 MCP 连接错误恢复

**`services/mcp/client.ts` 行 1265-1371: 连接错误处理和自动重连**

```typescript
client.onerror = (error: Error) => {
  const uptime = Date.now() - connectionStartTime
  hasErrorOccurred = true
  
  // 会话过期检测和自动关闭
  if (
    (transportType === 'http' || transportType === 'claudeai-proxy') &&
    isMcpSessionExpiredError(error)
  ) {
    logMCPDebug(name, `MCP session expired, triggering reconnection`)
    closeTransportAndRejectPending('session expired')
    return
  }

  // 终端连接错误计数和自动重连
  if (isTerminalConnectionError(error.message)) {
    consecutiveConnectionErrors++
    if (consecutiveConnectionErrors >= MAX_ERRORS_BEFORE_RECONNECT) {
      consecutiveConnectionErrors = 0
      closeTransportAndRejectPending('max consecutive terminal errors')
    }
  }
}

// 连接关闭时清理缓存
client.onclose = () => {
  // 清除 memoization 缓存以便下次重新连接
  connectToServer.cache.delete(key)
  fetchToolsForClient.cache.delete(name)
  // ... 其他缓存清理
}
```

---

## 4. QueryEngine 层错误处理

### 4.1 API 错误恢复机制

**`query.ts` 行 893-953: 模型回退处理**

```typescript
try {
  while (attemptWithFallback) {
    attemptWithFallback = false
    // ... API 调用
  }
} catch (innerError) {
  if (innerError instanceof FallbackTriggeredError && fallbackModel) {
    // 切换到回退模型并重试
    currentModel = fallbackModel
    attemptWithFallback = true

    // 清理之前的状态
    yield* yieldMissingToolResultBlocks(assistantMessages, 'Model fallback triggered')
    assistantMessages.length = 0
    toolResults.length = 0
    toolUseBlocks.length = 0

    // 丢弃 streaming executor 的待处理结果
    if (streamingToolExecutor) {
      streamingToolExecutor.discard()
      streamingToolExecutor = new StreamingToolExecutor(...)
    }

    // 记录回退事件
    logEvent('tengu_model_fallback_triggered', {
      original_model: innerError.originalModel,
      fallback_model: fallbackModel,
    })

    // 通知用户
    yield createSystemMessage(
      `Switched to ${renderModelName(fallbackModel)} due to high demand`,
      'warning',
    )
    continue
  }
  throw innerError
}
```

### 4.2 Prompt-Too-Long 恢复

**`query.ts` 行 1065-1183: 上下文过长恢复**

```typescript
const isWithheld413 =
  lastMessage?.type === 'assistant' &&
  lastMessage.isApiErrorMessage &&
  isPromptTooLongMessage(lastMessage)

if (isWithheld413) {
  // 首先尝试 context collapse drain
  if (feature('CONTEXT_COLLAPSE') && contextCollapse) {
    const drained = contextCollapse.recoverFromOverflow(messagesForQuery, querySource)
    if (drained.committed > 0) {
      state = { ..., transition: { reason: 'collapse_drain_retry' } }
      continue
    }
  }
}

// 然后尝试 reactive compact
if ((isWithheld413 || isWithheldMedia) && reactiveCompact) {
  const compacted = await reactiveCompact.tryReactiveCompact({
    hasAttempted: hasAttemptedReactiveCompact,
    // ... 其他参数
  })
  if (compacted) {
    state = { ..., transition: { reason: 'reactive_compact_retry' } }
    continue
  }
  // 恢复失败，显示错误并退出
  yield lastMessage
  void executeStopFailureHooks(lastMessage, toolUseContext)
  return { reason: 'prompt_too_long' }
}
```

### 4.3 Max Output Tokens 恢复

**`query.ts` 行 1188-1256:**

```typescript
if (isWithheldMaxOutputTokens(lastMessage)) {
  // 首先尝试升级到更大的输出限制
  if (capEnabled && maxOutputTokensOverride === undefined) {
    logEvent('tengu_max_tokens_escalate', { escalatedTo: ESCALATED_MAX_TOKENS })
    state = { ..., maxOutputTokensOverride: ESCALATED_MAX_TOKENS }
    continue
  }

  // 多轮恢复
  if (maxOutputTokensRecoveryCount < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT) {
    const recoveryMessage = createUserMessage({
      content: `Output token limit hit. Resume directly...`,
      isMeta: true,
    })
    state = {
      ...,
      maxOutputTokensRecoveryCount: maxOutputTokensRecoveryCount + 1,
    }
    continue
  }

  // 恢复耗尽，显示错误
  yield lastMessage
}
```

---

## 5. 错误分类和遥测

### 5.1 Tool 错误分类

**`services/tools/toolExecution.ts` 行 150-171:**

```typescript
export function classifyToolError(error: unknown): string {
  if (error instanceof TelemetrySafeError) {
    return error.telemetryMessage.slice(0, 200)
  }
  if (error instanceof Error) {
    // Node.js 文件系统错误代码 (ENOENT, EACCES 等)
    const errnoCode = getErrnoCode(error)
    if (typeof errnoCode === 'string') {
      return `Error:${errnoCode}`
    }
    // 已知错误类型的稳定名称
    if (error.name && error.name !== 'Error' && error.name.length > 3) {
      return error.name.slice(0, 60)
    }
    return 'Error'
  }
  return 'UnknownError'
}
```

### 5.2 错误格式化

**`utils/toolErrors.ts`:**

```typescript
export function formatError(error: unknown): string {
  if (error instanceof AbortError) {
    return error.message || INTERRUPT_MESSAGE_FOR_TOOL_USE
  }
  if (!(error instanceof Error)) {
    return String(error)
  }
  const parts = getErrorParts(error)
  const fullMessage = parts.filter(Boolean).join('\n').trim()
  
  // 截断长错误消息
  if (fullMessage.length <= 10000) {
    return fullMessage
  }
  const halfLength = 5000
  return `${fullMessage.slice(0, halfLength)}\n\n... [${fullMessage.length - 10000} characters truncated] ...\n\n${fullMessage.slice(-halfLength)}`
}
```

---

## 6. 关键设计模式

### 6.1 错误包装模式

Claude Code 使用多层错误包装来确保：
1. **遥测安全**: 不包含用户文件路径或代码
2. **错误分类**: 便于分析和监控
3. **用户友好**: 清晰的错误信息

```
底层错误 (McpError, ShellError 等)
     ↓
TelemetrySafeError (脱敏处理)
     ↓
ToolResult (包含 is_error: true)
     ↓
用户消息流
```

### 6.2 重试策略

| 场景 | 重试次数 | 策略 |
|-----|---------|------|
| MCP 会话过期 | 1 | 立即重连 |
| URL Elicitation | 3 | 等待用户操作后重试 |
| 模型回退 | 1 | 切换到备用模型 |
| Max Output Tokens | 3 | 渐进式恢复 |

### 6.3 流式执行错误处理

**`StreamingToolExecutor.ts`** 处理并行工具执行的错误：

```typescript
// 当工具执行失败时，仍然生成 tool_result 块
// 确保每个 tool_use 都有对应的 tool_result
for await (const result of streamingToolExecutor.getCompletedResults()) {
  if (result.message) {
    yield result.message
  }
}
```

---

## 7. 总结

Claude Code 的工具错误处理架构具有以下特点：

1. **分层处理**: 从底层 MCP 连接错误到高层 QueryEngine 恢复，每层都有专门的错误处理
2. **优雅降级**: 会话过期自动重连、模型回退、上下文压缩等多种恢复机制
3. **完整遥测**: 所有错误都被分类记录，便于监控和调试
4. **用户透明**: 错误恢复尽可能对用户透明，只在必要时显示错误信息
5. **安全优先**: 错误信息经过脱敏处理，避免泄露敏感数据
