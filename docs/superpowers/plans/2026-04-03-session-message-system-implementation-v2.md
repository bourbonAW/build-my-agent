# Bourbon Session System Implementation Plan (v2 - 修正版)

> **Status:** COMPLETED — Tasks 1-10 complete  
> **Spec:** `docs/superpowers/specs/2026-04-03-session-message-system-design-v2.md`  
> **Key Fixes:** logical_parent semantics, two-layer persistence, grouped tool results, sidechain deprioritized  
> **Post-review-1 fixes:** C1 compact() dead code, C2 streaming path (Task 6b), I3 trigger param, I4 append mutation doc, M4 test reachability assertion  
> **Post-review-2 fixes:** F1 compact manifest persistence, F2 grouped tool results, F3 simplified recovery, F4 all migration entry points  
> **Post-review-3 fixes:** F1 spec synced, F2 maybe_compact trigger param, F3 handle_confirmation non-stream, F4 test replaced+success criteria, F5a usage before add, F5b session_id override in add_message  
> **Post-review-4 fixes:** F1 source_tool_uuid constraint, F2 doc table + summary cleanup  
> **Post-review-5 fixes:** F1 removed _recover_tool_results (impossible crash state), F2 bare return statements, F3 compact manifest round-trip test  
> **Post-review-6 fixes:** F1 rebuild applies overrides by mutating msg.parent_uuid before traversal, F2 spec/plan navigation layer cleanup

---

## 关键变更总结

### v1 → v2 的修正

| 问题 | v1 错误 | v2 修正 |
|------|---------|---------|
| logical_parent_uuid | 用于 active chain 回溯 | **只用于调试，不参与链构建** |
| 持久化模型 | 混淆可变/不可变 | **明确两层：append-only transcript + mutable memory chain** |
| Tool round | 缺少 source_tool_uuid，多条分散 | **完整实现 parent 指向 + grouped tool results（一轮一条 user message）** |
| Sidechain | 列为目标但未规划 | **从目标中移除** |
| messages setter | 兼容性层不可用 | **保留 deprecated setter（`warnings.warn`），重写所有直接 `.append` call sites** |
| 返回类型漂移 | spec/plan 不一致 | **统一使用 dataclass，不用 dict** |

---

## 文件结构

```
src/bourbon/session/
├── __init__.py              # 导出
├── types.py                 # 核心类型
├── chain.py                 # MessageChain (内存链)
├── storage.py               # TranscriptStore (持久化)
├── context.py               # Token + Compact 策略
└── manager.py               # Session + SessionManager

src/bourbon/
├── agent.py                 # 重写以使用 Session
├── repl.py                  # 重写消息追加逻辑
└── compression.py           # 标记为废弃

tests/session/
├── test_types.py
├── test_chain.py            # 测试 active chain 构建
├── test_storage.py          # 测试两层模型
├── test_context.py
├── test_manager.py
└── test_compact_manifest.py # 新增：compact manifest round-trip
```

---

## Task 1: 核心类型 (types.py)

**Files:**
- Create: `src/bourbon/session/types.py`
- Create: `tests/session/test_types.py`

- [x] **Step 1: 编写类型定义**

```python
"""Core types for Session System"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4


class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CompactTrigger(Enum):
    MANUAL = "manual"
    AUTO_THRESHOLD = "auto_threshold"
    AUTO_EMERGENCY = "auto_emergency"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    
    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class TextBlock:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass(frozen=True)
class ToolUseBlock:
    type: Literal["tool_use"] = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResultBlock:
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False


MessageContent = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass
class CompactMetadata:
    trigger: CompactTrigger
    pre_compact_token_count: int
    post_compact_token_count: int
    first_archived_uuid: UUID
    last_archived_uuid: UUID
    summary: str
    archived_at: datetime = field(default_factory=datetime.now)


@dataclass
class TranscriptMessage:
    """
    消息结构 - 关键设计：
    
    1. parent_uuid: 唯一用于构建 active chain 的边
    2. logical_parent_uuid: 仅用于调试展示，不参与链构建
    3. source_tool_uuid: tool_result -> 生成它的 assistant message
    """
    uuid: UUID = field(default_factory=uuid4)
    session_id: UUID = field(default_factory=uuid4)
    
    # Chain structure
    parent_uuid: UUID | None = None
    logical_parent_uuid: UUID | None = None  # 仅用于调试！
    
    # Content
    role: MessageRole = MessageRole.USER
    content: list[MessageContent] = field(default_factory=list)
    
    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    usage: TokenUsage | None = None
    
    # Tool association (CRITICAL)
    source_tool_uuid: UUID | None = None
    
    # Sidechain (预留，本期不实现)
    is_sidechain: bool = False
    agent_id: str | None = None
    
    # Compact
    is_compact_boundary: bool = False
    compact_metadata: CompactMetadata | None = None
    
    def to_llm_format(self) -> dict:
        """转换为 LLM API 格式"""
        content_list = []
        for block in self.content:
            block_dict = {"type": block.type}
            if isinstance(block, TextBlock):
                block_dict["text"] = block.text
            elif isinstance(block, ToolUseBlock):
                block_dict["id"] = block.id
                block_dict["name"] = block.name
                block_dict["input"] = block.input
            elif isinstance(block, ToolResultBlock):
                block_dict["tool_use_id"] = block.tool_use_id
                block_dict["content"] = block.content
                block_dict["is_error"] = block.is_error
            content_list.append(block_dict)
        
        return {
            "role": self.role.value,
            "content": content_list,
        }


@dataclass
class SessionMetadata:
    uuid: UUID
    parent_uuid: UUID | None
    project_dir: str
    created_at: datetime
    last_activity: datetime
    message_count: int = 0
    total_tokens_used: int = 0
    is_active: bool = True
    description: str = ""


@dataclass
class SessionSummary:
    uuid: UUID
    description: str
    last_activity: datetime
    message_count: int
    is_resumable: bool


@dataclass
class CompactResult:
    """Compact 操作结果"""
    success: bool
    archived_count: int = 0
    preserved_count: int = 0
    boundary_uuid: UUID | None = None
    reason: str = ""
    # Finding 1 fix: compact 修改了内存中的 parent_uuid，调用方必须持久化这些变更
    # key: str(uuid), value: str(new_parent_uuid) | None
    parent_uuid_overrides: dict[str, str | None] = field(default_factory=dict)
```

