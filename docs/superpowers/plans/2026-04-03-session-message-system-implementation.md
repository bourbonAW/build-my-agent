# Bourbon Session & Message System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 Bourbon 的 session 和消息管理系统，实现基于 Claude Code 设计的新架构

**Architecture:** 分层设计：SessionManager 管理生命周期，MessageChain 处理链式消息，TranscriptStore 负责 JSONL 持久化，ContextManager 处理 Token 和压缩策略

**Tech Stack:** Python 3.11+, dataclasses, UUID, JSONL, optional tiktoken

**References:** 
- Spec: `docs/superpowers/specs/2026-04-03-session-message-system-design.md`
- Research: `wiki/architecture/session-message-system.md`

---

## 文件结构

```
src/bourbon/session/
├── __init__.py          # 导出主要类
├── types.py             # 核心数据类型
├── chain.py             # MessageChain 链式消息
├── storage.py           # TranscriptStore JSONL 持久化
├── context.py           # TokenTracker + CompactStrategy
└── manager.py           # Session + SessionManager
```

---

## Task 1: 核心类型定义 (types.py)

**Files:**
- Create: `src/bourbon/session/types.py`
- Test: `tests/session/test_types.py`

- [ ] **Step 1: 编写类型定义文件**

```python
"""核心类型定义 - 参考 Claude Code 设计"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Literal
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
    """Token 使用统计"""
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
class ContentBlock:
    """内容块基类"""
    type: str


@dataclass(frozen=True)
class TextBlock(ContentBlock):
    """文本块"""
    text: str
    type: str = "text"


@dataclass(frozen=True)
class ToolUseBlock(ContentBlock):
    """工具调用块"""
    id: str
    name: str
    input: dict = field(default_factory=dict)
    type: str = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock(ContentBlock):
    """工具结果块"""
    tool_use_id: str
    content: str
    is_error: bool = False
    type: str = "tool_result"


# Union type for content blocks
MessageContent = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass
class CompactMetadata:
    """压缩元数据"""
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
    链式消息结构 - 核心设计
    
    参考 Claude Code 的 TranscriptMessage 设计:
    - uuid: 唯一标识
    - parent_uuid: 物理父节点（用于构建链）
    - logical_parent_uuid: 逻辑父节点（compact 后保留连续性）
    """
    # 身份标识
    uuid: UUID = field(default_factory=uuid4)
    session_id: UUID = field(default_factory=uuid4)
    
    # 链式关系（核心！）
    parent_uuid: UUID | None = None           # 物理父节点
    logical_parent_uuid: UUID | None = None   # 逻辑父节点
    
    # 消息内容
    role: MessageRole = MessageRole.USER
    content: list[MessageContent] = field(default_factory=list)
    
    # 元数据
    timestamp: datetime = field(default_factory=datetime.now)
    usage: TokenUsage | None = None
    
    # Sidechain 支持
    agent_id: str | None = None      # 子代理 ID
    is_sidechain: bool = False       # 是否为 sidechain 消息
    
    # Tool 关联
    source_tool_uuid: UUID | None = None  # tool_result 关联的 tool_use message
    
    # Compact 相关
    is_compact_boundary: bool = False
    compact_metadata: CompactMetadata | None = None
    
    def to_llm_format(self) -> dict:
        """转换为 LLM API 格式"""
        content_list = []
        for block in self.content:
            block_dict = {
                "type": block.type,
            }
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
    """会话元数据"""
    uuid: UUID
    parent_uuid: UUID | None
    project_dir: str
    created_at: datetime
    last_activity: datetime
    message_count: int = 0
    total_tokens_used: int = 0
    is_active: bool = True
    description: str = ""  # 用户可设置的会话描述


@dataclass
class SessionSummary:
    """会话摘要（用于列表展示）"""
    uuid: UUID
    description: str
    last_activity: datetime
    message_count: int
    is_resumable: bool
```

- [ ] **Step 2: 编写基础类型测试**

