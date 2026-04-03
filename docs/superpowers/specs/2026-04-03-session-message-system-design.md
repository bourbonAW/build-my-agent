# Bourbon Session & Message System Redesign

> **For agentic workers:** This spec defines the architecture for重构 Bourbon's session and message management system based on Claude Code's proven design.
> 
> **Related Research:** `wiki/architecture/session-message-system.md`

---

## 1. 现状与问题

### 1.1 当前实现 (Before)

```python
# src/bourbon/agent.py - 当前简陋实现
class Agent:
    def __init__(self, ...):
        # 问题1: 无存证，无 Session ID
        self.messages: list[dict] = []  # 简单列表，无链式结构
        
    def step(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        # ... 直接传递 messages 给 LLM
```

```python
# src/bourbon/compression.py - 当前简陋压缩
class ContextCompressor:
    def compact(self, messages: list[dict]) -> list[dict]:
        # 问题2: 直接替换 messages，丢失所有上下文关系
        summary = self._generate_summary(messages)
        return [
            {"role": "user", "content": f"[Context compressed] {summary}"},
            {"role": "assistant", "content": "Understood."}
        ]
```

### 1.2 核心问题

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| **无 Session ID** | 无法恢复、无法追踪会话历史 | 🔴 Critical |
| **简单列表结构** | 无 UUID，无法构建消息链 | 🔴 Critical |
| **无持久化** | 进程结束即丢失所有历史 | 🔴 Critical |
| **Compression 破坏关系** | 压缩后上下文断裂，LLM 困惑 | 🟠 High |
| **无 Token 预警** | 到达上限时突然失败 | 🟠 High |
| **无 Sidechain 支持** | 子代理污染主会话上下文 | 🟡 Medium |

### 1.3 Claude Code 的优势

| 特性 | Claude Code 实现 | Bourbon 现状 |
|------|------------------|--------------|
| Session 管理 | UUID + parent_session_id | 无 |
| 消息链 | UUID + parentUuid + logicalParentUuid | 无 |
| 持久化 | JSONL 增量写入 | 无 |
| 压缩 | Compact Boundary 保留逻辑关系 | 直接替换 |
| Token 管理 | 多级预警 + 渐进压缩 | 简单阈值 |
| 子代理 | Sidechain 独立存储 | 无 |

---

## 2. 设计目标

### 2.1 主要目标

1. **可恢复**: 会话可持久化，支持 `--continue` 恢复
2. **可追踪**: UUID 链式结构，支持消息溯源
3. **智能压缩**: 保留逻辑关系，渐进式处理
4. **Token 友好**: 多级预警，平滑处理上限
5. **子代理隔离**: Sidechain 独立存储

### 2.2 设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                     设计原则 (Design Principles)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. BACKWARD COMPATIBLE      现有代码可渐进式迁移                  │
│                                                                 │
│  2. EVENT-SOURCED-LIKE       消息不可变，追加写入                  │
│                                                                 │
│  3. SEPARATION OF CONCERNS   Session / Chain / Store 分离         │
│                                                                 │
│  4. FAIL-SAFE                Token 上限前有预警和防护              │
│                                                                 │
│  5. OBSERVABLE               清晰的调试和追踪能力                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Bourbon Session Architecture                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         SessionManager                               │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │   │
│  │  │   Session    │  │   Message    │  │   TranscriptStore        │  │   │
│  │  │   (metadata) │  │   Chain      │  │   (persistence)          │  │   │
│  │  │              │  │              │  │                          │  │   │
│  │  │ - uuid       │  │ - messages   │  │ - append()               │  │   │
│  │  │ - parent_uuid│  │ - append()   │  │ - load()                 │  │   │
│  │  │ - created_at │  │ - compact()  │  │ - list_sessions()        │  │   │
│  │  │ - project_dir│  │ - to_llm()   │  │                          │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         ContextManager                               │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │   │
│  │  │ TokenTracker │  │   Compact    │  │   TokenStrategy          │  │   │
│  │  │              │  │   Strategy   │  │                          │  │   │
│  │  │ - estimate() │  │              │  │ - NORMAL (0-50%)         │  │   │
│  │  │ - current()  │  │ - compact()  │  │ - WARM (50-75%)          │  │   │
│  │  │ - ratio()    │  │ - snip()     │  │ - HOT (75-90%)           │  │   │
│  │  └──────────────┘  └──────────────┘  │ - CRITICAL (90-100%)     │  │   │
│  │                                       └──────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Storage Layout                               │   │
│  │                                                                      │   │
│  │   ~/.bourbon/sessions/                                               │   │
│  │   └── <project-name>/                                                │   │
│  │       ├── <session-id>.jsonl          # 主会话消息                   │   │
│  │       ├── <session-id>.meta.json      # 会话元数据                   │   │
│  │       └── sidechains/                                                │   │
│  │           └── <agent-id>.jsonl        # 子代理消息                   │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心类型系统

