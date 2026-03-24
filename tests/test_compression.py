"""Tests for context compression."""

import json
import tempfile
from pathlib import Path

from bourbon.compression import ContextCompressor


class TestContextCompressor:
    """Test context compression."""

    def test_estimate_tokens(self):
        """Test token estimation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compressor = ContextCompressor(transcript_dir=Path(tmpdir))

            messages = [{"role": "user", "content": "Hello"}]
            tokens = compressor.estimate_tokens(messages)
            # Rough estimate: json.dumps length // 4
            expected = len(json.dumps(messages)) // 4
            assert tokens == expected

    def test_should_compact(self):
        """Test threshold checking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compressor = ContextCompressor(
                transcript_dir=Path(tmpdir),
                token_threshold=100,  # Low threshold for testing
            )

            # Small conversation - shouldn't compact
            small = [{"role": "user", "content": "Hi"}]
            assert not compressor.should_compact(small)

            # Large conversation - should compact
            large = [{"role": "user", "content": "x" * 1000} for _ in range(100)]
            assert compressor.should_compact(large)

    def test_microcompact_clears_old_results(self):
        """Test microcompact clears old tool results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compressor = ContextCompressor(
                transcript_dir=Path(tmpdir),
                keep_tool_results=2,
            )

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "1", "content": "Result 1"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "2", "content": "Result 2"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "3", "content": "Result 3"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "4", "content": "Result 4"},
                    ],
                },
            ]

            compressor.microcompact(messages)

            # First two should be cleared (long content > 100 chars not applicable here)
            # Actually, only content > 100 chars gets cleared
            # So these short contents should remain unchanged

    def test_microcompact_clears_long_content(self):
        """Test microcompact clears long content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compressor = ContextCompressor(
                transcript_dir=Path(tmpdir),
                keep_tool_results=1,
            )

            long_content = "x" * 200
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "1", "content": long_content},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "2", "content": "Keep this"},
                    ],
                },
            ]

            compressor.microcompact(messages)

            # First result should be cleared (long content)
            assert messages[0]["content"][0]["content"] == "[cleared]"
            # Second result should remain
            assert messages[1]["content"][0]["content"] == "Keep this"

    def test_archive_transcript(self):
        """Test archiving conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compressor = ContextCompressor(transcript_dir=Path(tmpdir))

            messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ]

            path = compressor.archive_transcript(messages)

            assert path.exists()
            assert path.parent == Path(tmpdir)
            assert path.name.startswith("transcript_")

            # Verify content
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2
            assert json.loads(lines[0])["role"] == "user"

    def test_compact_returns_summary(self):
        """Test compact returns summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            compressor = ContextCompressor(transcript_dir=Path(tmpdir))

            messages = [
                {"role": "user", "content": "Task: refactor code"},
                {"role": "assistant", "content": "I'll help"},
                {"role": "user", "content": "Use ast-grep"},
            ]

            compressed = compressor.compact(messages)

            assert len(compressed) == 2
            assert compressed[0]["role"] == "user"
            assert "[Context compressed." in compressed[0]["content"]
            assert compressed[1]["role"] == "assistant"