```python
# tests/session/test_types.py
import pytest
from datetime import datetime
from uuid import uuid4

from bourbon.session.types import (
    MessageRole,
    TranscriptMessage,
    TextBlock,
    TokenUsage,
)


def test_transcript_message_creation():
    """测试消息创建"""
    msg = TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="Hello")],
    )
    assert msg.role == MessageRole.USER
    assert len(msg.content) == 1
    assert msg.content[0].text == "Hello"


def test_transcript_message_to_llm_format():
    """测试转换为 LLM 格式"""
    msg = TranscriptMessage(
        role=MessageRole.USER,
        content=[TextBlock(text="Hello")],
    )
    llm_format = msg.to_llm_format()
    assert llm_format["role"] == "user"
    assert llm_format["content"][0]["type"] == "text"
    assert llm_format["content"][0]["text"] == "Hello"


def test_token_usage_addition():
    """测试 TokenUsage 加法"""
    usage1 = TokenUsage(input_tokens=100, output_tokens=50)
    usage2 = TokenUsage(input_tokens=50, output_tokens=25)
    total = usage1 + usage2
    assert total.input_tokens == 150
    assert total.output_tokens == 75
    assert total.total_tokens == 0  # default
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/session/test_types.py -v`
Expected: 3 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/session/types.py tests/session/test_types.py
git commit -m "feat(session): add core types (MessageRole, TranscriptMessage, TokenUsage)"
```

---

## Task 2: 消息链实现 (chain.py)

**Files:**
- Create: `src/bourbon/session/chain.py`
- Create: `tests/session/test_chain.py`

- [ ] **Step 1: 编写 MessageChain 实现**

```python
"""消息链管理 - 核心算法实现"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterator
from uuid import UUID

from .types import TranscriptMessage, CompactMetadata


@dataclass
class CompactResult:
    """压缩结果"""
    success: bool
    before_count: int
    after_count: int
    before_tokens: int
    after_tokens: int
    archived_count: int
    preserved_count: int
    summary: str
    boundary_message: TranscriptMessage | None = None


class MessageChain:
    """
    消息链管理器
    
    核心功能:
    1. UUID -> Message 映射
    2. 从叶子节点构建对话链
    3. 支持 Compact（压缩）操作
    4. 支持 Snip（删除）操作
    """
    
    def __init__(self):
        # UUID -> Message 的映射（保持插入顺序）
        self._messages: OrderedDict[UUID, TranscriptMessage] = OrderedDict()
        # 当前叶子节点
        self._leaf_uuid: UUID | None = None
        # 根节点（第一个消息）
        self._root_uuid: UUID | None = None
    
    @property
    def leaf_uuid(self) -> UUID | None:
        return self._leaf_uuid
    
    @property
    def root_uuid(self) -> UUID | None:
        return self._root_uuid
    
    @property
    def message_count(self) -> int:
        return len(self._messages)
    
    def append(self, message: TranscriptMessage) -> None:
        """
        添加消息到链
        
        自动设置 parent_uuid 为当前叶子节点
        """
        if self._leaf_uuid:
            message.parent_uuid = self._leaf_uuid
        else:
            # 这是第一条消息
            self._root_uuid = message.uuid
            
        self._messages[message.uuid] = message
        self._leaf_uuid = message.uuid
    
    def get(self, uuid: UUID) -> TranscriptMessage | None:
        """获取指定 UUID 的消息"""
        return self._messages.get(uuid)
    
    def __contains__(self, uuid: UUID) -> bool:
        return uuid in self._messages
    
    def __iter__(self) -> Iterator[TranscriptMessage]:
        """按插入顺序迭代所有消息"""
        return iter(self._messages.values())
    
    def build_conversation_chain(self) -> list[TranscriptMessage]:
        """
        从叶子节点回溯到根节点，构建完整的对话链
        
        算法:
        1. 从 leaf_uuid 开始
        2. 收集当前消息
        3. 使用 logical_parent_uuid 或 parent_uuid 向上回溯
        4. 检测循环
        5. 反转列表得到从根到叶的顺序
        
        Returns:
            按时间顺序排列的消息列表
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
            
            # 优先使用 logical_parent_uuid（compact 后保留逻辑连续性）
            next_uuid = message.logical_parent_uuid or message.parent_uuid
            current_uuid = next_uuid
        
        # 反转得到从根到叶的顺序
        chain.reverse()
        return chain
    
    def get_llm_messages(self) -> list[dict]:
        """
        获取适合传递给 LLM 的消息列表
        
        过滤掉:
        - compact_boundary 消息（内部使用，不传给 LLM）
        - sidechain 消息（除非明确包含）
        """
        chain = self.build_conversation_chain()
        llm_messages = []
        
        for msg in chain:
            # 跳过 compact_boundary 消息（其内容是元数据，不是对话）
            if msg.is_compact_boundary:
                continue
            # 跳过 sidechain 消息
            if msg.is_sidechain:
                continue
            llm_messages.append(msg.to_llm_format())
        
        return llm_messages
    
    def compact(
        self,
        preserve_count: int = 3,
        summary: str = "",
    ) -> CompactResult:
        """
        压缩消息链
        
        算法:
        1. 保留最近 preserve_count 条消息
        2. 将之前的消息归档到 transcript
        3. 生成 summary
        4. 创建 compact_boundary 消息
        5. 更新 logical_parent_uuid 保留逻辑关系
        
        示例:
            原始: [M1, M2, M3, M4, M5]
            压缩: [Boundary, M4, M5]
            
            M4.parent_uuid = Boundary.uuid（物理连接）
            M4.logical_parent_uuid = M3.uuid（逻辑连接保留）
            Boundary.parent_uuid = null（compact 边界）
        """
        chain = self.build_conversation_chain()
        if len(chain) <= preserve_count:
            return CompactResult(
                success=False,
                before_count=len(chain),
                after_count=len(chain),
                before_tokens=0,
                after_tokens=0,
                archived_count=0,
                preserved_count=len(chain),
                summary="",
                boundary_message=None,
            )
        
        # 分割：需要归档的 和 需要保留的
        to_archive = chain[:-preserve_count]
        to_preserve = chain[-preserve_count:]
        
        if not to_archive:
            return CompactResult(
                success=False,
                before_count=len(chain),
                after_count=len(chain),
                before_tokens=0,
                after_tokens=0,
                archived_count=0,
                preserved_count=len(chain),
                summary="",
                boundary_message=None,
            )
        
        # 获取归档范围
        first_archived = to_archive[0]
        last_archived = to_archive[-1]
        
        # 获取保留范围
        first_preserved = to_preserve[0]
        
        # 创建 compact_boundary 消息
        from .types import CompactTrigger, CompactMetadata
        
        boundary_msg = TranscriptMessage(
            role=MessageRole.SYSTEM,  # Assuming MessageRole is imported
            content=[],  # Boundary 消息没有实际内容
            is_compact_boundary=True,
            compact_metadata=CompactMetadata(
                trigger=CompactTrigger.MANUAL,
                pre_compact_token_count=len(to_archive),  # Simplified
                post_compact_token_count=len(to_preserve),
                first_archived_uuid=first_archived.uuid,
                last_archived_uuid=last_archived.uuid,
                summary=summary or f"Archived {len(to_archive)} messages",
            ),
        )
        
        # 更新链：删除归档消息，添加 boundary，保留的消息
        for msg in to_archive:
            del self._messages[msg.uuid]
        
        # boundary 消息的 parent 为 null（物理断开）
        boundary_msg.parent_uuid = None
        boundary_msg.logical_parent_uuid = last_archived.uuid
        
        self._messages[boundary_msg.uuid] = boundary_msg
        
        # 更新第一个保留消息的 parent 为 boundary
        # 但 logical_parent 保留原来的值
        first_preserved.parent_uuid = boundary_msg.uuid
        if not first_preserved.logical_parent_uuid:
            first_preserved.logical_parent_uuid = last_archived.uuid
        
        # 如果叶子节点被归档，更新为最后一个保留的消息
        if self._leaf_uuid in [m.uuid for m in to_archive]:
            self._leaf_uuid = to_preserve[-1].uuid if to_preserve else boundary_msg.uuid
        
        return CompactResult(
            success=True,
            before_count=len(chain),
            after_count=1 + len(to_preserve),  # boundary + preserved
            before_tokens=0,  # Would need actual token count
            after_tokens=0,
            archived_count=len(to_archive),
            preserved_count=len(to_preserve),
            summary=summary or f"Archived {len(to_archive)} messages",
            boundary_message=boundary_msg,
        )
    
    def find_orphaned_messages(self) -> list[TranscriptMessage]:
        """
        查找孤立消息（无法从 leaf 到达的消息）
        
        可能原因:
        - Snip 操作遗留
        - 手动删除
        - Bug
        """
        reachable = set()
        current = self._leaf_uuid
        
        while current:
            reachable.add(current)
            msg = self._messages.get(current)
            if not msg:
                break
            current = msg.parent_uuid
        
        orphaned = [
            msg for uuid, msg in self._messages.items()
            if uuid not in reachable
        ]
        return orphaned
```

- [ ] **Step 2: 编写链测试**

```python
# tests/session/test_chain.py
import pytest
from uuid import uuid4

from bourbon.session.chain import MessageChain, CompactResult
from bourbon.session.types import (
    TranscriptMessage,
    MessageRole,
    TextBlock,
)


def test_empty_chain():
    """测试空链"""
    chain = MessageChain()
    assert chain.message_count == 0
    assert chain.leaf_uuid is None
    assert chain.build_conversation_chain() == []


def test_append_messages():
    """测试添加消息"""
    chain = MessageChain()
    
    msg1 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="Hello")])
    chain.append(msg1)
    
    assert chain.message_count == 1
    assert chain.leaf_uuid == msg1.uuid
    assert msg1.parent_uuid is None  # 第一条消息无 parent
    
    msg2 = TranscriptMessage(role=MessageRole.ASSISTANT, content=[TextBlock(text="Hi!")])
    chain.append(msg2)
    
    assert chain.message_count == 2
    assert chain.leaf_uuid == msg2.uuid
    assert msg2.parent_uuid == msg1.uuid


def test_build_conversation_chain():
    """测试构建对话链"""
    chain = MessageChain()
    
    msg1 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
    msg2 = TranscriptMessage(role=MessageRole.ASSISTANT, content=[TextBlock(text="2")])
    msg3 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="3")])
    
    chain.append(msg1)
    chain.append(msg2)
    chain.append(msg3)
    
    conversation = chain.build_conversation_chain()
    assert len(conversation) == 3
    assert conversation[0] == msg1
    assert conversation[1] == msg2
    assert conversation[2] == msg3


def test_compact_preserves_logical_relationship():
    """测试压缩保留逻辑关系"""
    chain = MessageChain()
    
    # 添加 5 条消息
    messages = []
    for i in range(5):
        msg = TranscriptMessage(
            role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
            content=[TextBlock(text=str(i))],
        )
        messages.append(msg)
        chain.append(msg)
    
    # 压缩，保留最近 2 条
    result = chain.compact(preserve_count=2, summary="Test compact")
    
    assert result.success is True
    assert result.archived_count == 3
    assert result.preserved_count == 2
    
    # 验证链结构
    conversation = chain.build_conversation_chain()
    # 应该是: [boundary, msg4, msg5]
    assert len(conversation) == 3
    assert conversation[0].is_compact_boundary is True
    assert conversation[1] == messages[3]  # msg4
    assert conversation[2] == messages[4]  # msg5
    
    # 验证 logical_parent 保留
    assert messages[3].logical_parent_uuid == messages[2].uuid
    
    # 验证 LLM 消息过滤掉 boundary
    llm_msgs = chain.get_llm_messages()
    assert len(llm_msgs) == 2  # 只有 msg4 和 msg5


def test_compact_noop_when_insufficient_messages():
    """测试消息不足时不压缩"""
    chain = MessageChain()
    
    msg1 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
    chain.append(msg1)
    
    result = chain.compact(preserve_count=3)
    
    assert result.success is False
    assert result.before_count == 1
    assert chain.message_count == 1
```

- [ ] **Step 3: 修复导入问题并运行测试**

Run: `pytest tests/session/test_chain.py -v`
Expected: 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/session/chain.py tests/session/test_chain.py
git commit -m "feat(session): implement MessageChain with UUID linking and compact"
```

---

## Task 3: JSONL 持久化存储 (storage.py)