- [x] **Step 2: 编写基础测试**

```python
# tests/session/test_types.py
import pytest
from uuid import uuid4

from bourbon.session.types import (
    MessageRole,
    TranscriptMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    TokenUsage,
    CompactResult,
)


def test_transcript_message_creation():
    """测试消息创建"""
    msg = TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="Hello")],
    )
    assert msg.role == MessageRole.USER
    assert msg.parent_uuid is None
    assert msg.logical_parent_uuid is None


def test_transcript_message_to_llm_format():
    """测试 LLM 格式转换"""
    msg = TranscriptMessage(
        role=MessageRole.ASSISTANT,
        content=[
            TextBlock(text="Let me check"),
            ToolUseBlock(id="tool_1", name="read_file", input={"path": "test.py"}),
        ],
    )
    
    llm_format = msg.to_llm_format()
    assert llm_format["role"] == "assistant"
    assert len(llm_format["content"]) == 2
    assert llm_format["content"][0]["type"] == "text"
    assert llm_format["content"][1]["type"] == "tool_use"


def test_tool_result_block():
    """测试 tool result"""
    block = ToolResultBlock(
        tool_use_id="tool_1",
        content="File content",
        is_error=False,
    )
    assert block.tool_use_id == "tool_1"
    assert block.is_error is False


def test_token_usage_addition():
    """测试 TokenUsage 加法"""
    u1 = TokenUsage(input_tokens=100, output_tokens=50)
    u2 = TokenUsage(input_tokens=50, output_tokens=25)
    total = u1 + u2
    assert total.input_tokens == 150
    assert total.output_tokens == 75


def test_compact_result():
    """测试 CompactResult"""
    result = CompactResult(
        success=True,
        archived_count=10,
        preserved_count=5,
        reason="test",
    )
    assert result.success is True
    assert result.archived_count == 10
```

- [x] **Step 3: 运行测试**

```bash
pytest tests/session/test_types.py -v
# Expected: 5 tests PASS
```

- [x] **Step 4: Commit**

```bash
git add src/bourbon/session/types.py tests/session/test_types.py
git commit -m "feat(session): add core types with correct semantics"
```

---

## Task 2: MessageChain (v2 修正版)

**Files:**
- Create: `src/bourbon/session/chain.py`
- Create: `tests/session/test_chain.py`

- [x] **Step 1: 编写 MessageChain**

