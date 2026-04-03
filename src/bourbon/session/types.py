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
    Message structure - key design:

    1. parent_uuid: the only edge used to build the active chain
    2. logical_parent_uuid: debug-only, NOT used in chain construction
    3. source_tool_uuid: tool_result -> the assistant message that generated it
    """

    uuid: UUID = field(default_factory=uuid4)
    session_id: UUID = field(default_factory=uuid4)

    # Chain structure
    parent_uuid: UUID | None = None
    logical_parent_uuid: UUID | None = None  # Debug only!

    # Content
    role: MessageRole = MessageRole.USER
    content: list[MessageContent] = field(default_factory=list)

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    usage: TokenUsage | None = None

    # Tool association (CRITICAL)
    source_tool_uuid: UUID | None = None

    # Sidechain (reserved, not implemented this phase)
    is_sidechain: bool = False
    agent_id: str | None = None

    # Compact
    is_compact_boundary: bool = False
    compact_metadata: CompactMetadata | None = None

    def to_llm_format(self) -> dict:
        """Convert to LLM API format."""
        content_list = []
        for block in self.content:
            block_dict: dict = {"type": block.type}
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
    """Compact operation result."""

    success: bool
    archived_count: int = 0
    preserved_count: int = 0
    boundary_uuid: UUID | None = None
    reason: str = ""
    # Finding 1 fix: compact modified in-memory parent_uuid, caller must persist these changes
    # key: str(uuid), value: str(new_parent_uuid) | None
    parent_uuid_overrides: dict[str, str | None] = field(default_factory=dict)