**Files:**
- Create: `src/bourbon/session/storage.py`
- Create: `tests/session/test_storage.py`

- [ ] **Step 1: 编写存储实现**

```python
"""JSONL 持久化存储"""

import json
from pathlib import Path
from uuid import UUID

from .types import (
    TranscriptMessage,
    SessionMetadata,
    SessionSummary,
    MessageRole,
    ContentBlock,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    TokenUsage,
    CompactTrigger,
    CompactMetadata,
)


class TranscriptStore:
    """
    JSONL 增量持久化存储
    
    设计:
    - 每条消息一行 JSON (JSONL 格式)
    - 追加写入，无需重写整个文件
    - 支持流式读取
    - 去重机制防止重复写入
    """
    
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_project_dir(self, project_name: str) -> Path:
        """获取项目目录"""
        project_dir = self.base_dir / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    
    def _get_session_path(self, project_name: str, session_id: UUID) -> Path:
        """获取会话文件路径"""
        return self._get_project_dir(project_name) / f"{session_id}.jsonl"
    
    def _get_meta_path(self, project_name: str, session_id: UUID) -> Path:
        """获取元数据文件路径"""
        return self._get_project_dir(project_name) / f"{session_id}.meta.json"
    
    def _get_sidechain_dir(self, project_name: str) -> Path:
        """获取 sidechain 目录"""
        sidechain_dir = self._get_project_dir(project_name) / "sidechains"
        sidechain_dir.mkdir(parents=True, exist_ok=True)
        return sidechain_dir
    
    def _get_existing_uuids(self, path: Path) -> set[UUID]:
        """获取文件中已存在的 UUID"""
        if not path.exists():
            return set()
        
        uuids = set()
        try:
            with open(path) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        uuids.add(UUID(data["uuid"]))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
        
        return uuids
    
    def append_messages(
        self,
        project_name: str,
        session_id: UUID,
        messages: list[TranscriptMessage],
    ) -> int:
        """
        追加消息到 transcript
        
        Returns:
            实际写入的消息数量
        """
        path = self._get_session_path(project_name, session_id)
        
        # 获取已存在的 UUID
        existing_uuids = self._get_existing_uuids(path)
        
        # 过滤已存在的消息
        new_messages = [
            msg for msg in messages
            if msg.uuid not in existing_uuids
        ]
        
        if not new_messages:
            return 0
        
        # 追加写入
        with open(path, "a") as f:
            for msg in new_messages:
                f.write(json.dumps(self._serialize_message(msg), default=str) + "\n")
        
        return len(new_messages)
    
    def load_messages(
        self,
        project_name: str,
        session_id: UUID,
    ) -> list[TranscriptMessage]:
        """加载会话的所有消息"""
        path = self._get_session_path(project_name, session_id)
        
        if not path.exists():
            return []
        
        messages = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        messages.append(self._deserialize_message(data))
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        # 跳过损坏的行
                        continue
        
        return messages
    
    def save_metadata(
        self,
        project_name: str,
        metadata: SessionMetadata,
    ) -> None:
        """保存会话元数据"""
        path = self._get_meta_path(project_name, metadata.uuid)
        
        data = {
            "uuid": str(metadata.uuid),
            "parent_uuid": str(metadata.parent_uuid) if metadata.parent_uuid else None,
            "project_dir": metadata.project_dir,
            "created_at": metadata.created_at.isoformat(),
            "last_activity": metadata.last_activity.isoformat(),
            "message_count": metadata.message_count,
            "total_tokens_used": metadata.total_tokens_used,
            "is_active": metadata.is_active,
            "description": metadata.description,
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def load_metadata(
        self,
        project_name: str,
        session_id: UUID,
    ) -> SessionMetadata | None:
        """加载会话元数据"""
        path = self._get_meta_path(project_name, session_id)
        
        if not path.exists():
            return None
        
        with open(path) as f:
            data = json.load(f)
        
        return SessionMetadata(
            uuid=UUID(data["uuid"]),
            parent_uuid=UUID(data["parent_uuid"]) if data.get("parent_uuid") else None,
            project_dir=data["project_dir"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_activity=datetime.fromisoformat(data["last_activity"]),
            message_count=data.get("message_count", 0),
            total_tokens_used=data.get("total_tokens_used", 0),
            is_active=data.get("is_active", True),
            description=data.get("description", ""),
        )
    
    def list_sessions(self, project_name: str) -> list[SessionSummary]:
        """
        列出项目的所有可恢复会话
        
        过滤:
        - 只返回非 sidechain 的主会话
        - 按 last_activity 排序
        """
        project_dir = self._get_project_dir(project_name)
        
        if not project_dir.exists():
            return []
        
        sessions = []
        for meta_file in project_dir.glob("*.meta.json"):
            try:
                with open(meta_file) as f:
                    data = json.load(f)
                
                sessions.append(SessionSummary(
                    uuid=UUID(data["uuid"]),
                    description=data.get("description", ""),
                    last_activity=datetime.fromisoformat(data["last_activity"]),
                    message_count=data.get("message_count", 0),
                    is_resumable=data.get("is_active", True),
                ))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        # 按最后活动时间排序（最新的在前）
        sessions.sort(key=lambda s: s.last_activity, reverse=True)
        return sessions
    
    def _serialize_message(self, msg: TranscriptMessage) -> dict:
        """序列化消息为 JSON"""
        return {
            "uuid": str(msg.uuid),
            "session_id": str(msg.session_id),
            "parent_uuid": str(msg.parent_uuid) if msg.parent_uuid else None,
            "logical_parent_uuid": str(msg.logical_parent_uuid) if msg.logical_parent_uuid else None,
            "role": msg.role.value,
            "content": self._serialize_content(msg.content),
            "timestamp": msg.timestamp.isoformat(),
            "usage": self._serialize_usage(msg.usage) if msg.usage else None,
            "agent_id": msg.agent_id,
            "is_sidechain": msg.is_sidechain,
            "source_tool_uuid": str(msg.source_tool_uuid) if msg.source_tool_uuid else None,
            "is_compact_boundary": msg.is_compact_boundary,
            "compact_metadata": self._serialize_compact_metadata(msg.compact_metadata) if msg.compact_metadata else None,
        }
    
    def _serialize_content(self, content: list[ContentBlock]) -> list[dict]:
        """序列化内容块"""
        result = []
        for block in content:
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
            result.append(block_dict)
        return result
    
    def _serialize_usage(self, usage: TokenUsage) -> dict:
        """序列化 TokenUsage"""
        return {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
    
    def _serialize_compact_metadata(self, metadata: CompactMetadata) -> dict:
        """序列化 CompactMetadata"""
        return {
            "trigger": metadata.trigger.value,
            "pre_compact_token_count": metadata.pre_compact_token_count,
            "post_compact_token_count": metadata.post_compact_token_count,
            "first_archived_uuid": str(metadata.first_archived_uuid),
            "last_archived_uuid": str(metadata.last_archived_uuid),
            "summary": metadata.summary,
            "archived_at": metadata.archived_at.isoformat(),
        }
    
    def _deserialize_message(self, data: dict) -> TranscriptMessage:
        """从 JSON 反序列化消息"""
        from datetime import datetime
        
        # 反序列化 content
        content = []
        for block_data in data.get("content", []):
            block_type = block_data.get("type")
            if block_type == "text":
                content.append(TextBlock(text=block_data["text"]))
            elif block_type == "tool_use":
                content.append(ToolUseBlock(
                    id=block_data["id"],
                    name=block_data["name"],
                    input=block_data.get("input", {}),
                ))
            elif block_type == "tool_result":
                content.append(ToolResultBlock(
                    tool_use_id=block_data["tool_use_id"],
                    content=block_data["content"],
                    is_error=block_data.get("is_error", False),
                ))
        
        # 反序列化 usage
        usage = None
        if data.get("usage"):
            usage = TokenUsage(**data["usage"])
        
        # 反序列化 compact_metadata
        compact_metadata = None
        if data.get("compact_metadata"):
            cm_data = data["compact_metadata"]
            compact_metadata = CompactMetadata(
                trigger=CompactTrigger(cm_data["trigger"]),
                pre_compact_token_count=cm_data["pre_compact_token_count"],
                post_compact_token_count=cm_data["post_compact_token_count"],
                first_archived_uuid=UUID(cm_data["first_archived_uuid"]),
                last_archived_uuid=UUID(cm_data["last_archived_uuid"]),
                summary=cm_data["summary"],
                archived_at=datetime.fromisoformat(cm_data["archived_at"]),
            )
        
        return TranscriptMessage(
            uuid=UUID(data["uuid"]),
            session_id=UUID(data["session_id"]),
            parent_uuid=UUID(data["parent_uuid"]) if data.get("parent_uuid") else None,
            logical_parent_uuid=UUID(data["logical_parent_uuid"]) if data.get("logical_parent_uuid") else None,
            role=MessageRole(data["role"]),
            content=content,
            timestamp=datetime.fromisoformat(data["timestamp"]),
            usage=usage,
            agent_id=data.get("agent_id"),
            is_sidechain=data.get("is_sidechain", False),
            source_tool_uuid=UUID(data["source_tool_uuid"]) if data.get("source_tool_uuid") else None,
            is_compact_boundary=data.get("is_compact_boundary", False),
            compact_metadata=compact_metadata,
        )
```