```python
"""MessageChain - Active conversation chain (in-memory only)"""

from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID

from .types import (
    TranscriptMessage,
    MessageRole,
    TextBlock,
    CompactResult,
    ToolUseBlock,
    ToolResultBlock,
    CompactMetadata,
    CompactTrigger,
)


class MessageChain:
    """
    Active Message Chain - 内存中的可变链
    
    职责：
    1. 维护当前活跃的消息（用于 LLM 对话）
    2. 使用 parent_uuid 构建 active chain（logical_parent_uuid 不参与！）
    3. 执行 compact（从内存中删除旧消息）
    
    注意：这不负责持久化！
    """
    
    def __init__(self):
        self._messages: OrderedDict[UUID, TranscriptMessage] = OrderedDict()
        self._leaf_uuid: UUID | None = None
        self._root_uuid: UUID | None = None
    
    @property
    def leaf_uuid(self) -> UUID | None:
        return self._leaf_uuid
    
    @property
    def message_count(self) -> int:
        return len(self._messages)
    
    def append(self, message: TranscriptMessage) -> None:
        """
        添加消息到 active chain
        
        自动设置 parent_uuid 为当前叶子。
        
        I4 note: 此方法会直接修改传入的 message.parent_uuid！
        调用方需知晓 append() 会取得该对象的所有权并发生变更。
        如果调用方创建了带有明确 parent_uuid 的消息（例如 rebuild 期间），
        请勿再调用 append()，而是直接操作 self._messages。
        """
        if self._leaf_uuid:
            message.parent_uuid = self._leaf_uuid
        else:
            self._root_uuid = message.uuid
        
        self._messages[message.uuid] = message
        self._leaf_uuid = message.uuid
    
    def get(self, uuid: UUID) -> TranscriptMessage | None:
        return self._messages.get(uuid)
    
    def build_active_chain(self) -> list[TranscriptMessage]:
        """
        构建活跃对话链 - 只使用 parent_uuid！
        
        CRITICAL: logical_parent_uuid 不参与链构建！
        
        Returns:
            从根到叶的消息列表
        """
        chain: list[TranscriptMessage] = []
        seen: set[UUID] = set()
        current_uuid = self._leaf_uuid
        
        while current_uuid and current_uuid not in seen:
            seen.add(current_uuid)
            message = self._messages.get(current_uuid)
            if not message:
                break
            
            chain.append(message)
            
            # CRITICAL: 只使用 parent_uuid！
            current_uuid = message.parent_uuid
        
        chain.reverse()
        return chain
    
    def get_llm_messages(self) -> list[dict]:
        """
        获取给 LLM 的消息列表
        
        过滤：
        - compact_boundary 消息不传给 LLM
        - sidechain 消息（本期不实现，预留）
        """
        chain = self.build_active_chain()
        llm_messages = []
        
        for msg in chain:
            if msg.is_compact_boundary:
                continue
            if msg.is_sidechain:  # 预留
                continue
            llm_messages.append(msg.to_llm_format())
        
        return llm_messages
    
    def compact(
        self,
        preserve_count: int = 3,
        summary: str = "",
        trigger: CompactTrigger = CompactTrigger.AUTO_THRESHOLD,  # I3 fix: 不再硬编码
    ) -> CompactResult:
        """
        Compact active chain
        
        操作：
        1. 保留最近 preserve_count 条消息
        2. 从内存链中删除旧消息（transcript 中仍保留）
        3. 创建 compact_boundary 消息
        4. 更新 parent_uuid
        
        Args:
            trigger: 触发原因（MANUAL, AUTO_THRESHOLD, AUTO_EMERGENCY）
        
        Returns:
            CompactResult
        """
        chain = self.build_active_chain()
        
        if len(chain) <= preserve_count:
            return CompactResult(
                success=False,
                reason=f"insufficient_messages: {len(chain)} <= {preserve_count}",
            )
        
        to_archive = chain[:-preserve_count]
        to_preserve = chain[-preserve_count:]
        
        first_archived = to_archive[0]
        last_archived = to_archive[-1]
        first_preserved = to_preserve[0]
        
        # 创建 compact_boundary 消息
        boundary = TranscriptMessage(
            role=MessageRole.SYSTEM,
            content=[TextBlock(text=f"[Context compressed: {summary}]")],
            is_compact_boundary=True,
            compact_metadata=CompactMetadata(
                trigger=trigger,  # I3 fix: 使用传入的 trigger
                # M3 note: 字段名含 token 但存的是消息数量，后续可改为实际 token 数
                pre_compact_token_count=len(to_archive),
                post_compact_token_count=len(to_preserve),
                first_archived_uuid=first_archived.uuid,
                last_archived_uuid=last_archived.uuid,
                summary=summary,
            ),
        )
        
        # 从内存中删除归档消息
        for msg in to_archive:
            del self._messages[msg.uuid]
        
        # boundary 的 parent 为 None（compact 边界，断开与已归档消息的 active chain 连接）
        boundary.parent_uuid = None
        # logical_parent_uuid 仅用于记录（不参与链构建）
        boundary.logical_parent_uuid = last_archived.uuid
        
        self._messages[boundary.uuid] = boundary
        
        # 第一个保留消息的 parent 指向 boundary
        first_preserved.parent_uuid = boundary.uuid
        # logical_parent_uuid 保留原来的连接（仅用于调试）
        first_preserved.logical_parent_uuid = last_archived.uuid
        
        # C1 fix: 无条件更新 _leaf_uuid 和 _root_uuid
        self._leaf_uuid = to_preserve[-1].uuid
        self._root_uuid = boundary.uuid
        
        # Finding 1 fix: 记录 parent_uuid 变更，供调用方持久化到 compact manifest
        # 这些变更只在内存中发生，TranscriptStore 是 append-only，
        # 必须通过 manifest 文件持久化，否则重启后 rebuild_from_transcript 会撤销 compact。
        parent_uuid_overrides: dict[str, str | None] = {
            str(boundary.uuid): None,  # boundary.parent_uuid = None
            str(first_preserved.uuid): str(boundary.uuid),  # first_preserved -> boundary
        }
        
        return CompactResult(
            success=True,
            archived_count=len(to_archive),
            preserved_count=len(to_preserve),
            boundary_uuid=boundary.uuid,
            parent_uuid_overrides=parent_uuid_overrides,  # 调用方必须持久化
        )
    
    def clear(self) -> None:
        """
        清空 active chain
        
        注意：只清空内存，transcript 不受影响
        """
        self._messages.clear()
        self._leaf_uuid = None
        self._root_uuid = None
    
    def rebuild_from_transcript(
        self,
        transcript: list[TranscriptMessage],
        resume_from: UUID | None = None,
        parent_uuid_overrides: dict[str, str | None] | None = None,
    ) -> None:
        """
        从 transcript 重建 active chain。
        
        Finding 1 fix: 在遍历前 apply compact manifest 中的 parent_uuid overrides，
        保证重启后链结构与 compact 后内存状态一致。
        
        Args:
            transcript: 完整的消息历史（来自 JSONL）
            resume_from: 从指定消息恢复，None 则自动选择最新的非 boundary 消息
            parent_uuid_overrides: compact manifest 中的 parent_uuid 覆盖表
                                   { str(msg_uuid): str(new_parent_uuid) | None }
        """
        self.clear()
        
        if not transcript:
            return
        
        # 构建 UUID -> Message 映射
        msg_map = {msg.uuid: msg for msg in transcript}
        
        # Finding 1 fix: apply overrides BEFORE traversal
        # 这样 rebuild 的回溯路径与 compact 后的内存状态一致
        if parent_uuid_overrides:
            for uuid_str, new_parent_str in parent_uuid_overrides.items():
                try:
                    msg_uuid = UUID(uuid_str)
                    if msg_uuid in msg_map:
                        msg_map[msg_uuid].parent_uuid = (
                            UUID(new_parent_str) if new_parent_str else None
                        )
                except ValueError:
                    continue  # 忽略格式错误的 UUID
        
        # 确定 resume point
        if resume_from is None:
            for msg in reversed(transcript):
                if not msg.is_compact_boundary:
                    resume_from = msg.uuid
                    break
        
        if resume_from is None or resume_from not in msg_map:
            return
        
        # 从 resume point 回溯构建链（只用 parent_uuid）
        chain: list[TranscriptMessage] = []
        seen: set[UUID] = set()
        current_uuid = resume_from
        
        while current_uuid and current_uuid not in seen:
            seen.add(current_uuid)
            msg = msg_map.get(current_uuid)
            if not msg:
                break
            chain.append(msg)
            current_uuid = msg.parent_uuid
        
        chain.reverse()
        for msg in chain:
            self._messages[msg.uuid] = msg
        
        if chain:
            self._root_uuid = chain[0].uuid
            self._leaf_uuid = chain[-1].uuid
        
        # Finding 1 fix（post-review-4 移除 _recover_tool_results 的说明）：
        # Session.add_message() 的执行顺序是 chain.append() 先于 append_to_transcript()。
        # 因此"tool_result_msg 在 transcript 但 parent_uuid=None 且未入链"这个状态不可能出现：
        #   - crash 在 append_to_transcript 之前 → msg 不在 transcript，无从恢复
        #   - crash 在 append_to_transcript 之后 → msg 在 transcript 且有正确 parent_uuid，
        #     正常 rebuild 遍历就能找到，不需要额外 recovery
        # 原 _recover_tool_results 处理的是一个不存在的状态，已移除。


# Helper for compatibility
def build_conversation_from_transcript(
    transcript: list[TranscriptMessage],
) -> list[TranscriptMessage]:
    """
    从完整 transcript 构建对话链（用于调试）
    
    注意：这可能会包含已被 compact 的消息，仅用于调试展示！
    """
    if not transcript:
        return []
    
    # 找到最新的非 boundary 消息
    start_uuid = None
    for msg in reversed(transcript):
        if not msg.is_compact_boundary:
            start_uuid = msg.uuid
            break
    
    if not start_uuid:
        return []
    
    msg_map = {msg.uuid: msg for msg in transcript}
    
    # 使用 logical_parent_uuid 构建逻辑链（仅用于展示）
    chain = []
    seen = set()
    current = start_uuid
    
    while current and current not in seen:
        seen.add(current)
        msg = msg_map.get(current)
        if not msg:
            break
        chain.append(msg)
        # 展示时使用 logical_parent_uuid
        current = msg.logical_parent_uuid or msg.parent_uuid
    
    chain.reverse()
    return chain
```