```python
# src/bourbon/session/types.py
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


@dataclass
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


@dataclass  
class ContentBlock:
    """内容块基类"""
    type: str


@dataclass
class TextBlock(ContentBlock):
    """文本块"""
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock(ContentBlock):
    """工具调用块"""
    id: str
    name: str
    input: dict = field(default_factory=dict)
    type: str = "tool_use"


@dataclass
class ToolResultBlock(ContentBlock):
    """工具结果块"""
    tool_use_id: str
    content: str
    is_error: bool = False
    type: str = "tool_result"


@dataclass
class ThinkingBlock(ContentBlock):
    """思考块（Claude 3.7+ thinking）"""
    thinking: str
    signature: str | None = None
    type: str = "thinking"


# Union type for content blocks
MessageContent = TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock


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
        return {
            "role": self.role.value,
            "content": [
                block.__dict__ for block in self.content
            ]
        }


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

### 3.3 MessageChain 链式结构

```python
# src/bourbon/session/chain.py
"""消息链管理 - 核心算法实现"""

from collections import OrderedDict
from uuid import UUID

from .types import TranscriptMessage


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
        strategy: CompactStrategy = None,
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
        # 实现细节见 CompactStrategy
        pass
    
    def snip(self, start_uuid: UUID, end_uuid: UUID) -> None:
        """
        删除指定范围的消息
        
        与 compact 不同，snip 完全删除消息并重新链接:
        - Msg1 -> [Msg2, Msg3, Msg4] -> Msg5
        - 删除 Msg2-4 后: Msg1 -> Msg5
        """
        pass
    
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

### 3.4 持久化存储

```python
# src/bourbon/session/storage.py
"""JSONL 持久化存储"""

import json
from pathlib import Path
from uuid import UUID

from .types import TranscriptMessage, SessionMetadata


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
    
    def _get_session_path(self, project_name: str, session_id: UUID) -> Path:
        """获取会话文件路径"""
        session_dir = self.base_dir / project_name
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / f"{session_id}.jsonl"
    
    def _get_meta_path(self, project_name: str, session_id: UUID) -> Path:
        """获取元数据文件路径"""
        session_dir = self.base_dir / project_name
        return session_dir / f"{session_id}.meta.json"
    
    def append_messages(
        self,
        project_name: str,
        session_id: UUID,
        messages: list[TranscriptMessage],
    ) -> None:
        """
        追加消息到 transcript
        
        实现:
        1. 检查已存在的 UUID（去重）
        2. 只写入新消息
        3. 原子性写入（先写临时文件，再重命名）
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
            return
        
        # 追加写入
        with open(path, "a") as f:
            for msg in new_messages:
                f.write(json.dumps(self._serialize_message(msg), default=str) + "\n")
    
    def load_session(
        self,
        project_name: str,
        session_id: UUID,
    ) -> tuple[SessionMetadata, list[TranscriptMessage]]:
        """
        加载完整会话
        
        Returns:
            (metadata, messages)
        """
        # 加载元数据
        meta_path = self._get_meta_path(project_name, session_id)
        metadata = self._load_metadata(meta_path)
        
        # 加载消息
        path = self._get_session_path(project_name, session_id)
        messages = self._load_messages(path)
        
        return metadata, messages
    
    def list_sessions(self, project_name: str) -> list[SessionSummary]:
        """
        列出项目的所有可恢复会话
        
        过滤:
        - 只返回非 sidechain 的主会话
        - 按 last_activity 排序
        """
        project_dir = self.base_dir / project_name
        if not project_dir.exists():
            return []
        
        sessions = []
        for meta_file in project_dir.glob("*.meta.json"):
            metadata = self._load_metadata(meta_file)
            if metadata.is_active:
                sessions.append(SessionSummary(
                    uuid=metadata.uuid,
                    description=metadata.description,
                    last_activity=metadata.last_activity,
                    message_count=metadata.message_count,
                    is_resumable=True,
                ))
        
        # 按最后活动时间排序
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
            "content": [block.__dict__ for block in msg.content],
            "timestamp": msg.timestamp.isoformat(),
            "usage": msg.usage.__dict__ if msg.usage else None,
            "agent_id": msg.agent_id,
            "is_sidechain": msg.is_sidechain,
            "source_tool_uuid": str(msg.source_tool_uuid) if msg.source_tool_uuid else None,
            "is_compact_boundary": msg.is_compact_boundary,
            "compact_metadata": msg.compact_metadata.__dict__ if msg.compact_metadata else None,
        }
    
    def _deserialize_message(self, data: dict) -> TranscriptMessage:
        """从 JSON 反序列化消息"""
        # 实现细节...
        pass
```

