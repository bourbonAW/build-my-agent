# Investment Agent - UV Quick Start

## 使用 uv 管理依赖（推荐方式）

### 1. 创建虚拟环境并安装依赖

```bash
cd ~/investment-skill

# 创建虚拟环境（.venv）
uv venv

# 安装所有依赖（从 pyproject.toml）
uv pip install -e .

# 安装 Playwright 浏览器
uv run playwright install chromium
```

### 2. 使用 uv run 运行（无需激活虚拟环境）

```bash
# 运行所有技能
uv run python -m investment-agent

# 或具体技能
uv run python -m skills.fund_monitor
uv run python -m skills.macro_liquidity
uv run python -m skills.daily_summary
uv run python -m skills.semiconductor_tracker

# 使用快捷命令（安装后可使用）
uv run fund-monitor
uv run macro-liquidity
uv run daily-summary
uv run semi-tracker
```

### 3. 依赖管理

```bash
# 添加新依赖
uv add akshare

# 添加开发依赖
uv add --dev pytest

# 更新所有依赖
uv pip compile pyproject.toml -o requirements.lock
uv pip sync requirements.lock

# 锁定当前环境
uv pip freeze > requirements.lock
```

### 4. 开发工作流

```bash
# 格式化代码
uv run black .

# 代码检查
uv run ruff check .

# 类型检查
uv run mypy .

# 运行测试
uv run pytest
```

## 传统方式（对比）

### pip 方式
```bash
pip install -r requirements.txt
python __main__.py
```

### uv 优势
- ⚡ 更快的依赖解析和安装
- 🗂️ 更好的依赖锁定（uv.lock）
- 🔄 自动虚拟环境管理
- 📦 无需手动激活环境
- 🎯 通过 `uv run` 直接执行

## 配置 Claude Code 使用 uv

在 `~/.claude/CLAUDE.md` 中添加：

```markdown
## Investment Agent Skill

When running investment-agent commands, use `uv run`:

```bash
# Instead of:
python ~/investment-skill/__main__.py

# Use:
uv run --directory ~/investment-skill python -m investment-agent
```
```

## 常用命令速查

| 操作 | 命令 |
|------|------|
| 创建环境 | `uv venv` |
| 安装依赖 | `uv pip install -e .` |
| 运行脚本 | `uv run python script.py` |
| 添加包 | `uv add package_name` |
| 添加开发包 | `uv add --dev package_name` |
| 更新包 | `uv pip install --upgrade package_name` |
| 锁定依赖 | `uv pip freeze > requirements.lock` |
| 同步环境 | `uv pip sync requirements.lock` |