- [ ] **Step 2: 编写存储测试**

```python
# tests/session/test_storage.py
import tempfile
import pytest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from bourbon.session.storage import TranscriptStore
from bourbon.session.types import (
    TranscriptMessage,
    SessionMetadata,
    MessageRole,
    TextBlock,
)


def test_store_init():
    """测试存储初始化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TranscriptStore(Path(tmpdir))
        assert store.base_dir.exists()


def test_append_and_load_messages():
    """测试追加和加载消息"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TranscriptStore(Path(tmpdir))
        session_id = uuid4()
        project_name = "test-project"
        
        # 创建消息
        messages = [
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text=f"msg{i}")])
            for i in range(3)
        ]
        
        # 追加
        count = store.append_messages(project_name, session_id, messages)
        assert count == 3
        
        # 加载
        loaded = store.load_messages(project_name, session_id)
        assert len(loaded) == 3
        assert loaded[0].content[0].text == "msg0"
        assert loaded[1].content[0].text == "msg1"


def test_deduplication():
    """测试去重"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TranscriptStore(Path(tmpdir))
        session_id = uuid4()
        
        msg = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="test")])
        
        # 第一次追加
        count1 = store.append_messages("test", session_id, [msg])
        assert count1 == 1
        
        # 第二次追加（应该被去重）
        count2 = store.append_messages("test", session_id, [msg])
        assert count2 == 0
        
        # 验证文件只有一条消息
        loaded = store.load_messages("test", session_id)
        assert len(loaded) == 1


def test_save_and_load_metadata():
    """测试元数据保存和加载"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TranscriptStore(Path(tmpdir))
        
        metadata = SessionMetadata(
            uuid=uuid4(),
            parent_uuid=None,
            project_dir="/test",
            created_at=datetime.now(),
            last_activity=datetime.now(),
            description="Test session",
        )
        
        store.save_metadata("test", metadata)
        
        loaded = store.load_metadata("test", metadata.uuid)
        assert loaded is not None
        assert loaded.uuid == metadata.uuid
        assert loaded.description == "Test session"


def test_list_sessions():
    """测试列出会话"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TranscriptStore(Path(tmpdir))
        
        # 创建两个会话
        for i in range(2):
            metadata = SessionMetadata(
                uuid=uuid4(),
                parent_uuid=None,
                project_dir=f"/test{i}",
                created_at=datetime.now(),
                last_activity=datetime.now(),
                description=f"Session {i}",
            )
            store.save_metadata("test", metadata)
        
        sessions = store.list_sessions("test")
        assert len(sessions) == 2
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/session/test_storage.py -v`
Expected: 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/session/storage.py tests/session/test_storage.py
git commit -m "feat(session): add TranscriptStore with JSONL persistence and deduplication"
```

---

## Task 4: Token 管理与压缩策略 (context.py)

**Files:**
- Create: `src/bourbon/session/context.py`
- Create: `tests/session/test_context.py`

- [ ] **Step 1: 编写 Token 管理和压缩策略**

```python
"""上下文管理和 Token 策略"""

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from .chain import MessageChain
from .types import TranscriptMessage, TokenUsage, CompactTrigger, MessageRole, TextBlock


class TokenLevel(Enum):
    """Token 使用级别"""
    NORMAL = auto()      # 0-50%: 正常
    WARM = auto()        # 50-75%: 温和清理
    HOT = auto()         # 75-90%: 积极压缩
    CRITICAL = auto()    # 90-100%: 紧急处理


@dataclass
class TokenStatus:
    """Token 状态"""
    current_tokens: int
    threshold: int
    ratio: float  # 0.0 - 1.0
    level: TokenLevel
    message_count: int
    
    def __str__(self) -> str:
        return f"TokenStatus({self.current_tokens}/{self.threshold}, {self.ratio:.1%}, {self.level.name})"


class TokenTracker:
    """
    Token 跟踪器
    
    功能:
    1. 准确估算消息 Token 数
    2. 跟踪累积使用量
    3. 提供预警级别
    """
    
    def __init__(self, threshold: int = 100000):
        self.threshold = threshold
        self.usage_history: list[TokenUsage] = []
    
    def estimate_tokens(self, messages: list[dict]) -> int:
        """
        估算消息的 Token 数
        
        策略:
        - 优先使用 tiktoken 准确计算
        - 回退到字符/4 估算
        """
        try:
            import tiktoken
            encoder = tiktoken.get_encoding("cl100k_base")
            text = json.dumps(messages, default=str)
            return len(encoder.encode(text))
        except ImportError:
            # 粗略估算: ~4 字符/token
            text = json.dumps(messages, default=str)
            return len(text) // 4
    
    def check_status(self, chain: MessageChain) -> TokenStatus:
        """检查当前 Token 状态"""
        messages = chain.get_llm_messages()
        current = self.estimate_tokens(messages)
        ratio = current / self.threshold if self.threshold > 0 else 0
        
        if ratio < 0.5:
            level = TokenLevel.NORMAL
        elif ratio < 0.75:
            level = TokenLevel.WARM
        elif ratio < 0.9:
            level = TokenLevel.HOT
        else:
            level = TokenLevel.CRITICAL
        
        return TokenStatus(
            current_tokens=current,
            threshold=self.threshold,
            ratio=ratio,
            level=level,
            message_count=chain.message_count,
        )
    
    def record_usage(self, usage: TokenUsage) -> None:
        """记录 Token 使用"""
        self.usage_history.append(usage)