- [x] **Step 2: 编写测试**

```python
# tests/session/test_chain.py
import pytest
from uuid import uuid4

from bourbon.session.chain import MessageChain, build_conversation_from_transcript
from bourbon.session.types import (
    TranscriptMessage,
    MessageRole,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


class TestMessageChain:
    """MessageChain 测试"""
    
    def test_empty_chain(self):
        """测试空链"""
        chain = MessageChain()
        assert chain.message_count == 0
        assert chain.build_active_chain() == []
    
    def test_append_builds_parent_links(self):
        """测试 append 构建 parent 链接"""
        chain = MessageChain()
        
        msg1 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
        chain.append(msg1)
        
        msg2 = TranscriptMessage(role=MessageRole.ASSISTANT, content=[TextBlock(text="2")])
        chain.append(msg2)
        
        assert msg2.parent_uuid == msg1.uuid
        assert chain.leaf_uuid == msg2.uuid
    
    def test_build_active_chain_order(self):
        """测试 active chain 顺序"""
        chain = MessageChain()
        
        msgs = [
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text=str(i))])
            for i in range(3)
        ]
        for msg in msgs:
            chain.append(msg)
        
        active = chain.build_active_chain()
        assert len(active) == 3
        assert active[0] == msgs[0]
        assert active[1] == msgs[1]
        assert active[2] == msgs[2]
    
    def test_compact_removes_from_memory(self):
        """测试 compact 从内存删除消息"""
        chain = MessageChain()
        
        msgs = [
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text=str(i))])
            for i in range(5)
        ]
        for msg in msgs:
            chain.append(msg)
        
        result = chain.compact(preserve_count=2)
        
        assert result.success is True
        assert result.archived_count == 3
        assert result.preserved_count == 2
        assert chain.message_count == 3  # boundary + 2 preserved
        
        # 验证旧消息从内存删除
        assert msgs[0].uuid not in chain._messages
        assert msgs[1].uuid not in chain._messages
        assert msgs[2].uuid not in chain._messages
    
    def test_compact_boundary_not_in_llm_messages(self):
        """测试 boundary 不出现在 LLM 消息中"""
        chain = MessageChain()
        
        for i in range(5):
            chain.append(TranscriptMessage(
                role=MessageRole.USER,
                content=[TextBlock(text=str(i))],
            ))
        
        chain.compact(preserve_count=2)
        
        llm_msgs = chain.get_llm_messages()
        assert len(llm_msgs) == 2  # 只有 preserved 消息
    
    def test_logical_parent_not_used_in_active_chain(self):
        """测试 logical_parent_uuid 不参与 active chain 构建"""
        chain = MessageChain()
        
        msg1 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
        chain.append(msg1)
        
        msg2 = TranscriptMessage(role=MessageRole.ASSISTANT, content=[TextBlock(text="2")])
        chain.append(msg2)
        
        # 修改 logical_parent（模拟错误设置）
        msg2.logical_parent_uuid = uuid4()  # 错误的 UUID
        
        # active chain 应该仍然正确
        active = chain.build_active_chain()
        assert len(active) == 2
        assert active[1] == msg2
    
    def test_clear_empties_chain(self):
        """测试 clear 清空链"""
        chain = MessageChain()
        
        for i in range(3):
            chain.append(TranscriptMessage(
                role=MessageRole.USER,
                content=[TextBlock(text=str(i))],
            ))
        
        chain.clear()
        
        assert chain.message_count == 0
        assert chain.leaf_uuid is None


import copy


class TestCompactManifestRoundTrip:
    """Compact manifest 持久化与重建的关键路径测试
    
    验证核心不变量：compact() 产生的 parent_uuid_overrides 必须经过
    manifest 持久化后，才能保证重启后 rebuild_from_transcript() 正确重建链。
    这是"恢复后下一次重启还得能继续工作"的核心保证。
    
    关键建模约束：
    - transcript 是 append-only，compact 执行前写入磁盘的消息永远保留原始 parent_uuid
    - 测试用 copy.deepcopy 冻结"磁盘状态"快照，避免被 compact() 的内存修改污染
    - compact 执行后，boundary_msg 被追加到 transcript（maybe_compact 行为）
    """
    
    def test_compact_manifest_survives_restart(self):
        """
        验证 compact → save manifest → rebuild_from_transcript 的完整 round-trip。
        
        场景：
        1. 链中有 5 条消息，每条 append 时模拟持久化（deepcopy 冻结磁盘状态）
        2. compact(preserve_count=2) 归档前 3 条，保留后 2 条
        3. boundary_msg 追加到 disk_transcript（模拟 maybe_compact 行为）
        4. 保存 parent_uuid_overrides 到 manifest
        5. 模拟重启：用 disk_transcript（含 boundary）+ manifest 重建
        6. 重建后的链应只包含 boundary + 2 条保留消息（3 条）
        """
        chain = MessageChain()
        msgs = []
        disk_transcript = []  # 模拟 append-only 磁盘：compact 前写入原始 parent_uuid
        
        for i in range(5):
            msg = TranscriptMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=[TextBlock(text=f"message {i}")],
            )
            chain.append(msg)
            msgs.append(msg)
            # 模拟 append_to_transcript：冻结此刻的 parent_uuid（deepcopy）
            disk_transcript.append(copy.deepcopy(msg))
        
        assert chain.message_count == 5
        
        # Step 1: compact，保留最后 2 条
        result = chain.compact(preserve_count=2, summary="archived messages 0-2")
        
        assert result.parent_uuid_overrides, "compact 必须产生 parent_uuid_overrides"
        
        # compact 后内存中的链：1 boundary + 2 preserved = 3 条
        active_after_compact = chain.build_active_chain()
        assert len(active_after_compact) == 3, (
            f"compact 后应有 boundary + 2 preserved，实际 {len(active_after_compact)}"
        )
        assert active_after_compact[0].is_compact_boundary is True, "第一条应是 compact boundary"
        
        # Step 2: 模拟 maybe_compact 把 boundary 追加到 transcript
        boundary_msg = chain.get(result.boundary_uuid)
        disk_transcript.append(boundary_msg)  # boundary 是新消息，未被 deepcopy 过
        
        # Step 3: 持久化 manifest
        saved_overrides = dict(result.parent_uuid_overrides)
        
        # Step 4: 模拟重启 — 用 disk_transcript（含 boundary，5 条原始消息有原始 parent_uuid）
        # + manifest overrides 重建
        new_chain = MessageChain()
        new_chain.rebuild_from_transcript(disk_transcript, parent_uuid_overrides=saved_overrides)
        
        # 验证重建后的链与 compact 后一致：boundary + 2 preserved = 3 条
        rebuilt_active = new_chain.build_active_chain()
        assert len(rebuilt_active) == 3, (
            f"重建后应有 boundary + 2 preserved，实际 {len(rebuilt_active)}"
        )
        assert rebuilt_active[0].is_compact_boundary is True, "重建后第一条应是 compact boundary"
        assert rebuilt_active[-1].uuid == msgs[-1].uuid, "leaf 应是最后一条原始消息"
        assert rebuilt_active[-2].uuid == msgs[-2].uuid, "倒数第二条应是 msgs[-2]"
    
    def test_rebuild_without_manifest_includes_archived(self):
        """
        验证不传 manifest override 时，重建会错误地遍历到所有已归档消息。
        这个测试证明了 manifest 机制的必要性：
        - 有 overrides：first_preserved.parent_uuid → boundary（只遍历 3 条）
        - 无 overrides：first_preserved.parent_uuid → msgs[2]（遍历全部 5 条）
        """
        chain = MessageChain()
        msgs = []
        disk_transcript = []
        
        for i in range(5):
            msg = TranscriptMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=[TextBlock(text=f"message {i}")],
            )
            chain.append(msg)
            msgs.append(msg)
            disk_transcript.append(copy.deepcopy(msg))  # 冻结磁盘状态
        
        result = chain.compact(preserve_count=2, summary="archived")
        assert result.parent_uuid_overrides
        
        # 追加 boundary 到 disk transcript
        boundary_msg = chain.get(result.boundary_uuid)
        disk_transcript.append(boundary_msg)
        
        # 不传 parent_uuid_overrides：disk 中 first_preserved（msgs[3] 的 deepcopy）
        # 的 parent_uuid 仍指向 msgs[2].uuid（原始值）
        # 遍历路径：leaf(msgs[4]) → msgs[3] → msgs[2] → msgs[1] → msgs[0]
        # boundary 不可达（无消息指向它），不出现在 active chain 中
        new_chain = MessageChain()
        new_chain.rebuild_from_transcript(disk_transcript)  # 不传 overrides
        
        rebuilt_active = new_chain.build_active_chain()
        assert len(rebuilt_active) == 5, (
            f"不使用 manifest 时应错误地包含全部 5 条已归档消息，实际 {len(rebuilt_active)}"
        )
```

