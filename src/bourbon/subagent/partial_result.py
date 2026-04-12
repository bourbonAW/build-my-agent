"""Partial result extraction from incomplete subagent transcripts."""

from __future__ import annotations

from bourbon.session.types import MessageRole, TextBlock, TranscriptMessage

MAX_PARTIAL_RESULT_CHARS = 2000


def extract_partial_result(messages: list[TranscriptMessage]) -> str:
    """Extract the latest assistant text content from a transcript."""
    for message in reversed(messages):
        if message.role != MessageRole.ASSISTANT:
            continue

        text_parts = [
            block.text.strip()
            for block in message.content
            if isinstance(block, TextBlock) and block.text.strip()
        ]
        if not text_parts:
            continue

        result = "\n".join(text_parts)
        if len(result) > MAX_PARTIAL_RESULT_CHARS:
            return f"{result[:MAX_PARTIAL_RESULT_CHARS]}\n... (truncated)"
        return result

    return "(No partial result available)"
