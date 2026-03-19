"""Context compression for long conversations.

Implements two-tier compression:
1. Micro-compact: Clear old tool results (keep last N)
2. Auto-compact: Summarize and archive when token threshold exceeded
"""

import json
import time
from pathlib import Path
from typing import Any


class ContextCompressor:
    """Manages context compression for agent conversations."""

    def __init__(
        self,
        transcript_dir: Path | None = None,
        token_threshold: int = 100000,
        keep_tool_results: int = 3,
    ):
        """Initialize compressor.

        Args:
            transcript_dir: Directory to store transcripts
            token_threshold: Token count to trigger auto-compact
            keep_tool_results: Number of recent tool results to keep
        """
        if transcript_dir is None:
            transcript_dir = Path.home() / ".bourbon" / "transcripts"
        self.transcript_dir = transcript_dir
        self.token_threshold = token_threshold
        self.keep_tool_results = keep_tool_results

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Estimate token count from messages.

        Rough estimate: 4 characters per token on average.
        """
        text = json.dumps(messages, default=str)
        return len(text) // 4

    def microcompact(self, messages: list[dict]) -> None:
        """Lightweight compression: clear old tool results.

        Keeps the most recent N tool results, clears older ones.
        Modifies messages in place.
        """
        # Find all tool_result entries
        tool_results = []
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        tool_results.append(part)

        # If we have more than keep_tool_results, clear the older ones
        if len(tool_results) > self.keep_tool_results:
            for part in tool_results[:-self.keep_tool_results]:
                if isinstance(part.get("content"), str) and len(part["content"]) > 100:
                    part["content"] = "[cleared]"

    def should_compact(self, messages: list[dict]) -> bool:
        """Check if auto-compact should be triggered."""
        return self.estimate_tokens(messages) > self.token_threshold

    def archive_transcript(self, messages: list[dict]) -> Path:
        """Save full conversation to transcript file.

        Returns:
            Path to archived transcript
        """
        self.transcript_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        transcript_path = self.transcript_dir / f"transcript_{timestamp}.jsonl"

        with open(transcript_path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str) + "\n")

        return transcript_path

    def compact(self, messages: list[dict]) -> list[dict]:
        """Perform full context compression.

        1. Archive current conversation
        2. Generate summary (placeholder - would call LLM in real impl)
        3. Replace with summary + acknowledgement

        Args:
            messages: Full conversation history

        Returns:
            Compressed conversation (summary + recent context)
        """
        # Archive full conversation
        transcript_path = self.archive_transcript(messages)

        # In real implementation, this would call LLM to summarize
        # For now, create a simple summary
        summary = self._generate_summary(messages)

        # Return compressed context
        return [
            {
                "role": "user",
                "content": f"[Context compressed. Transcript: {transcript_path}]\n\nConversation summary:\n{summary}",
            },
            {
                "role": "assistant",
                "content": "Understood. Continuing with summary context.",
            },
        ]

    def _generate_summary(self, messages: list[dict]) -> str:
        """Generate summary of conversation.

        TODO: In real implementation, this should call an LLM to generate
        a proper summary. For now, just return basic stats.
        """
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        tool_calls = sum(
            1
            for m in messages
            if m.get("role") == "assistant"
            and isinstance(m.get("content"), list)
            and any(p.get("type") == "tool_use" for p in m["content"])
        )

        return (
            f"- {user_msgs} user messages\n"
            f"- {assistant_msgs} assistant responses\n"
            f"- {tool_calls} tool invocations\n"
            f"Full details in transcript file."
        )