- [x] **Step 3: 运行测试**

```bash
pytest tests/session/test_chain.py -v
# Expected: 9 tests PASS
```

- [x] **Step 4: Commit**

```bash
git add src/bourbon/session/chain.py tests/session/test_chain.py
git commit -m "feat(session): implement MessageChain with correct parent semantics and compact manifest"
```

---

## Task 3-5: Storage, Context, Manager

（由于篇幅限制，以下简要列出，实际实现参考 v1 plan 并应用上述修正原则）

### Task 3: TranscriptStore (两层模型 + compact manifest)

```python
# Key design: append-only transcript + overwriteable compact manifest
class TranscriptStore:
    def append_to_transcript(self, ...):  # 只追加，永不修改
    def load_transcript(self, ...) -> list[TranscriptMessage]:  # 加载完整历史
    def save_metadata(self, ...):  # 元数据可更新
    
    # Finding 1 fix: compact manifest - 记录 compact 对 parent_uuid 的修改
    # 这是唯一可覆写的文件（不是 append-only），保存最近一次 compact 的链重写信息
    def save_compact_manifest(
        self,
        project_name: str,
        session_id: UUID,
        overrides: dict[str, str | None],  # { str(uuid): str(parent_uuid) | None }
    ) -> None:
        """
        持久化 compact 后的 parent_uuid 修改。每次 compact 覆盖前一次 manifest。
        
        文件路径: {base_dir}/{project_name}/{session_id}.compact.json
        格式: { "overrides": { "uuid_str": "parent_uuid_str_or_null" } }
        """
        path = self.base_dir / project_name / f"{session_id}.compact.json"
        with open(path, "w") as f:
            json.dump({"overrides": overrides}, f, indent=2)
    
    def load_compact_manifest(
        self,
        project_name: str,
        session_id: UUID,
    ) -> dict[str, str | None]:
        """加载 compact manifest，若不存在返回空 dict。"""
        path = self.base_dir / project_name / f"{session_id}.compact.json"
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                data = json.load(f)
            return data.get("overrides", {})
        except (json.JSONDecodeError, KeyError):
            return {}
```