### 3.5 Token 管理与压缩策略

```python
# src/bourbon/session/context.py
"""上下文管理和 Token 策略"""

from dataclasses import dataclass
from enum import Enum, auto

from .chain import MessageChain
from .types import TokenUsage


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
    
    def __str__(self) -> str:
        return f"TokenStatus({self.current_tokens}/{self.threshold}, {self.ratio:.1%})"


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
        ratio = current / self.threshold
        
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
        )


class CompactStrategy:
    """
    压缩策略
    
    多级压缩策略，根据 Token 级别采取不同措施:
    """
    
    def __init__(self, chain: MessageChain, tracker: TokenTracker):
        self.chain = chain
        self.tracker = tracker
    
    def execute(self) -> CompactResult:
        """
        根据当前 Token 状态执行相应策略
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
    
    def _micro_compact(self) -> CompactResult:
        """
        微观压缩: 清理旧 tool 结果
        
        - 保留最近 3 个 tool_result
        - 将旧的替换为 "[cleared]"
        """
        pass
    
    def _light_compact(self) -> CompactResult:
        """
        轻度压缩: 归档旧消息，保留摘要
        
        - 归档 50% 的旧消息
        - 生成摘要
        - 创建 compact_boundary
        """
        pass
    
    def _aggressive_compact(self) -> CompactResult:
        """
        积极压缩: 大幅减少上下文
        
        - 只保留最近 5 轮对话
        - 深度摘要
        """
        pass
    
    def _emergency_compact(self) -> CompactResult:
        """
        紧急压缩: 极限保活
        
        - 只保留 system + 最近用户消息
        - 或者抛出 ContextWindowExceededError
        """
        pass


@dataclass
class CompactResult:
    """压缩结果"""
    success: bool
    before_tokens: int
    after_tokens: int
    archived_count: int
    preserved_count: int
    summary: str
```

### 3.6 Session 管理器

```python
# src/bourbon/session/manager.py
"""会话管理器 - 对外接口"""

from pathlib import Path
from uuid import UUID, uuid4

from .chain import MessageChain
from .context import CompactStrategy, TokenTracker
from .storage import TranscriptStore
from .types import SessionMetadata, TranscriptMessage


class Session:
    """
    会话对象
    
    封装了一个完整会话的所有组件:
    - 元数据
    - 消息链
    - 存储
    """
    
    def __init__(
        self,
        metadata: SessionMetadata,
        chain: MessageChain,
        store: TranscriptStore,
    ):
        self.metadata = metadata
        self.chain = chain
        self.store = store
        self.token_tracker = TokenTracker()
        self._dirty = False  # 是否有未保存的变更
    
    def add_message(self, message: TranscriptMessage) -> None:
        """添加消息"""
        message.session_id = self.metadata.uuid
        self.chain.append(message)
        self.metadata.message_count += 1
        self._dirty = True
    
    def get_messages_for_llm(self) -> list[dict]:
        """获取给 LLM 的消息列表"""
        return self.chain.get_llm_messages()
    
    def maybe_compact(self) -> CompactResult | None:
        """
        检查并执行压缩
        
        Returns:
            如果执行了压缩，返回结果；否则返回 None
        """
        status = self.token_tracker.check_status(self.chain)
        
        if status.level.value >= TokenLevel.WARM.value:
            strategy = CompactStrategy(self.chain, self.token_tracker)
            result = strategy.execute()
            if result.success:
                self._dirty = True
            return result
        
        return None
    
    def save(self) -> None:
        """持久化当前状态"""
        if not self._dirty:
            return
        
        # 保存消息
        messages = list(self.chain._messages.values())
        self.store.append_messages(
            project_name=Path(self.metadata.project_dir).name,
            session_id=self.metadata.uuid,
            messages=messages,
        )
        
        # 更新元数据
        self.metadata.last_activity = datetime.now()
        self.store.save_metadata(
            project_name=Path(self.metadata.project_dir).name,
            metadata=self.metadata,
        )
        
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
    
    def __init__(self, storage_dir: Path = None, project_dir: Path = None):
        if storage_dir is None:
            storage_dir = Path("~/.bourbon/sessions").expanduser()
        
        self.storage_dir = storage_dir
        self.project_dir = project_dir or Path.cwd()
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
        session = Session(metadata, chain, self.store)
        
        self._current_session = session
        return session
    
    def load_session(self, session_id: UUID) -> Session:
        """加载现有会话"""
        project_name = self.project_dir.name
        metadata, messages = self.store.load_session(project_name, session_id)
        
        # 重建消息链
        chain = MessageChain()
        for msg in messages:
            chain._messages[msg.uuid] = msg
        
        # 找到叶子节点
        if messages:
            # 按时间排序，最后一个是最新的
            sorted_msgs = sorted(messages, key=lambda m: m.timestamp)
            chain._leaf_uuid = sorted_msgs[-1].uuid
            chain._root_uuid = sorted_msgs[0].uuid
        
        session = Session(metadata, chain, self.store)
        self._current_session = session
        return session
    
    def get_latest_session(self) -> Session | None:
        """获取最近的活动会话"""
        sessions = self.store.list_sessions(self.project_dir.name)
        if not sessions:
            return None
        
        # 返回最新的非 sidechain 会话
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
```