class CompactStrategy:
    """
    压缩策略
    
    多级压缩策略，根据 Token 级别采取不同措施
    """
    
    def __init__(
        self,
        chain: MessageChain,
        tracker: TokenTracker,
        summarizer: Callable[[list[TranscriptMessage]], str] | None = None,
    ):
        self.chain = chain
        self.tracker = tracker
        self.summarizer = summarizer
    
    def execute(self) -> dict:
        """
        根据当前 Token 状态执行相应策略
        
        Returns:
            执行结果描述
        """
        status = self.tracker.check_status(self.chain)
        
        if status.level == TokenLevel.NORMAL:
            return self._micro_compact()
        elif status.level == TokenLevel.WARM:
            return self._light_compact()
        elif status.level == TokenLevel.HOT:
            return self._aggressive_compact()
        else:  # CRITICAL
            return self._emergency_compact()
    
    def _micro_compact(self) -> dict:
        """
        微观压缩: 清理旧 tool 结果
        
        保留最近 3 个 tool_result，将旧的替换为 "[cleared]"
        """
        # 实现 microcompact 逻辑
        return {"action": "micro_compact", "cleared_count": 0}
    
    def _light_compact(self) -> dict:
        """
        轻度压缩: 归档旧消息，保留摘要
        
        - 归档 50% 的旧消息
        - 生成摘要
        - 创建 compact_boundary
        """
        # 计算要归档的消息数（保留最近 50% 或至少 5 条）
        total = self.chain.message_count
        preserve_count = max(5, total // 2)
        
        # 生成摘要
        summary = "Previous conversation archived."
        if self.summarizer:
            chain = self.chain.build_conversation_chain()
            to_summarize = chain[:-preserve_count] if len(chain) > preserve_count else []
            if to_summarize:
                summary = self.summarizer(to_summarize)
        
        # 执行压缩
        result = self.chain.compact(
            preserve_count=preserve_count,
            summary=summary,
        )
        
        return {
            "action": "light_compact",
            "archived": result.archived_count if result.success else 0,
            "preserved": result.preserved_count if result.success else 0,
            "success": result.success,
        }
    
    def _aggressive_compact(self) -> dict:
        """
        积极压缩: 大幅减少上下文
        
        - 只保留最近 5 轮对话
        - 深度摘要
        """
        result = self.chain.compact(
            preserve_count=5,
            summary="[Context compressed due to high token usage]",
        )
        
        return {
            "action": "aggressive_compact",
            "archived": result.archived_count if result.success else 0,
            "preserved": result.preserved_count if result.success else 0,
            "success": result.success,
        }
    
    def _emergency_compact(self) -> dict:
        """
        紧急压缩: 极限保活
        
        - 只保留 system + 最近用户消息
        - 或者抛出 ContextWindowExceededError
        """
        # 尝试只保留最近 2 条
        result = self.chain.compact(
            preserve_count=2,
            summary="[Emergency compact: context severely reduced]",
        )
        
        # 检查是否仍然超限
        status = self.tracker.check_status(self.chain)
        
        return {
            "action": "emergency_compact",
            "archived": result.archived_count if result.success else 0,
            "remaining_tokens": status.current_tokens,
            "still_critical": status.level == TokenLevel.CRITICAL,
            "success": result.success,
        }


class ContextManager:
    """
    上下文管理器
    
    整合 Token 跟踪和压缩策略
    """
    
    def __init__(self, chain: MessageChain, threshold: int = 100000):
        self.chain = chain
        self.tracker = TokenTracker(threshold)
        self.strategy = CompactStrategy(chain, self.tracker)
    
    def check_and_compact(self) -> dict | None:
        """
        检查 Token 状态并执行必要的压缩
        
        Returns:
            如果执行了压缩，返回结果；否则返回 None
        """
        status = self.tracker.check_status(self.chain)
        
        # 只在 WARM 及以上级别执行压缩
        if status.level.value >= TokenLevel.WARM.value:
            return self.strategy.execute()
        
        return None
    
    def get_status(self) -> TokenStatus:
        """获取当前 Token 状态"""
        return self.tracker.check_status(self.chain)
```

- [ ] **Step 2: 编写测试**

```python
# tests/session/test_context.py
import pytest
from uuid import uuid4

from bourbon.session.context import (
    TokenTracker,
    TokenLevel,
    CompactStrategy,
    ContextManager,
)
from bourbon.session.chain import MessageChain
from bourbon.session.types import (
    TranscriptMessage,
    MessageRole,
    TextBlock,
)


def test_token_tracker_estimate():
    """测试 Token 估算"""
    tracker = TokenTracker(threshold=1000)
    
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Hello world"}]},
    ]
    
    tokens = tracker.estimate_tokens(messages)
    assert tokens > 0  # 应该有正数估算


def test_token_status_levels():
    """测试 Token 级别判断"""
    chain = MessageChain()
    tracker = TokenTracker(threshold=1000)
    
    # 空链应该是 NORMAL
    status = tracker.check_status(chain)
    assert status.level == TokenLevel.NORMAL


def test_compact_strategy_levels():
    """测试压缩策略级别"""
    chain = MessageChain()
    tracker = TokenTracker(threshold=100)
    strategy = CompactStrategy(chain, tracker)
    
    # 空链应该是 NORMAL，不执行压缩
    result = strategy.execute()
    assert result["action"] == "micro_compact"


def test_context_manager():
    """测试上下文管理器"""
    chain = MessageChain()
    manager = ContextManager(chain, threshold=1000)
    
    # 空链不触发压缩
    result = manager.check_and_compact()
    assert result is None
    
    # 获取状态
    status = manager.get_status()
    assert status.level == TokenLevel.NORMAL
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/session/test_context.py -v`
Expected: 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/session/context.py tests/session/test_context.py
git commit -m "feat(session): add TokenTracker and multi-level CompactStrategy"
```

---

## Task 5: Session 管理器集成 (manager.py)

**Files:**
- Create: `src/bourbon/session/manager.py`
- Create: `src/bourbon/session/__init__.py`
- Create: `tests/session/test_manager.py`

- [ ] **Step 1: 编写 Session 管理器**

```python
"""会话管理器 - 对外接口"""

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from .chain import MessageChain
from .context import ContextManager, TokenStatus
from .storage import TranscriptStore
from .types import (
    SessionMetadata,
    SessionSummary,
    TranscriptMessage,
    TokenUsage,
)


class Session:
    """
    会话对象
    
    封装了一个完整会话的所有组件:
    - 元数据
    - 消息链
    - 存储
    - Token 管理
    """
    
    def __init__(
        self,
        metadata: SessionMetadata,
        chain: MessageChain,
        store: TranscriptStore,
        token_threshold: int = 100000,
    ):
        self.metadata = metadata
        self.chain = chain
        self.store = store
        self.context_manager = ContextManager(chain, token_threshold)
        self._dirty = False  # 是否有未保存的变更
    
    def add_message(self, message: TranscriptMessage) -> None:
        """添加消息"""
        message.session_id = self.metadata.uuid
        self.chain.append(message)
        self.metadata.message_count = self.chain.message_count
        self._dirty = True
    
    def get_messages_for_llm(self) -> list[dict]:
        """获取给 LLM 的消息列表"""
        return self.chain.get_llm_messages()
    
    def maybe_compact(self) -> dict | None:
        """
        检查并执行压缩
        
        Returns:
            如果执行了压缩，返回结果；否则返回 None
        """
        result = self.context_manager.check_and_compact()
        if result:
            self._dirty = True
        return result
    
    def get_token_status(self) -> TokenStatus:
        """获取 Token 状态"""
        return self.context_manager.get_status()
    
    def save(self, project_name: str | None = None) -> None:
        """持久化当前状态"""
        if not self._dirty:
            return
        
        if project_name is None:
            project_name = Path(self.metadata.project_dir).name
        
        # 保存所有消息
        messages = list(self.chain)
        self.store.append_messages(project_name, self.metadata.uuid, messages)
        
        # 更新元数据
        self.metadata.last_activity = datetime.now()
        self.store.save_metadata(project_name, self.metadata)
        
        self._dirty = False


class SessionManager:
    """
    会话管理器
    
    职责:
    1. 创建新会话
    2. 加载现有会话
    3. 列出可恢复会话
    4. 管理会话生命周期
    """
    
    def __init__(
        self,
        storage_dir: Path | None = None,
        project_dir: Path | None = None,
        token_threshold: int = 100000,
    ):
        if storage_dir is None:
            storage_dir = Path("~/.bourbon/sessions").expanduser()
        
        self.storage_dir = storage_dir
        self.project_dir = project_dir or Path.cwd()
        self.token_threshold = token_threshold
        self.store = TranscriptStore(storage_dir)
        self._current_session: Session | None = None
    
    def create_session(
        self,
        parent_session_id: UUID | None = None,
        description: str = "",
    ) -> Session:
        """创建新会话"""
        metadata = SessionMetadata(
            uuid=uuid4(),
            parent_uuid=parent_session_id,
            project_dir=str(self.project_dir),
            created_at=datetime.now(),
            last_activity=datetime.now(),
            description=description,
        )
        
        chain = MessageChain()
        session = Session(metadata, chain, self.store, self.token_threshold)
        
        self._current_session = session
        return session
    
    def load_session(self, session_id: UUID) -> Session:
        """加载现有会话"""
        project_name = self.project_dir.name
        
        # 加载元数据
        metadata = self.store.load_metadata(project_name, session_id)
        if metadata is None:
            raise ValueError(f"Session {session_id} not found")
        
        # 加载消息
        messages = self.store.load_messages(project_name, session_id)
        
        # 重建消息链
        chain = MessageChain()
        # 按 timestamp 排序后添加
        sorted_messages = sorted(messages, key=lambda m: m.timestamp)
        for msg in sorted_messages:
            chain._messages[msg.uuid] = msg
        
        # 设置叶子节点（最新的消息）
        if sorted_messages:
            chain._leaf_uuid = sorted_messages[-1].uuid
            chain._root_uuid = sorted_messages[0].uuid
        
        session = Session(metadata, chain, self.store, self.token_threshold)
        self._current_session = session
        return session
    
    def get_latest_session(self) -> Session | None:
        """获取最近的活动会话"""
        sessions = self.store.list_sessions(self.project_dir.name)
        
        for summary in sessions:
            if summary.is_resumable:
                return self.load_session(summary.uuid)
        
        return None
    
    def list_sessions(self) -> list[SessionSummary]:
        """列出所有可恢复的会话"""
        return self.store.list_sessions(self.project_dir.name)
    
    @property
    def current_session(self) -> Session | None:
        return self._current_session
    
    def resume_or_create(self, description: str = "") -> Session:
        """
        尝试恢复最近的会话，如果不存在则创建新会话
        
        Returns:
            恢复的或新创建的会话
        """
        latest = self.get_latest_session()
        if latest:
            return latest
        return self.create_session(description=description)
```