### Task 4: ContextManager (Token + Compact)

```python
# Use correct return types (CompactResult, not dict)
class ContextManager:
    def check_and_compact(self) -> CompactResult | None:
    def get_status(self) -> TokenStatus:
```

### Task 5: SessionManager

```python
class Session:
    def add_message(self, message: TranscriptMessage) -> None:
        # Finding 5b fix: TranscriptMessage.session_id 默认是随机 uuid4()，
        # 必须在这里覆写为当前 session 的 UUID，否则落盘后消息的 session_id 会漂移。
        message.session_id = self.metadata.uuid
        self.chain.append(message)
        self.store.append_to_transcript(...)  # 立即持久化到 transcript
    
    def save(self) -> None:  # 只更新 metadata
        self.store.save_metadata(...)
    
    def maybe_compact(
        self,
        trigger: CompactTrigger = CompactTrigger.AUTO_THRESHOLD,
    ) -> CompactResult | None:
        """
        检查是否需要 compact，如需要则执行并持久化 manifest。
        
        Finding 2 fix: 接受 trigger 参数，允许 /compact 命令传入 MANUAL。
        """
        if trigger == CompactTrigger.AUTO_THRESHOLD and not self.context_manager.should_compact():
            return None
        
        result = self.chain.compact(
            preserve_count=self.config.compact_preserve_count,
            summary=self.context_manager.generate_summary(),
            trigger=trigger,
        )
        
        if result.success:
            # Finding 1 fix: compact 修改了内存中的 parent_uuid，必须立即持久化
            # 否则重启后 rebuild_from_transcript 会用旧 parent_uuid 重走已归档路径
            self.store.append_to_transcript(
                self.project_name, self.metadata.uuid,
                [self.chain.get(result.boundary_uuid)],  # 持久化 boundary 消息
            )
            self.store.save_compact_manifest(
                self.project_name, self.metadata.uuid,
                result.parent_uuid_overrides,  # 持久化 parent_uuid 变更
            )
            self.save()  # 更新 metadata
        
        return result
    
    def load_and_rebuild(self) -> None:
        """从 transcript + manifest 重建 active chain。"""
        transcript = self.store.load_transcript(self.project_name, self.metadata.uuid)
        overrides = self.store.load_compact_manifest(self.project_name, self.metadata.uuid)
        self.chain.rebuild_from_transcript(transcript, parent_uuid_overrides=overrides)
```

---

## Task 6: Agent 重写 (解决向后兼容)

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `src/bourbon/repl.py`

- [x] **Step 1: 重写 Agent 核心方法**

