"""ContextManager - Token tracking and compact strategy.

Bridges the old ContextCompressor behavior into the new Session system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .chain import MessageChain
from .types import CompactResult, CompactTrigger


@dataclass
class TokenStatus:
    """Current token usage status."""

    estimated_tokens: int
    threshold: int
    usage_ratio: float
    should_compact: bool


class ContextManager:
    """Token tracking and compact trigger logic.

    Replaces ContextCompressor's should_compact/estimate_tokens for the Session system.
    """

    def __init__(
        self,
        chain: MessageChain,
        token_threshold: int = 100000,
        keep_tool_results: int = 3,
        compact_preserve_count: int = 3,
    ):
        self.chain = chain
        self.token_threshold = token_threshold
        self.keep_tool_results = keep_tool_results
        self.compact_preserve_count = compact_preserve_count

    def estimate_tokens(self) -> int:
        """Estimate token count from active chain.

        Rough estimate: 4 characters per token on average.
        """
        messages = self.chain.get_llm_messages()
        text = json.dumps(messages, default=str)
        return len(text) // 4

    def should_compact(self) -> bool:
        """Check if auto-compact should be triggered."""
        return self.estimate_tokens() > self.token_threshold

    def get_status(self) -> TokenStatus:
        """Get current token usage status."""
        estimated = self.estimate_tokens()
        return TokenStatus(
            estimated_tokens=estimated,
            threshold=self.token_threshold,
            usage_ratio=estimated / self.token_threshold if self.token_threshold else 0,
            should_compact=estimated > self.token_threshold,
        )

    def generate_summary(self) -> str:
        """Generate summary for compact operation.

        TODO: In full implementation, call LLM to generate a proper summary.
        For now, return basic stats.
        """
        chain = self.chain.build_active_chain()
        user_msgs = sum(1 for m in chain if m.role.value == "user")
        assistant_msgs = sum(1 for m in chain if m.role.value == "assistant")

        return (
            f"{user_msgs} user messages, "
            f"{assistant_msgs} assistant responses archived"
        )

    def microcompact(self) -> None:
        """Lightweight compression: clear old tool results in active chain.

        Keeps the most recent N tool results, clears older ones.
        """
        from .types import ToolResultBlock, TextBlock

        chain = self.chain.build_active_chain()

        # Find all messages with tool results
        tool_result_msgs = []
        for msg in chain:
            has_tool_results = any(
                isinstance(block, ToolResultBlock) for block in msg.content
            )
            if has_tool_results:
                tool_result_msgs.append(msg)

        # If we have more than keep_tool_results, clear the older ones
        if len(tool_result_msgs) > self.keep_tool_results:
            for msg in tool_result_msgs[: -self.keep_tool_results]:
                new_content = []
                for block in msg.content:
                    if isinstance(block, ToolResultBlock) and len(block.content) > 100:
                        new_content.append(
                            ToolResultBlock(
                                tool_use_id=block.tool_use_id,
                                content="[cleared]",
                                is_error=block.is_error,
                            )
                        )
                    else:
                        new_content.append(block)
                msg.content = new_content