- [ ] **Step 2: 编写模块导出**

```python
# src/bourbon/session/__init__.py
"""Bourbon Session Management System

参考 Claude Code 设计，提供:
- UUID 链式消息结构
- JSONL 持久化
- 多级 Token 压缩策略
- Sidechain 支持
"""

from .chain import MessageChain, CompactResult
from .context import ContextManager, TokenTracker, TokenLevel, TokenStatus
from .manager import Session, SessionManager
from .storage import TranscriptStore
from .types import (
    CompactMetadata,
    CompactTrigger,
    ContentBlock,
    MessageContent,
    MessageRole,
    SessionMetadata,
    SessionSummary,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    TokenUsage,
    TranscriptMessage,
)

__all__ = [
    # Core types
    "TranscriptMessage",
    "MessageRole",
    "MessageContent",
    "ContentBlock",
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "TokenUsage",
    "SessionMetadata",
    "SessionSummary",
    "CompactMetadata",
    "CompactTrigger",
    # Chain
    "MessageChain",
    "CompactResult",
    # Storage
    "TranscriptStore",
    # Context
    "ContextManager",
    "TokenTracker",
    "TokenLevel",
    "TokenStatus",
    # Manager
    "Session",
    "SessionManager",
]
```

- [ ] **Step 3: 编写管理器测试**

```python
# tests/session/test_manager.py
import tempfile
import pytest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from bourbon.session.manager import Session, SessionManager
from bourbon.session.types import (
    TranscriptMessage,
    MessageRole,
    TextBlock,
)


def test_create_session():
    """测试创建会话"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_dir=Path(tmpdir),
            project_dir=Path(tmpdir),
        )
        
        session = manager.create_session(description="Test session")
        
        assert session.metadata.uuid is not None
        assert session.metadata.description == "Test session"
        assert session.chain.message_count == 0
        assert manager.current_session == session


def test_add_message_and_persist():
    """测试添加消息并持久化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_dir=Path(tmpdir),
            project_dir=Path(tmpdir) / "test-project",
        )
        manager.project_dir.mkdir(parents=True, exist_ok=True)
        
        session = manager.create_session()
        
        # 添加消息
        msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        )
        session.add_message(msg)
        
        assert session.chain.message_count == 1
        assert session.metadata.message_count == 1
        
        # 保存
        session.save()
        
        # 重新加载
        loaded = manager.load_session(session.metadata.uuid)
        assert loaded.chain.message_count == 1
        assert loaded.metadata.message_count == 1


def test_resume_or_create():
    """测试恢复或创建"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_dir=Path(tmpdir),
            project_dir=Path(tmpdir) / "test-project",
        )
        manager.project_dir.mkdir(parents=True, exist_ok=True)
        
        # 第一次应该创建新会话
        session1 = manager.resume_or_create(description="First")
        session1.save()
        
        # 第二次应该恢复同一个会话
        session2 = manager.resume_or_create()
        
        assert session1.metadata.uuid == session2.metadata.uuid


def test_list_sessions():
    """测试列出会话"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_dir=Path(tmpdir),
            project_dir=Path(tmpdir) / "test-project",
        )
        manager.project_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建两个会话
        for i in range(2):
            session = manager.create_session(description=f"Session {i}")
            session.save()
        
        sessions = manager.list_sessions()
        assert len(sessions) == 2


def test_get_messages_for_llm():
    """测试获取 LLM 消息"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_dir=Path(tmpdir),
            project_dir=Path(tmpdir),
        )
        
        session = manager.create_session()
        
        # 添加消息
        session.add_message(TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
        ))
        session.add_message(TranscriptMessage(
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Hi!")],
        ))
        
        llm_msgs = session.get_messages_for_llm()
        assert len(llm_msgs) == 2
        assert llm_msgs[0]["role"] == "user"
        assert llm_msgs[1]["role"] == "assistant"
```

- [ ] **Step 4: 运行所有 Session 测试**

Run: `pytest tests/session/ -v`
Expected: 所有测试 PASS

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/session/
git add tests/session/
git commit -m "feat(session): complete SessionManager with persistence and context management"
```

---

## Task 6: Agent 集成与向后兼容

**Files:**
- Modify: `src/bourbon/agent.py`
- Modify: `src/bourbon/repl.py`
- Create: `tests/test_agent_session_integration.py`

- [ ] **Step 1: 修改 Agent 集成 Session**

```python
# src/bourbon/agent.py - 关键修改

from pathlib import Path
from uuid import UUID

# 添加 Session 导入
from bourbon.session import Session, SessionManager

class Agent:
    """集成新 Session 系统的 Agent"""
    
    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        session_id: UUID | None = None,  # 新增：恢复会话
        resume_last: bool = False,       # 新增：恢复最近的会话
        ...
    ):
        self.config = config
        self.workdir = workdir or Path.cwd()
        
        # 初始化 Session 管理器
        storage_dir = Path("~/.bourbon/sessions").expanduser()
        self.session_manager = SessionManager(
            storage_dir=storage_dir,
            project_dir=self.workdir,
            token_threshold=getattr(config.ui, "token_threshold", 100000),
        )
        
        # 加载或创建会话
        if session_id:
            self.session = self.session_manager.load_session(session_id)
        elif resume_last:
            self.session = self.session_manager.resume_or_create()
        else:
            # 默认行为：创建新会话
            self.session = self.session_manager.create_session()
        
        # 其他组件
        self.todos = TodoManager()
        self.skills = SkillManager(self.workdir)
        self.compressor = ContextCompressor(...)  # 保留旧 compressor 做兼容
        
        # 保留向后兼容的 messages 属性
        self._legacy_messages: list[dict] | None = None
    
    @property
    def messages(self) -> list[dict]:
        """向后兼容：返回 messages 列表"""
        if self.session:
            return self.session.get_messages_for_llm()
        return self._legacy_messages or []
    
    @messages.setter
    def messages(self, value: list[dict]):
        """向后兼容：设置 messages"""
        if not self.session:
            self._legacy_messages = value
    
    def step(self, user_input: str) -> str:
        """处理用户输入"""
        # 检查确认状态...
        
        # 创建用户消息
        from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=user_input)],
        )
        self.session.add_message(user_msg)
        
        # 检查并执行压缩（使用新的 ContextManager）
        compact_result = self.session.maybe_compact()
        if compact_result:
            # 可以通知用户或记录日志
            pass
        
        # 运行对话循环
        return self._run_conversation_loop()
    
    def _run_conversation_loop(self) -> str:
        """运行对话循环"""
        # 获取 LLM 消息
        messages = self.session.get_messages_for_llm()
        
        # 调用 LLM
        response = self.llm.chat(
            messages=messages,
            tools=definitions(),
            system=self.system_prompt,
        )
        
        # 处理响应...
        
        # 添加助手消息到会话
        from bourbon.session.types import TranscriptMessage, MessageRole
        assistant_msg = self._convert_response_to_message(response)
        self.session.add_message(assistant_msg)
        
        # 持久化
        self.session.save()
        
        # 返回文本
        return self._extract_text_from_response(response)
    
    def clear_history(self) -> None:
        """清空对话历史"""
        if self.session:
            # 创建新的空链
            from bourbon.session.chain import MessageChain
            self.session.chain = MessageChain()
            self.session.metadata.message_count = 0
            self.session._dirty = True
            self.session.save()
        else:
            # 旧代码路径
            self._legacy_messages = []
    
    def get_session_info(self) -> dict:
        """获取会话信息"""
        if not self.session:
            return {}
        
        status = self.session.get_token_status()
        return {
            "session_id": str(self.session.metadata.uuid),
            "message_count": self.session.metadata.message_count,
            "created_at": self.session.metadata.created_at.isoformat(),
            "token_status": {
                "current": status.current_tokens,
                "threshold": status.threshold,
                "ratio": status.ratio,
                "level": status.level.name,
            },
        }