### 3.7 与现有 Agent 集成

```python
# src/bourbon/agent.py - 集成后的 Agent

class Agent:
    """集成新 Session 系统的 Agent"""
    
    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        session_id: UUID | None = None,  # 用于恢复会话
        ...
    ):
        self.config = config
        self.workdir = workdir or Path.cwd()
        
        # 初始化 Session 管理器
        self.session_manager = SessionManager(
            storage_dir=Path("~/.bourbon/sessions"),
            project_dir=self.workdir,
        )
        
        # 加载或创建会话
        if session_id:
            self.session = self.session_manager.load_session(session_id)
        else:
            self.session = self.session_manager.get_latest_session()
            if not self.session:
                self.session = self.session_manager.create_session()
        
        # 其他组件保持不变
        self.todos = TodoManager()
        self.skills = SkillManager(self.workdir)
        self.llm = create_client(config)
        ...
    
    def step(self, user_input: str) -> str:
        """处理用户输入"""
        # 创建用户消息
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=user_input)],
        )
        self.session.add_message(user_msg)
        
        # 检查并执行压缩
        compact_result = self.session.maybe_compact()
        if compact_result:
            # 通知用户（可选）
            pass
        
        # 获取 LLM 消息
        messages = self.session.get_messages_for_llm()
        
        # 调用 LLM
        response = self.llm.chat(
            messages=messages,
            tools=definitions(),
            system=self.system_prompt,
        )
        
        # 创建助手消息
        assistant_msg = self._convert_llm_response_to_message(response)
        self.session.add_message(assistant_msg)
        
        # 持久化
        self.session.save()
        
        # 处理 tool calls
        ...
    
    def _run_conversation_loop_stream(self, on_text_chunk) -> str:
        """流式对话循环"""
        messages = self.session.get_messages_for_llm()
        
        for event in self.llm.chat_stream(messages, ...):
            if event["type"] == "text":
                on_text_chunk(event["text"])
            elif event["type"] == "tool_use":
                # 收集 tool_use
                pass
            elif event["type"] == "usage":
                # 记录 token 使用
                pass
        
        # 构建助手消息并添加到会话
        ...
```

---

## 4. 存储布局

```
~/.bourbon/sessions/
└── <project-name>/
    ├── <session-id-1>.jsonl              # 主会话消息
    ├── <session-id-1>.meta.json          # 会话元数据
    ├── <session-id-2>.jsonl
    ├── <session-id-2>.meta.json
    └── sidechains/
        └── <agent-id-1>.jsonl            # 子代理消息
```

### 4.1 JSONL 格式示例

