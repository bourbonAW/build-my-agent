---
title: Bourbon Project Superpowers
description: Project analysis and brainstorming skill for Bourbon Agent
author: bourbon
tags: [project, analysis, planning]
---

# Bourbon Project Superpowers

## 🧠 Brainstorming: Error Handling Strategy

### 核心原则

**绝不自动恢复高风险操作，可以智能处理低风险操作。**

### 风险分级矩阵

| 操作类型 | 风险等级 | 错误策略 | 示例 |
|----------|----------|----------|------|
| **安装/卸载软件** | 🔴 高风险 | 暂停 → 报告 → 等待确认 | `pip install numpy==9.9.9` → 版本不存在 |
| **系统命令** | 🔴 高风险 | 暂停 → 报告 → 等待确认 | `rm -rf` 类操作 |
| **修改/删除文件** | 🟡 中风险 | 暂停 → 报告 → 等待确认 | `write_file` 覆盖重要文件 |
| **读取文件内容** | 🟢 低风险 | 智能恢复 → 搜索替代 | `read_file("main.py")` → 搜索 `*.py` |
| **搜索代码** | 🟢 低风险 | 智能恢复 → 调整参数 | `rg_search` 无结果 → 放宽模式 |

### 场景分析

#### 场景 1：安装软件版本错误

```
User: 安装 numpy 9.9.9
Agent: pip install numpy==9.9.9
Result: ERROR: Could not find a version that satisfies the requirement
```

**❌ 错误做法：**
Agent 自行决定安装 numpy 最新版 `pip install numpy`

**✅ 正确做法：**
Agent 暂停并报告：
> "安装失败：numpy 9.9.9 版本不存在。可用版本：1.26.4, 1.26.3... 请确认要安装哪个版本？"

#### 场景 2：读取文件不存在

```
User: 读取 main.py
Agent: read_file("main.py")
Result: Error: File not found: main.py
```

**✅ 可以接受的做法：**
Agent 智能恢复：
> "文件 main.py 不存在。搜索到 src/main.py，正在读取..."

### 实现状态

#### Phase 1 ✅ (已完成)

- **System Prompt 增强**: 在 `_build_system_prompt()` 中添加 **CRITICAL ERROR HANDLING RULES**
- **策略文档化**: 三级风险策略明确写入系统提示

#### Phase 2 ✅ (已完成)

- **风险等级标记**: `RiskLevel` 枚举 + 工具注册时标记
- **运行时检测**: `Tool.is_high_risk_operation()` 检测具体调用
- **强制拦截**: Agent 层 `PendingConfirmation` 状态管理
- **交互确认**: REPL 层 `_handle_pending_confirmation()` 实现
- **测试覆盖**: 14 个测试用例验证

| 工具 | 风险等级 | 检测模式 |
|------|----------|----------|
| `bash` | HIGH | pip install, apt, rm, sudo, curl, \| sh 等 |
| `write_file` | MEDIUM | - |
| `edit_file` | MEDIUM | - |
| `read_file` | LOW | - |
| `rg_search` | LOW | - |
| `ast_grep_search` | LOW | - |
| `skill` | LOW | - |

---

*Last updated: 2026-03-19*