```

- [ ] **Step 2: 修改 REPL 添加会话命令**

```python
# src/bourbon/repl.py - 添加会话管理命令

class BourbonREPL:
    """添加会话管理命令的 REPL"""
    
    def __init__(self, agent: Agent, ...):
        self.agent = agent
        # ...
    
    def _handle_command(self, command: str) -> bool:
        """处理斜杠命令"""
        cmd = command.lower().strip()
        
        if cmd == "/session":
            self._show_session_info()
            return True
        elif cmd == "/sessions":
            self._list_sessions()
            return True
        elif cmd.startswith("/resume "):
            session_id = cmd.split(" ", 1)[1].strip()
            self._resume_session(session_id)
            return True
        elif cmd == "/compact":
            self._manual_compact()
            return True
        # ... 其他命令
        
        return False
    
    def _show_session_info(self) -> None:
        """显示当前会话信息"""
        info = self.agent.get_session_info()
        if not info:
            print("No active session")
            return
        
        print(f"Session ID: {info['session_id']}")
        print(f"Messages: {info['message_count']}")
        print(f"Created: {info['created_at']}")
        print(f"Token Usage: {info['token_status']['current']}/{info['token_status']['threshold']} ({info['token_status']['ratio']:.1%})")
        print(f"Level: {info['token_status']['level']}")
    
    def _list_sessions(self) -> None:
        """列出可恢复的会话"""
        sessions = self.agent.session_manager.list_sessions()
        if not sessions:
            print("No sessions found")
            return
        
        print(f"{'Session ID':<36} {'Last Activity':<20} {'Messages':<10} Description")
        print("-" * 100)
        for s in sessions:
            desc = s.description[:30] + "..." if len(s.description) > 30 else s.description
            print(f"{str(s.uuid):<36} {s.last_activity.strftime('%Y-%m-%d %H:%M'):<20} {s.message_count:<10} {desc}")
    
    def _manual_compact(self) -> None:
        """手动执行压缩"""
        result = self.agent.session.maybe_compact()
        if result:
            print(f"Compact executed: {result}")
        else:
            print("No compaction needed")
```

- [ ] **Step 3: 编写集成测试**

```python
# tests/test_agent_session_integration.py
import tempfile
import pytest
from pathlib import Path
from uuid import uuid4

from bourbon.agent import Agent
from bourbon.config import Config


@pytest.fixture
def temp_config():
    """临时配置"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Config()
        config.ui.token_threshold = 1000
        yield config, Path(tmpdir)


def test_agent_creates_session_on_init(temp_config):
    """测试 Agent 初始化时创建 Session"""
    config, tmpdir = temp_config
    
    agent = Agent(config, workdir=tmpdir)
    
    assert agent.session is not None
    assert agent.session_manager.current_session is not None


def test_agent_step_adds_message(temp_config):
    """测试 step 添加消息到 Session"""
    config, tmpdir = temp_config
    
    agent = Agent(config, workdir=tmpdir)
    initial_count = agent.session.chain.message_count
    
    # 使用 mock LLM 来测试
    # ...


def test_agent_messages_property(temp_config):
    """测试 messages 属性向后兼容"""
    config, tmpdir = temp_config
    
    agent = Agent(config, workdir=tmpdir)
    
    # 应该返回列表
    msgs = agent.messages
    assert isinstance(msgs, list)
```

- [ ] **Step 4: 运行集成测试**

Run: `pytest tests/test_agent_session_integration.py -v`
Expected: 测试 PASS（可能需要 mock LLM）

- [ ] **Step 5: Commit**

```bash
git add src/bourbon/agent.py src/bourbon/repl.py
git add tests/test_agent_session_integration.py
git commit -m "feat(agent): integrate Session system with backward compatibility"
```

---

## Task 7: CLI 集成 (--resume, --continue)

**Files:**
- Modify: `src/bourbon/cli.py`

- [ ] **Step 1: 添加 CLI 选项**

```python
# src/bourbon/cli.py - 添加 session 相关选项

import argparse
from uuid import UUID

def main():
    parser = argparse.ArgumentParser(description="Bourbon - AI Agent")
    
    # 现有选项...
    
    # Session 管理选项
    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="Resume a specific session by ID",
    )
    session_group.add_argument(
        "--continue",
        dest="continue_last",
        action="store_true",
        help="Continue the most recent session",
    )
    session_group.add_argument(
        "--new-session",
        action="store_true",
        help="Start a new session (don't resume)",
    )
    
    parser.add_argument(
        "--session-desc",
        help="Description for the new session",
    )
    
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List available sessions and exit",
    )
    
    args = parser.parse_args()
    
    # 处理 --list-sessions
    if args.list_sessions:
        _list_sessions_and_exit()
    
    # 确定 session 策略
    session_id = None
    resume_last = False
    
    if args.resume:
        try:
            session_id = UUID(args.resume)
        except ValueError:
            print(f"Invalid session ID: {args.resume}")
            sys.exit(1)
    elif args.continue_last:
        resume_last = True
    elif args.new_session:
        session_id = None
        resume_last = False
    
    # 创建 Agent
    config = load_config()
    agent = Agent(
        config,
        workdir=Path.cwd(),
        session_id=session_id,
        resume_last=resume_last,
    )
    
    # 如果有描述，设置到会话
    if args.session_desc and agent.session:
        agent.session.metadata.description = args.session_desc
    
    # ... 启动 REPL 或处理输入


def _list_sessions_and_exit():
    """列出会话并退出"""
    from bourbon.session import SessionManager
    
    manager = SessionManager(project_dir=Path.cwd())
    sessions = manager.list_sessions()
    
    if not sessions:
        print("No sessions found for this project")
        sys.exit(0)
    
    print(f"\nAvailable sessions for {Path.cwd().name}:")
    print(f"{'ID':<36} {'Last Activity':<20} {'Msgs':<6} Description")
    print("-" * 100)
    
    for s in sessions:
        desc = s.description[:40] + "..." if len(s.description) > 40 else s.description
        activity = s.last_activity.strftime("%Y-%m-%d %H:%M")
        print(f"{str(s.uuid):<36} {activity:<20} {s.message_count:<6} {desc}")
    
    print(f"\nUse --resume <ID> to resume a session")
    print(f"Use --continue to resume the most recent session")
    sys.exit(0)
```

- [ ] **Step 2: 测试 CLI**

Run: `python -m bourbon --help`
Expected: 显示新的 session 选项

Run: `python -m bourbon --list-sessions`
Expected: 显示会话列表或 "No sessions found"

- [ ] **Step 3: Commit**

```bash
git add src/bourbon/cli.py
git commit -m "feat(cli): add --resume, --continue, --list-sessions options"
```

---

## Task 8: 清理旧 Compression 代码

**Files:**
- Modify: `src/bourbon/compression.py`
- Modify: `tests/test_compression.py`

- [ ] **Step 1: 标记旧代码为弃用**

```python
# src/bourbon/compression.py
"""Context compression - DEPRECATED