```jsonl
{"uuid": "550e8400-e29b-41d4-a716-446655440000", "session_id": "550e8400-e29b-41d4-a716-446655440001", "parent_uuid": null, "logical_parent_uuid": null, "role": "user", "content": [{"type": "text", "text": "Hello"}], "timestamp": "2026-04-03T10:00:00", "is_compact_boundary": false, ...}
{"uuid": "550e8400-e29b-41d4-a716-446655440002", "session_id": "550e8400-e29b-41d4-a716-446655440001", "parent_uuid": "550e8400-e29b-41d4-a716-446655440000", "logical_parent_uuid": null, "role": "assistant", "content": [{"type": "text", "text": "Hi!"}], "timestamp": "2026-04-03T10:00:01", "is_compact_boundary": false, ...}
{"uuid": "550e8400-e29b-41d4-a716-446655440003", "session_id": "550e8400-e29b-41d4-a716-446655440001", "parent_uuid": null, "logical_parent_uuid": "550e8400-e29b-41d4-a716-446655440002", "role": "system", "content": [{"type": "text", "text": "[Context compressed...]"}], "timestamp": "2026-04-03T10:05:00", "is_compact_boundary": true, "compact_metadata": {"trigger": "auto_threshold", "pre_compact_token_count": 95000, "post_compact_token_count": 15000, ...}, ...}
```

### 4.2 元数据格式

```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440001",
  "parent_uuid": null,
  "project_dir": "/Users/whf/github_project/build-my-agent",
  "created_at": "2026-04-03T10:00:00",
  "last_activity": "2026-04-03T11:30:00",
  "message_count": 42,
  "total_tokens_used": 150000,
  "is_active": true,
  "description": "Session about refactoring session system"
}
```

---

## 5. CLI 集成

```bash
# 列出可恢复的会话
bourbon sessions list

# 恢复特定会话
bourbon --resume <session-id>

# 继续最近的会话
bourbon --continue

# 创建新会话（不继承）
bourbon --new-session

# 设置会话描述
bourbon session describe "Working on compression strategy"

# 查看会话统计
bourbon session stats

# 手动压缩
bourbon session compact

# 导出会话
bourbon session export <session-id> > session.jsonl
```

---

## 6. 迁移策略

### 6.1 渐进式迁移

```python
# 阶段 1: 添加 Session 支持（向后兼容）
# - Agent 可选使用 Session
# - 不破坏现有代码

# 阶段 2: 默认启用 Session
# - 默认创建/加载 Session
# - 提供 --no-session 选项

# 阶段 3: 移除旧代码
# - 删除简单的 messages 列表
# - 完全依赖 Session 系统
```

### 6.2 向后兼容层

```python
class Agent:
    @property
    def messages(self) -> list[dict]:
        """向后兼容：返回 messages 列表"""
        if self.session:
            return self.session.get_messages_for_llm()
        return self._legacy_messages  # 旧代码路径
    
    @messages.setter
    def messages(self, value: list[dict]):
        """向后兼容：设置 messages"""
        if not self.session:
            self._legacy_messages = value
```

---

## 7. 测试策略

### 7.1 单元测试

```python
# tests/session/test_chain.py
def test_build_conversation_chain():
    chain = MessageChain()
    # 添加消息
    # 验证链构建正确

def test_compact_preserves_logical_parent():
    # 验证 compact 后 logical_parent_uuid 正确

def test_token_tracker_levels():
    # 验证各级别触发条件
```

### 7.2 集成测试

```python
# tests/session/test_integration.py
def test_session_persistence():
    # 创建会话
    # 添加消息
    # 保存
    # 重新加载
    # 验证消息一致

def test_compression_flow():
    # 模拟大量消息
    # 验证压缩触发
    # 验证压缩后功能正常
```

### 7.3 压力测试

```python
def test_massive_session():
    # 1000+ 消息
    # 验证性能
    # 验证压缩正确
```

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 性能下降 | 高 | 增量持久化、异步写入、缓存 |
| 数据丢失 | 高 | 原子写入、备份机制、校验和 |
| 兼容性问题 | 中 | 渐进迁移、向后兼容层 |
| 复杂度过高 | 中 | 模块化设计、清晰接口 |
| Token 计算不准 | 中 | 多级估算、安全余量 |

---

## 9. 成功标准

- [ ] Session 可创建、加载、恢复
- [ ] 消息持久化到 JSONL
- [ ] Compression 保留逻辑关系
- [ ] Token 多级预警正常工作
- [ ] 现有测试全部通过
- [ ] 新功能测试覆盖 > 80%
- [ ] 性能无明显下降（< 10%）

---

*Spec 版本: 1.0*  
*创建日期: 2026-04-03*  
*状态: 待 Review*
