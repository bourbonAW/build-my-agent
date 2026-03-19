# Bourbon Stage A 评测清单

## 关键设计验证：错误处理策略

> ⚠️ **重要**: 参考 vault 笔记 `~/vault-notes/projects/bourbon/topics/error-handling-strategy.md`

### 禁止的行为

- [x] **自动降级** - 命令失败后自动使用备选方案 (通过 system prompt 禁止)
- [x] **静默绕过** - 失败时跳过该步骤继续执行 (工具层返回明确错误)
- [x] **自动重试** - 未经用户同意的重试机制 (通过 system prompt 禁止)

### 必须的行为

- [x] **立即暂停** - 关键操作失败时立即停止 (system prompt 要求 HIGH RISK 操作必须暂停)
- [x] **明确报告** - 向用户清晰展示失败原因 (工具层返回 Error: 前缀信息)
- [~] **请求确认** - 询问用户如何处理 (system prompt 要求，需 LLM 配合)
- [ ] **记录决策** - 将用户的选择记录到任务日志

### 工具级别检查

#### bash 工具
- [ ] 命令执行失败时是否暂停并报告
- [ ] 超时错误是否明确提示
- [ ] 危险命令拦截是否清晰说明原因

#### read_file 工具
- [ ] 文件不存在时是否报告错误（而非返回空）
- [ ] 路径越界时是否明确拒绝
- [ ] 权限不足时是否清晰说明

#### write_file 工具
- [ ] 写入失败时是否暂停
- [ ] 磁盘满时是否明确报告
- [ ] 是否等待用户确认后重试

#### edit_file 工具
- [ ] 匹配失败时是否报告（而非静默跳过）
- [ ] 文件不存在时是否明确提示
- [ ] 多行替换失败时是否说明原因

#### rg_search / ast_grep_search 工具
- [ ] "无结果"和"执行错误"是否区分
- [ ] 工具未安装时是否明确提示
- [ ] 搜索超时是否报告

### 评测方法

1. **故意制造失败场景**:
   ```bash
   # 测试 read_file
   read_file("不存在的文件.txt")
   
   # 测试 bash
   bash("exit 1")
   
   # 测试 write_file（权限不足）
   write_file("/root/test.txt", "content")
   ```

2. **观察 Agent 行为**:
   - 是否自动尝试其他方案？（不应该）
   - 是否静默继续？（不应该）
   - 是否暂停并请求确认？（应该）

3. **验证交互质量**:
   - 错误信息是否清晰
   - 用户选项是否明确
   - 决策记录是否完整

### 反例检测

检查代码中是否存在以下模式：
```python
# ❌ 发现问题
if error:
    return fallback()  # 自动降级
    
# ❌ 发现问题  
try:
    return operation()
except:
    return ""  # 静默绕过
    
# ❌ 发现问题
if error:
    return retry()  # 未经同意的重试
```

### 通过标准

- 所有"禁止的行为"检查项必须为 **否**
- 所有"必须的行为"检查项必须为 **是**
- 所有工具级别检查必须通过

---

## 实施进度

### Phase 1: System Prompt 增强 ✅ (已完成)

**实施内容：**
1. 在 `agent.py` 的 `_build_system_prompt()` 中添加 **CRITICAL ERROR HANDLING RULES**
2. 定义三级风险策略：HIGH / MEDIUM / LOW
3. 明确禁止自动切换版本、自动改变参数等行为
4. 添加 7 个测试用例验证策略存在性

**验证方式：**
```bash
pytest tests/test_agent_error_policy.py -v
```

**结果：** 7/7 测试通过

### Phase 2: 强制拦截机制 ✅ (已完成)

**实施内容：**
1. ✅ 添加 `RiskLevel` 枚举 (LOW/MEDIUM/HIGH)
2. ✅ 在 `@register_tool` 装饰器中添加 `risk_level` 和 `risk_patterns` 参数
3. ✅ 为所有工具标记风险等级：
   - HIGH: `bash` (带风险模式检测)
   - MEDIUM: `write_file`, `edit_file`
   - LOW: `read_file`, `rg_search`, `ast_grep_search`, `skill`
4. ✅ 在 Agent 层添加 `PendingConfirmation` 状态管理
5. ✅ 在 `_execute_tools` 中检测高风险操作失败并暂停
6. ✅ 在 REPL 层添加交互式确认界面
7. ✅ 添加 14 个测试用例验证风险等级检测

**风险模式检测（bash）：**
- pip/pip3 install/uninstall
- apt/apt-get/yum/brew/pacman/dnf
- rm/rmdir
- sudo/su
- shutdown/reboot/halt
- mkfs/fdisk/dd
- curl/wget/| sh/| bash

**验证方式：**
```bash
pytest tests/test_risk_level.py -v
```

**结果：** 14/14 测试通过

---

*Phase 1 完成于 2026-03-19*  
*Phase 2 完成于 2026-03-19*

### Phase 3: Agent Skills 规范兼容改造 ✅ (已完成)

**参考规范**: https://agentskills.io/specification

**实施内容：**
1. ✅ 重构 Skill 系统架构
   - 新增 `SkillScanner` - 多作用域技能发现
   - 新增 `SkillManager` - 技能生命周期管理
   - 新增 `Skill` dataclass - 完整元数据支持

2. ✅ 扩展目录扫描范围
   - 项目级: `{workdir}/.agents/skills`, `{workdir}/.bourbon/skills`
   - 用户级: `~/.agents/skills`, `~/.bourbon/skills`
   - 向后兼容: `~/.claude/skills`

3. ✅ 渐进式披露 (Progressive Disclosure)
   - **Tier 1**: System prompt 中包含 skill catalog (name + description)
   - **Tier 2**: 通过 `skill` 工具激活时返回完整 instructions
   - **Tier 3**: 按需加载 resources (scripts/references/assets)

4. ✅ 支持标准子目录结构
   - `scripts/` - 可执行脚本
   - `references/` - 参考文档
   - `assets/` - 模板和资源文件

5. ✅ 改进激活机制
   - Model-driven: LLM 根据 catalog 自主决定何时激活
   - User-explicit: `/skill/skill-name` slash command
   - Deduplication: 防止重复激活

6. ✅ Skill 内容保护
   - Skill 内容免于 context compaction
   - 在 compressed context 中保留 skill instructions

7. ✅ 命名规范验证
   - 小写字母、数字、连字符
   - 不超过 64 字符
   - 不以连字符开头/结尾
   - 无连续连字符

8. ✅ 新增测试
   - `tests/test_skills_new.py` - 19 个测试用例
   - 验证命名规范、渲染格式、资源管理、扫描逻辑

**验证方式：**
```bash
pytest tests/test_skills_new.py -v
pytest tests/test_integration.py -v
```

**结果：** 
- 19/19 新技能测试通过
- 101/101 总测试通过

---

*Phase 1 完成于 2026-03-19*  
*Phase 2 完成于 2026-03-19*  
*Phase 3 完成于 2026-03-19*