```python
# src/bourbon/agent.py - 关键修改

class Agent:
    def __init__(self, config, workdir=None, session_id=None, resume_last=False, ...):
        # ... 初始化 SessionManager 和 Session ...
        
        # 废弃 _pending_messages，直接使用 Session
    
    def step(self, user_input: str) -> str:
        """完全重写以使用 Session"""
        from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock
        
        # 检查确认状态
        if self.pending_confirmation:
            return self._handle_confirmation_response(user_input)
        
        # 创建并添加用户消息 - 不再使用 self.messages.append
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=user_input)],
        )
        self.session.add_message(user_msg)
        self.session.save()  # 持久化
        
        # 检查压缩
        compact_result = self.session.maybe_compact()
        if compact_result and compact_result.success:
            # 可选：通知用户
            pass
        
        # 运行对话循环
        return self._run_conversation_loop()
    
    def _run_conversation_loop(self) -> str:
        """重写对话循环"""
        tool_round = 0
        
        while tool_round < self._max_tool_rounds:
            # 从 Session 获取消息
            messages = self.session.get_messages_for_llm()
            
            # 调用 LLM
            try:
                response = self.llm.chat(
                    messages=messages,
                    tools=definitions(),
                    system=self.system_prompt,
                )
            except LLMError as e:
                error_msg = f"LLM Error: {e}"
                # 添加错误消息到 Session
                from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock
                self.session.add_message(TranscriptMessage(
                    role=MessageRole.ASSISTANT,
                    content=[TextBlock(text=error_msg)],
                ))
                self.session.save()
                return error_msg
            
            # Finding 5a fix: 先提取 usage，再构造消息，再 add_message
            # 原来是 add -> save -> 再写 usage，transcript 里的记录不含 usage
            usage_data = response.get("usage", {})
            from bourbon.session.types import TokenUsage
            token_usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            ) if usage_data else None
            
            assistant_msg = self._convert_response_to_transcript_message(response)
            assistant_msg.usage = token_usage  # 写入后再 add，transcript 就能捕获到
            self.session.add_message(assistant_msg)
            self.session.save()
            
            # 检查是否有 tool calls
            tool_use_blocks = [
                b for b in response.get("content", [])
                if b.get("type") == "tool_use"
            ]
            
            if not tool_use_blocks:
                # 返回文本响应
                text_parts = [
                    b.get("text", "") for b in response.get("content", [])
                    if b.get("type") == "text"
                ]
                return "".join(text_parts)
            
            # 执行 tools
            tool_results = self._execute_tools(tool_use_blocks)
            
            # 检查确认
            if self.pending_confirmation:
                return self._format_confirmation_prompt()
            
            # Finding 2 fix: 所有 tool results 必须合并到 ONE user TranscriptMessage
            # Anthropic API 要求同一轮的所有 tool_result 在单个 user message 中，
            # 分开存储会导致 get_llm_messages() 产生多个相邻 user turn，violates protocol。
            tool_turn_msg = self._convert_tool_results_to_transcript_message(
                tool_results, assistant_msg.uuid
            )
            self.session.add_message(tool_turn_msg)
            self.session.save()
            tool_round += 1
        
        return "[Reached maximum tool execution rounds]"
    
    def _convert_response_to_transcript_message(self, response: dict) -> TranscriptMessage:
        """转换 LLM 响应为 TranscriptMessage"""
        from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock, ToolUseBlock
        
        content = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                content.append(TextBlock(text=block.get("text", "")))
            elif block.get("type") == "tool_use":
                content.append(ToolUseBlock(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    input=block.get("input", {}),
                ))
        
        return TranscriptMessage(role=MessageRole.ASSISTANT, content=content)
    
    def _convert_tool_results_to_transcript_message(
        self,
        results: list[dict],
        source_assistant_uuid: UUID,
    ) -> TranscriptMessage:
        """
        Finding 2 fix: 将一轮的所有 tool results 合并为单条 TranscriptMessage。
        
        Anthropic 协议要求一轮 tool_use 对应的所有 tool_result 必须在
        同一个 user message 的 content 列表中（多个 ToolResultBlock）。
        分开存储会让 get_llm_messages() 产生多个相邻 user turn，导致 API 拒绝。
        """
        from bourbon.session.types import TranscriptMessage, MessageRole, ToolResultBlock
        
        content = [
            ToolResultBlock(
                tool_use_id=r.get("tool_use_id", ""),
                content=str(r.get("content", "")),
                is_error=r.get("is_error", False),
            )
            for r in results
        ]
        return TranscriptMessage(
            role=MessageRole.USER,
            content=content,
            source_tool_uuid=source_assistant_uuid,  # 指向 source assistant
        )
    
    # 废弃 messages 属性的 setter
    @property
    def messages(self) -> list[dict]:
        """
        获取当前消息列表（只读副本）
        
        DEPRECATED: 返回的是副本，修改不会生效
        新代码应该使用 session.add_message()
        """
        if self.session:
            return self.session.get_messages_for_llm()
        return []
    
    @messages.setter
    def messages(self, value):
        """废弃：直接设置消息列表"""
        import warnings
        warnings.warn(
            "Setting messages directly is deprecated and will be ignored. "
            "Use session.add_message() or session.chain.append() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    
    def clear_history(self) -> None:
        """清空对话历史"""
        if self.session:
            self.session.chain.clear()
            self.session.metadata.message_count = 0
            self.session.save()  # 保存 metadata（transcript 不受影响）
```

- [x] **Step 2: 重写 REPL 中的消息追加**

