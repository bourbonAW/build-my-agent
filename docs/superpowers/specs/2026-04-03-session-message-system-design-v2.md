# Bourbon Session & Message System Redesign (v2 - 修正版)

> **Status:** REVISED after code review  
> **Changes from v1:** Fixed logical_parent_uuid semantics, unified persistence model, completed tool round recovery

---

## 关键修正总结 (Key Fixes)

### 1. logical_parent_uuid 语义修正

**错误理解 (v1):**
```python
# 错误！这会把归档消息重新串回 active chain
next_uuid = message.logical_parent_uuid or message.parent_uuid
```

**正确理解 (v2 - 参考 Claude Code):**
```python
# 正确！active chain 只走 parent_uuid
# logical_parent_uuid 仅用于展示/调试，不参与链构建
current_uuid = message.parent_uuid  # 唯一回溯边
```

### 2. 持久化模型统一

**决策: Append-Only Transcript + In-Memory Session State**

```
┌─────────────────────────────────────────────────────────────┐
│                   两层模型 (Two-Layer Model)                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Transcript (Append-Only, Immutable)               │
│  ─────────────────────────────────────────────              │
│  - JSONL 文件，只追加，永不修改                              │
│  - 完整记录所有消息，包括已被 compact 的                      │
│  - 用于审计、回放、调试                                      │
│                                                             │
│  Layer 2: Session State (In-Memory, Mutable)                │
│  ─────────────────────────────────────────────              │
│  - MessageChain 只包含 active messages                       │
│  - Compact 从内存链中删除消息，但 transcript 保留            │
│  - Clear 重建空链，transcript 不受影响                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3. Tool Round 完整实现

参考 Claude Code 的设计：
- `source_tool_uuid`: tool_result → 生成它的 assistant message
- `parent_uuid` chain: 用于构建 active conversation
- `recover_orphaned_parallel_tool_results`: 恢复并行的 tool results

---

## 核心类型系统 (v2)

```python
# src/bourbon/session/types.py

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


# Content Blocks
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
class TranscriptMessage:
    """
    链式消息结构
    
    Chain Building Rule (Critical):
    - 只有 parent_uuid 参与 active chain 构建
    - logical_parent_uuid 仅用于调试/展示，不参与链构建
    - 这是与 Claude Code 设计保持一致的关键
    """
    # Identity
    uuid: UUID = field(default_factory=uuid4)
    session_id: UUID = field(default_factory=uuid4)
    
    # Chain Structure (CRITICAL: Only parent_uuid for active chain!)
    parent_uuid: UUID | None = None           # 物理链：唯一用于构建 active chain 的边
    logical_parent_uuid: UUID | None = None   # 逻辑链：仅用于调试，不参与链构建
    
    # Content
    role: MessageRole = MessageRole.USER
    content: list[MessageContent] = field(default_factory=list)
    
    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    usage: TokenUsage | None = None
    
    # Tool Association (CRITICAL for recovery)
    # tool_result message -> 生成它的 assistant message (包含 tool_use)
    source_tool_uuid: UUID | None = None
    
    # Compact Boundary
    is_compact_boundary: bool = False
    compact_metadata: CompactMetadata | None = None


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
class SessionMetadata:
    uuid: UUID
    parent_uuid: UUID | None
    project_dir: str
    created_at: datetime
    last_activity: datetime
    message_count: int = 0  # Active message count (not transcript count)
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
```

---

## MessageChain (v2 - 修正版)

```python
# src/bourbon/session/chain.py

from collections import OrderedDict
from uuid import UUID

from .types import TranscriptMessage, MessageRole, TextBlock, CompactMetadata, CompactTrigger


