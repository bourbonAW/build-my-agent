# Skill 增强设计：变量替换 + allowed-tools 生效

**日期：** 2026-04-09  
**范围：** `src/bourbon/skills.py`, `src/bourbon/tools/skill_tool.py`

---

## 背景

Bourbon 的 skill 系统基础架构（发现、三层披露、工具调用）已经完整可用。本次优化针对两个"声明了但没生效"的漏洞：

1. Skill 内容无法引用自身目录路径，也无法接收调用参数
2. `allowed-tools` frontmatter 字段被解析存储，但激活时对 LLM 可用工具列表没有任何影响

---

## Feature 1：变量替换

### 目标

Skill 内容支持以下变量，在 `render_for_activation()` 时展开：

| 变量 | 含义 |
|------|------|
| `$ARGUMENTS` | 调用 skill 时传入的参数字符串（无参数时为空字符串） |
| `${CLAUDE_SKILL_DIR}` | skill 的 base 目录绝对路径（`SKILL.md` 的父目录） |

### 改动

**`skills.py` — `Skill.render_for_activation()`**

新增 `args: str = ""` 参数。在组装 body 内容后、返回前执行替换：

```python
def render_for_activation(self, args: str = "") -> str:
    # ... 现有逻辑 ...
    content = "\n".join(lines)
    content = content.replace("$ARGUMENTS", args)
    content = content.replace("${CLAUDE_SKILL_DIR}", str(self.base_dir))
    return content
```

**`skills.py` — `SkillManager.activate()`**

新增 `args: str = ""` 参数，透传给 `render_for_activation()`：

```python
def activate(self, name: str, args: str = "") -> str:
    ...
    return skill.render_for_activation(args=args)
```

**`tools/skill_tool.py` — `skill_handler`**

input_schema 新增可选 `args` 字段，调用时传入：

```python
# input_schema 新增：
"args": {
    "type": "string",
    "description": "Optional arguments passed to the skill ($ARGUMENTS substitution)"
}

# handler 签名：
def skill_handler(name: str, args: str = "", *, ctx: ToolContext) -> str:
    ...
    return manager.activate(name, args=args)
```

### 行为说明

- 替换是简单字符串替换，按顺序执行，不支持嵌套或条件逻辑
- 若 skill 内容中不包含这些变量，透明无副作用
- `${CLAUDE_SKILL_DIR}` 的替换在 `render_for_activation()` 内执行，而非 scanner 时，确保路径是运行时真实路径

---

## Feature 2：`allowed-tools` 生效

### 目标

当 skill 在 frontmatter 中声明 `allowed-tools`，激活该 skill 后，这些工具应出现在后续 LLM 调用的工具列表中。

### 架构利用

bourbon 已有 discovered tools 机制：

- `Agent._discovered_tools: set[str]` — 运行时累积的"已发现"工具名集合
- `definitions(discovered=...)` — 只返回 `always_load=True` 或在 `discovered` 集合中的工具
- `ToolContext.on_tools_discovered` — 工具执行时可向该集合注入新工具名的回调

skill_handler 已经可以访问 `ctx`，因此不需要改动 agent.py。

### 改动

**`tools/skill_tool.py` — `skill_handler`**

激活 skill 后，将其 `allowed_tools` 注入 discovered 集合：

```python
def skill_handler(name: str, args: str = "", *, ctx: ToolContext) -> str:
    manager = ctx.skill_manager if ctx.skill_manager is not None else get_skill_manager()

    try:
        if manager.is_activated(name):
            return f'<skill_already_loaded name="{name}"/>\n\nSkill \'{name}\' is already active.'

        content = manager.activate(name, args=args)

        # 将 skill 声明的工具注入 discovered 集合
        skill = manager.get_skill(name)
        if skill and skill.allowed_tools and ctx.on_tools_discovered:
            ctx.on_tools_discovered(set(skill.allowed_tools))

        return content
    except SkillValidationError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error activating skill '{name}': {e}"
```

### 行为说明

- 工具名大小写敏感，需与注册时的 `name` 完全一致（如 `Read`、`Bash`、`WebSearch`）
- 若 skill 声明了未注册的工具名，`definitions()` 不会报错，该工具名被静默忽略
- 效果在当前 step 的**下一轮** LLM 调用时生效（当前 tool_use 轮次完成后，agent 用新的 `discovered` 集合重新调 LLM）
- `allowed_tools` 一旦注入就持续到 session 结束，不会自动撤销——与 Claude Code inline 模式一致

---

## 不在本次范围内

- Shell 命令内联执行（`` !`cmd` ``）
- `model:` per-skill 覆盖
- Fork 模式（子代理执行）
- 条件 skill 激活（`paths:` 字段）
- Hooks 注册
- 权限系统（allow/deny rules）

---

## 受影响文件

| 文件 | 改动类型 |
|------|---------|
| `src/bourbon/skills.py` | `Skill.render_for_activation()` 加 `args` 参数 + 变量替换逻辑；`SkillManager.activate()` 加 `args` 透传 |
| `src/bourbon/tools/skill_tool.py` | `skill_handler` 加 `args` 参数；激活后注入 `allowed_tools` |

测试文件预期新增：`tests/test_skills.py`（或在已有 skill 测试文件中添加用例）