> **C2 说明：** REPL 实际使用 `step_stream()` → `_run_conversation_loop_stream()`，
> 而不是 `step()` / `_run_conversation_loop()`。如果只迁移同步路径，
> 用户所有真实会话都会绕过新系统，持久化、UUID 追踪等功能全部失效。

**需要迁移的调用点（来自 `src/bourbon/agent.py`）：**

```python
# agent.py line 469 - 流式路径添加 assistant response
self.messages.append({"role": "assistant", "content": content})
# 替换为：
assistant_msg = TranscriptMessage(
    role=MessageRole.ASSISTANT,
    content=self._parse_content_blocks(content),  # 转换 dict list -> dataclass list
)
self.session.add_message(assistant_msg)

# agent.py line 498 - 流式路径添加 tool results
self.messages.append({"role": "user", "content": tool_results})
# Finding 2 fix: 所有 results 必须合并为单条消息（与同步路径保持一致）
# 替换为：
tool_turn_msg = self._convert_tool_results_to_transcript_message(
    tool_results, assistant_msg.uuid
)
self.session.add_message(tool_turn_msg)

# agent.py line 515 - 流式路径错误回退
self.messages.append({"role": "assistant", "content": error_msg})
# 替换为：
self.session.add_message(TranscriptMessage(
    role=MessageRole.ASSISTANT,
    content=[TextBlock(text=error_msg)],
))
```

**`step_stream()` 入口迁移（`src/bourbon/agent.py` line ~320-356）：**

```python
def step_stream(
    self,
    user_input: str,
    on_text_chunk: Callable[[str], None],
) -> str:
    """处理用户输入（流式）- 迁移到 Session"""
    if self.pending_confirmation:
        # Finding 3 fix: 使用已有的 _handle_confirmation_response()，不是不存在的 stream 版本。
        # 实际代码 (agent.py:329) 也是调用 _handle_confirmation_response(user_input)。
        # 确认响应场景下不走流式路径是可接受的：确认消息很短，无需 streaming。
        return self._handle_confirmation_response(user_input)
    
    # 替换原来的 self.messages.append({"role": "user", ...})
    user_msg = TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text=user_input)],
    )
    self.session.add_message(user_msg)
    self.session.save()
    
    # 替换原来的 self.compressor.microcompact / should_compact 调用
    self.session.maybe_compact()
    
    return self._run_conversation_loop_stream(on_text_chunk)
```

- [x] **Step 3: 迁移其余遗漏的旧入口（Finding 4 - 必须全部覆盖）**

以下入口若不迁移，会绕过 Session 系统直接操作旧 `list[dict]`：

```python
# agent.py line 560 - 确认恢复分支（_handle_confirmation_response）
self.messages.append({"role": "user", "content": context})
# 替换为：
self.session.add_message(TranscriptMessage(
    role=MessageRole.USER,
    content=[TextBlock(text=context)],
))

# agent.py line 912 - _auto_compact（被 step_stream 和 /compact 命令调用）
self.messages = self.compressor.compact(self.messages)
# 替换为：
# _auto_compact 整个方法废弃，逻辑移到 session.maybe_compact()
# /compact 命令改为调用 self.session.maybe_compact(trigger=CompactTrigger.MANUAL)

# repl.py line 462 - /compact 命令
self.agent._manual_compact()
# 替换为：
from bourbon.session.types import CompactTrigger
result = self.agent.session.maybe_compact(trigger=CompactTrigger.MANUAL)
if result and result.success:
    self.console.print(f"[dim]Context compressed: {result.archived_count} messages archived.[/dim]")
else:
    self.console.print("[dim]Context compressed.[/dim]")

# agent.py line 924 - clear_history
self.messages = []
# 替换为：
self.session.chain.clear()
self.session.metadata.message_count = 0
self.session.save()
```

搜索所有 `self.agent.messages.append` 和 `self.messages.append` 的调用点，确认无遗漏。

---

## Task 7-10: CLI, 废弃旧代码, 文档, 测试

（参考 v1 plan，应用上述修正）

---

## 开放问题回答

### Q1: 不可变 transcript vs 可变 snapshot?

**决策：两层模型**

```
┌────────────────────────────────────────┐
│  Layer 1: Transcript (Append-Only)     │
│  - 完整历史，永不修改                   │
│  - JSONL 只追加                         │
│  - 用于审计、回放                       │
├────────────────────────────────────────┤
│  Layer 2: Session State (In-Memory)    │
│  - Active chain，可变                   │
│  - Compact 删除旧消息                   │
│  - Clear 重建空链                       │
│  - 不直接持久化（通过 transcript 恢复） │
└────────────────────────────────────────┘
```

### Q2: Sidechain 是否本期交付?

**决策：从目标中显式降级**

- ❌ 移除 "Sidechain 隔离" 目标
- ✅ 保留 `is_sidechain` 字段（为未来预留）
- 📅 Sidechain 在子代理机制实现后再考虑

---

## 总结

### 关键修正

1. ✅ `parent_uuid` 是唯一用于 active chain 构建的边
2. ✅ `logical_parent_uuid` 仅用于调试
3. ✅ Transcript append-only，Session State 可变
4. ✅ Compact/Clear 只影响内存链，transcript 保留完整历史
5. ✅ Tool result parent 指向 source assistant
6. ✅ 重写所有 `self.messages.append` 调用点
7. ✅ Sidechain 从目标中移除

### 下一步

需要开始执行吗？
- **Subagent-Driven** (推荐): 派遣独立子代理逐个任务执行
- **Inline**: 当前会话执行