class MessageChain:
    """
    Active Message Chain - In-Memory Only
    
    职责：
    1. 维护当前活跃的对话链（内存中可变）
    2. 构建给 LLM 的消息列表
    3. 执行 compact（从内存链中删除消息）
    
    注意：这不负责持久化！持久化由 TranscriptStore 处理
    """
    
    def __init__(self):
        self._messages: OrderedDict[UUID, TranscriptMessage] = OrderedDict()
        self._leaf_uuid: UUID | None = None
        self._root_uuid: UUID | None = None
    
    def append(self, message: TranscriptMessage) -> None:
        """
        添加消息到 active chain
        
        自动设置 parent_uuid 为当前叶子
        """
        if self._leaf_uuid:
            message.parent_uuid = self._leaf_uuid
        else:
            self._root_uuid = message.uuid
            
        self._messages[message.uuid] = message
        self._leaf_uuid = message.uuid
    
    def build_active_chain(self) -> list[TranscriptMessage]:
        """
        构建活跃对话链
        
        CRITICAL: 只使用 parent_uuid 回溯！
        logical_parent_uuid 不参与链构建！
        
        算法 (参考 Claude Code):
        1. 从 leaf_uuid 开始
        2. 只使用 parent_uuid 向上回溯
        3. 遇到 parent_uuid = null 停止（compact boundary）
        4. 反转得到从根到叶的顺序
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
            # logical_parent_uuid 不参与 active chain 构建
            current_uuid = message.parent_uuid
        
        chain.reverse()
        return chain
    
    def get_llm_messages(self) -> list[dict]:
        """
        获取给 LLM 的消息列表
        
        过滤：
        - compact_boundary 消息不传给 LLM
        - 返回的是副本，外部修改不影响 chain
        """
        chain = self.build_active_chain()
        llm_messages = []
        
        for msg in chain:
            if msg.is_compact_boundary:
                continue
            llm_messages.append(msg.to_llm_format())
        
        return llm_messages
    
    def compact(self, preserve_count: int = 3, summary: str = "") -> CompactResult:
        """
        Compact Active Chain
        
        操作：
        1. 保留最近 preserve_count 条消息
        2. 从内存链中删除旧消息（transcript 中仍保留）
        3. 创建 compact_boundary 消息
        4. 更新 parent_uuid（不是 logical_parent_uuid！）
        
        注意：旧消息从内存删除，但已经在 transcript 中持久化
        """
        chain = self.build_active_chain()
        if len(chain) <= preserve_count:
            return CompactResult(success=False, reason="insufficient_messages")
        
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
                trigger=CompactTrigger.AUTO_THRESHOLD,
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
        
        # boundary 的 parent 为 None（compact 边界）
        boundary.parent_uuid = None
        # logical_parent_uuid 仅用于记录逻辑关系，不参与链构建
        boundary.logical_parent_uuid = last_archived.uuid
        
        self._messages[boundary.uuid] = boundary
        
        # 第一个保留消息的 parent 指向 boundary
        first_preserved.parent_uuid = boundary.uuid
        # logical_parent_uuid 保留原来的连接（用于调试）
        if not first_preserved.logical_parent_uuid:
            first_preserved.logical_parent_uuid = last_archived.uuid
        
        return CompactResult(
            success=True,
            archived_count=len(to_archive),
            preserved_count=len(to_preserve),
            boundary_uuid=boundary.uuid,
        )
    
    def clear(self) -> None:
        """
        清空 active chain
        
        注意：只清空内存链，transcript 不受影响
        """
        self._messages.clear()
        self._leaf_uuid = None
        self._root_uuid = None
    
    def rebuild_from_transcript(
        self,
        transcript: list[TranscriptMessage],
        resume_from: UUID | None = None,
    ) -> None:
        """
        从 transcript 重建 active chain
        
        用于：
        1. 初始加载：从完整 transcript 构建
        2. 恢复会话：从特定点重建
        
        算法：
        1. 如果 resume_from 为 None，找到最新的非 compact_boundary 叶子
        2. 从该叶子使用 parent_uuid 回溯构建链
        3. 处理 tool_use/tool_result 配对
        """
        self.clear()
        
        if not transcript:
            return
        
        # 构建 UUID -> Message 映射
        msg_map = {msg.uuid: msg for msg in transcript}
        
        # 找到 resume point
        if resume_from is None:
            # 找到最新的非 compact_boundary 消息
            for msg in reversed(transcript):
                if not msg.is_compact_boundary:
                    resume_from = msg.uuid
                    break
        
        if resume_from is None or resume_from not in msg_map:
            return
        
        # 从 resume point 回溯构建链
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
        
        # 反转并添加到 chain
        chain.reverse()
        for msg in chain:
            self._messages[msg.uuid] = msg
        
        if chain:
            self._root_uuid = chain[0].uuid
            self._leaf_uuid = chain[-1].uuid
        
        # 恢复 orphaned parallel tool results
        self._recover_tool_results(msg_map, seen)
    
    def _recover_tool_results(
        self,
        msg_map: dict[UUID, TranscriptMessage],
        active_uuids: set[UUID],
    ) -> None:
        """
        恢复孤立的并行 tool results
        
        场景：一轮中有多个 tool_use，某些 tool_result 的 parent
        可能不在当前 active chain 中（由于 compact）
        """
        # 找到所有 active assistant 消息中的 tool_use
        tool_use_ids: set[str] = set()
        for uuid in active_uuids:
            msg = msg_map.get(uuid)
            if msg and msg.role == MessageRole.ASSISTANT:
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        tool_use_ids.add(block.id)
        
        # 找到所有已解决的 tool_result
        resolved_ids: set[str] = set()
        for uuid in active_uuids:
            msg = msg_map.get(uuid)
            if msg and msg.role == MessageRole.USER:
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        resolved_ids.add(block.tool_use_id)
        
        # 找到未解决的 tool_use，从 transcript 恢复对应的 tool_result
        unresolved = tool_use_ids - resolved_ids
        for tool_id in unresolved:
            # 在 transcript 中查找对应的 tool_result
            for msg in msg_map.values():
                if msg.role == MessageRole.USER:
                    for block in msg.content:
                        if isinstance(block, ToolResultBlock) and block.tool_use_id == tool_id:
                            # 恢复这个 tool_result 到 active chain
                            if msg.uuid not in self._messages:
                                self._messages[msg.uuid] = msg
                                # 设置 parent 指向 source assistant
                                for assistant_uuid in active_uuids:
                                    assistant_msg = msg_map.get(assistant_uuid)
                                    if assistant_msg and assistant_msg.role == MessageRole.ASSISTANT:
                                        for a_block in assistant_msg.content:
                                            if isinstance(a_block, ToolUseBlock) and a_block.id == tool_id:
                                                msg.parent_uuid = assistant_uuid
                                                break


@dataclass
class CompactResult:
    success: bool
    archived_count: int = 0
    preserved_count: int = 0
    boundary_uuid: UUID | None = None
    reason: str = ""
```

---

## TranscriptStore (v2 - 两层模型)

```python
# src/bourbon/session/storage.py

import json
from pathlib import Path
from uuid import UUID

from .types import TranscriptMessage, SessionMetadata, SessionSummary


class TranscriptStore:
    """
    Two-Layer Persistence:
    
    Layer 1 - Transcript (Append-Only):
    - 完整记录所有消息历史
    - JSONL 格式，只追加
    - 用于审计、回放
    
    Layer 2 - Active State (Snapshot):
    - 可选：保存当前活跃链的快照
    - 用于快速恢复（不遍历完整 transcript）
    """
    
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    # === Layer 1: Transcript (Append-Only) ===
    
    def append_to_transcript(
        self,
        project_name: str,
        session_id: UUID,
        messages: list[TranscriptMessage],
    ) -> None:
        """
        追加消息到 transcript - 永不修改已有内容
        
        去重：基于 UUID，跳过已存在的消息
        """
        path = self._get_transcript_path(project_name, session_id)
        existing = self._get_existing_uuids(path)
        
        new_messages = [m for m in messages if m.uuid not in existing]
        if not new_messages:
            return
        
        with open(path, "a") as f:
            for msg in new_messages:
                f.write(json.dumps(self._serialize(msg), default=str) + "\n")
    
    def load_transcript(
        self,
        project_name: str,
        session_id: UUID,
    ) -> list[TranscriptMessage]:
        """加载完整 transcript"""
        path = self._get_transcript_path(project_name, session_id)
        
        if not path.exists():
            return []
        
        messages = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        messages.append(self._deserialize(data))
                    except (json.JSONDecodeError, KeyError):
                        continue
        
        return messages
    
    # === Layer 2: Session Metadata ===
    
    def save_metadata(self, project_name: str, metadata: SessionMetadata) -> None:
        """保存会话元数据"""
        path = self._get_meta_path(project_name, metadata.uuid)
        with open(path, "w") as f:
            json.dump({
                "uuid": str(metadata.uuid),
                "parent_uuid": str(metadata.parent_uuid) if metadata.parent_uuid else None,
                "project_dir": metadata.project_dir,
                "created_at": metadata.created_at.isoformat(),
                "last_activity": metadata.last_activity.isoformat(),
                "message_count": metadata.message_count,
                "total_tokens_used": metadata.total_tokens_used,
                "is_active": metadata.is_active,
                "description": metadata.description,
            }, f, indent=2)
    
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
        """列出可恢复会话"""
        project_dir = self.base_dir / project_name
        
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
        
        sessions.sort(key=lambda s: s.last_activity, reverse=True)
        return sessions
    
    def _get_transcript_path(self, project_name: str, session_id: UUID) -> Path:
        project_dir = self.base_dir / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / f"{session_id}.jsonl"
    
    def _get_meta_path(self, project_name: str, session_id: UUID) -> Path:
        project_dir = self.base_dir / project_name
        return project_dir / f"{session_id}.meta.json"
```

---

## Agent 集成策略 (解决向后兼容)

```python
# src/bourbon/agent.py - 关键集成点

class Agent:
    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        session_id: UUID | None = None,
        resume_last: bool = False,
        ...
    ):
        # ... 初始化 Session ...
        
        # 向后兼容：提供 _pending_messages 用于累积
        self._pending_messages: list[dict] = []
    
    def step(self, user_input: str) -> str:
        """处理用户输入 - 完全重写以使用 Session"""
        from bourbon.session.types import TranscriptMessage, MessageRole, TextBlock
        
        # 直接创建 TranscriptMessage，不使用 self.messages.append
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=user_input)],
        )
        self.session.add_message(user_msg)
        
        # 持久化用户消息
        self.session.save()
        
        # 检查压缩
        self.session.maybe_compact()
        
        # 运行对话循环
        return self._run_conversation_loop()
    
    def _run_conversation_loop(self) -> str:
        """对话循环 - 重写以使用 Session"""
        while tool_round < self._max_tool_rounds:
            # 从 Session 获取消息
            messages = self.session.get_messages_for_llm()
            
            # 调用 LLM
            response = self.llm.chat(messages=messages, ...)
            
            # 转换并添加到 Session
            assistant_msg = self._convert_response_to_message(response)
            self.session.add_message(assistant_msg)
            self.session.save()
            
            # 处理 tool calls...
            if has_tool_calls:
                tool_results = self._execute_tools(tool_use_blocks)
                
                # 添加 tool results 到 Session
                for result in tool_results:
                    tool_msg = self._convert_tool_result_to_message(result)
                    self.session.add_message(tool_msg)
                
                self.session.save()
            else:
                return extract_text(response)
    
    # 废弃 messages 属性的 setter
    @property
    def messages(self) -> list[dict]:
        """
        获取当前消息列表（只读）
        
        DEPRECATED: 使用 self.session.get_messages_for_llm()
        注意：返回的是副本，修改不会生效
        """
        if self.session:
            return self.session.get_messages_for_llm()
        return []
    
    @messages.setter
    def messages(self, value):
        """
        废弃：直接设置消息列表
        
        这会导致与 Session 不同步。如果需要重建会话，
        请使用 SessionManager 的 API。
        """
        import warnings
        warnings.warn(
            "Setting messages directly is deprecated. "
            "Use session.add_message() instead.",
            DeprecationWarning,
        )
```

---

## Sidechain 降级说明

**决策：Sidechain 不在本期交付**

原因：
1. Bourbon 目前没有真正的 subagent 机制
2. Sidechain 需要额外的 Agent 架构支持
3. 优先保证 core session 功能的稳定性

**从目标中移除：**
- ❌ Sidechain 独立存储
- ❌ 子代理消息隔离

**保留：**
- `is_sidechain` 字段（为未来预留）
- 但不实现相关逻辑

---

## 成功标准 (v2)

- [ ] `parent_uuid` 是唯一用于 active chain 构建的边
- [ ] `logical_parent_uuid` 不参与链构建
- [ ] Transcript 是 append-only，永不修改
- [ ] Compact 从内存链删除消息，transcript 保留完整历史
- [ ] Clear 重建空内存链，transcript 不受影响
- [ ] Tool result 的 parent 指向 source assistant message
- [ ] 恢复时正确处理 orphaned parallel tool results
- [ ] 所有现有代码路径使用新的 Session API（不使用 `self.messages.append`）
- [ ] 单元测试覆盖核心逻辑
- [ ] 集成测试验证持久化和恢复

---

*Version: 2.0*  
*Status: 待 Review*  
*关键修正: logical_parent 语义、两层持久化模型、tool round 完整实现*
