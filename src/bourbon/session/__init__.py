"""Bourbon Session System - structured message management."""

from .chain import MessageChain, build_conversation_from_transcript
from .context import ContextManager, TokenStatus
from .manager import Session, SessionManager
from .storage import TranscriptStore
from .types import (
    CompactMetadata,
    CompactResult,
    CompactTrigger,
    MessageContent,
    MessageRole,
    SessionMetadata,
    SessionSummary,
    TextBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
    TranscriptMessage,
)

__all__ = [
    # Types
    "CompactMetadata",
    "CompactResult",
    "CompactTrigger",
    "MessageContent",
    "MessageRole",
    "SessionMetadata",
    "SessionSummary",
    "TextBlock",
    "TokenUsage",
    "ToolResultBlock",
    "ToolUseBlock",
    "TranscriptMessage",
    # Chain
    "MessageChain",
    "build_conversation_from_transcript",
    # Context
    "ContextManager",
    "TokenStatus",
    # Storage
    "TranscriptStore",
    # Manager
    "Session",
    "SessionManager",
]