This module is deprecated. Use bourbon.session.context instead.
"""

import warnings

warnings.warn(
    "bourbon.compression is deprecated. Use bourbon.session.context instead.",
    DeprecationWarning,
    stacklevel=2,
)

# 保留旧实现作为兼容层，但内部使用新的 ContextManager

from .session.context import TokenTracker, CompactStrategy, ContextManager
from .session.chain import MessageChain


class ContextCompressor:
    """
    Context compression - DEPRECATED
    
    Use bourbon.session.ContextManager instead.
    """
    
    def __init__(self, token_threshold: int = 100000, ...):
        warnings.warn("ContextCompressor is deprecated", DeprecationWarning)
        self.token_threshold = token_threshold
        # 内部使用新的 TokenTracker
        self._tracker = TokenTracker(token_threshold)
    
    def estimate_tokens(self, messages: list[dict]) -> int:
        """Estimate token count"""
        return self._tracker.estimate_tokens(messages)
    
    def should_compact(self, messages: list[dict]) -> bool:
        """Check if compaction is needed"""
        # 创建临时 chain 来检查
        chain = MessageChain()
        for msg in messages:
            # 转换消息格式...
            pass
        status = self._tracker.check_status(chain)
        return status.ratio > 0.75  # 旧阈值
    
    def microcompact(self, messages: list[dict]) -> None:
        """Micro-compaction - now a no-op"""
        # 新系统使用 ContextManager.maybe_compact()
        pass
    
    def compact(self, messages: list[dict]) -> list[dict]:
        """Full compaction - DEPRECATED"""
        warnings.warn(
            "compact() is deprecated. Use ContextManager.check_and_compact()",
            DeprecationWarning,
        )
        # 返回原列表，让新系统处理
        return messages
```

- [ ] **Step 2: 更新测试**

```python
# tests/test_compression.py
import warnings
import pytest

from bourbon.compression import ContextCompressor


def test_compression_emits_deprecation_warning():
    """测试压缩模块发出弃用警告"""
    with pytest.deprecated_call():
        compressor = ContextCompressor()


def test_microcompact_noop():
    """测试 microcompact 现在是空操作"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        compressor = ContextCompressor()
        messages = [{"role": "user", "content": "test"}]
        compressor.microcompact(messages)  # 不应报错
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_compression.py -v`
Expected: 测试 PASS

- [ ] **Step 4: Commit**

```bash
git add src/bourbon/compression.py tests/test_compression.py
git commit -m "refactor(compression): mark old compressor as deprecated, use session.context"
```

---

## Task 9: 文档与示例

**Files:**
- Create: `docs/superpowers/session-system-guide.md`
- Modify: `README.md` (添加 session 文档)

- [ ] **Step 1: 创建 Session 系统使用指南**

```markdown
# Bourbon Session System Guide

## 快速开始

### 创建新会话
```bash
bourbon --new-session --session-desc "Working on feature X"
```

### 恢复最近的会话
```bash
bourbon --continue
```

### 恢复特定会话
```bash
bourbon --resume 550e8400-e29b-41d4-a716-446655440000
```

### 列出所有会话
```bash
bourbon --list-sessions
```

## REPL 命令

| 命令 | 说明 |
|------|------|
| `/session` | 显示当前会话信息 |
| `/sessions` | 列出可恢复会话 |
| `/compact` | 手动执行压缩 |

## 编程接口

```python
from bourbon.session import SessionManager

# 创建管理器
manager = SessionManager(project_dir="/path/to/project")

# 创建会话
session = manager.create_session(description="My session")

# 添加消息
from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock
msg = TranscriptMessage(
    role=MessageRole.USER,
    content=[TextBlock(text="Hello")],
)
session.add_message(msg)

# 获取 LLM 消息
llm_msgs = session.get_messages_for_llm()

# 检查 Token 状态
status = session.get_token_status()
print(f"Token usage: {status.current_tokens}/{status.threshold}")

# 保存
session.save()

# 恢复会话
loaded = manager.load_session(session.metadata.uuid)
```

## 存储位置

```
~/.bourbon/sessions/
└── <project-name>/
    ├── <session-id>.jsonl
    ├── <session-id>.meta.json
    └── sidechains/
```

## 压缩策略

| 级别 | 触发条件 | 行为 |
|------|----------|------|
| NORMAL | 0-50% | 正常操作 |
| WARM | 50-75% | 温和清理旧 tool 结果 |
| HOT | 75-90% | 归档 50% 旧消息 |
| CRITICAL | 90-100% | 只保留最近 2 条消息 |
```

- [ ] **Step 2: Commit 文档**

```bash
git add docs/superpowers/session-system-guide.md
git commit -m "docs: add session system usage guide"
```

---

## Task 10: 最终测试与验证

- [ ] **Step 1: 运行全部测试**

```bash
# 类型检查
mypy src/bourbon/session/

# 单元测试
pytest tests/session/ -v --tb=short

# 集成测试
pytest tests/test_agent_session_integration.py -v

# 旧测试回归
pytest tests/ -v --ignore=tests/test_compression.py -k "not deprecated"
```

Expected: 所有测试 PASS

- [ ] **Step 2: 功能验证**

```bash
# 测试会话创建
python -c "
from bourbon.session import SessionManager
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmpdir:
    manager = SessionManager(storage_dir=Path(tmpdir), project_dir=Path(tmpdir))
    session = manager.create_session(description='Test')
    session.save()
    
    # 验证可以加载
    loaded = manager.load_session(session.metadata.uuid)
    print(f'Created: {session.metadata.uuid}')
    print(f'Loaded: {loaded.metadata.uuid}')
    assert session.metadata.uuid == loaded.metadata.uuid
    print('✓ Session persistence works!')
"
```

- [ ] **Step 3: 性能基准测试**

```python
# tests/session/test_performance.py
import tempfile
import time
from pathlib import Path

from bourbon.session import SessionManager
from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock


def test_large_session_performance():
    """测试大会话性能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(
            storage_dir=Path(tmpdir),
            project_dir=Path(tmpdir),
        )
        session = manager.create_session()
        
        # 添加 1000 条消息
        start = time.time()
        for i in range(1000):
            msg = TranscriptMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=[TextBlock(text=f"Message {i}")],
            )
            session.add_message(msg)
        
        build_time = time.time() - start
        
        # 保存
        start = time.time()
        session.save()
        save_time = time.time() - start
        
        # 加载
        start = time.time()
        loaded = manager.load_session(session.metadata.uuid)
        load_time = time.time() - start
        
        print(f"Build 1000 messages: {build_time:.2f}s")
        print(f"Save: {save_time:.2f}s")
        print(f"Load: {load_time:.2f}s")
        
        # 性能要求：每项 < 1s
        assert build_time < 1.0
        assert save_time < 1.0
        assert load_time < 1.0
```

Run: `pytest tests/session/test_performance.py -v`
Expected: 性能测试 PASS

- [ ] **Step 4: 最终 Commit**

```bash
git add tests/session/test_performance.py
git commit -m "test(session): add performance benchmarks"
```

---

## 总结

### 完成的功能

1. ✅ **核心类型系统** (`types.py`) - UUID、MessageRole、TranscriptMessage
2. ✅ **消息链** (`chain.py`) - parentUuid / logicalParentUuid 链式结构
3. ✅ **持久化存储** (`storage.py`) - JSONL 增量写入、去重
4. ✅ **Token 管理** (`context.py`) - 多级压缩策略
5. ✅ **Session 管理器** (`manager.py`) - 生命周期管理
6. ✅ **Agent 集成** - 向后兼容的集成
7. ✅ **CLI 集成** - `--resume`, `--continue`, `--list-sessions`
8. ✅ **文档** - 使用指南

### 存储结构

```
~/.bourbon/sessions/
└── <project-name>/
    ├── <session-id>.jsonl       # 消息历史
    ├── <session-id>.meta.json   # 元数据
    └── sidechains/              # 子代理消息
```

### API 变化

| 旧 API | 新 API |
|--------|--------|
| `agent.messages` | `agent.session.get_messages_for_llm()` |
| `ContextCompressor` | `session.maybe_compact()` |
| 无 | `bourbon --resume <id>` |
| 无 | `bourbon --continue` |

### 向后兼容

- `agent.messages` 属性保持可用
- 旧 `ContextCompressor` 标记为弃用但可用

---

**计划完成！**

**执行选项:**

**1. Subagent-Driven (推荐)** - 我派遣独立的子代理逐个任务执行，每个任务后有两阶段 Review

**2. Inline Execution** - 在当前会话中逐个执行任务，使用 executing-plans skill

**请选择执行方式？**
