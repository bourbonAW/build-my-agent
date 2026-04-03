"""Tests for ContextManager."""

import pytest

from bourbon.session.chain import MessageChain
from bourbon.session.context import ContextManager
from bourbon.session.types import (
    MessageRole,
    TextBlock,
    ToolResultBlock,
    TranscriptMessage,
)


@pytest.fixture
def chain_and_context():
    chain = MessageChain()
    ctx = ContextManager(chain, token_threshold=500)
    return chain, ctx


class TestContextManager:
    def test_estimate_tokens_empty(self, chain_and_context):
        _, ctx = chain_and_context
        assert ctx.estimate_tokens() == 0

    def test_estimate_tokens_with_messages(self, chain_and_context):
        chain, ctx = chain_and_context
        chain.append(
            TranscriptMessage(
                role=MessageRole.USER, content=[TextBlock(text="Hello world")]
            )
        )
        tokens = ctx.estimate_tokens()
        assert tokens > 0

    def test_should_compact_below_threshold(self, chain_and_context):
        chain, ctx = chain_and_context
        chain.append(
            TranscriptMessage(
                role=MessageRole.USER, content=[TextBlock(text="short")]
            )
        )
        assert ctx.should_compact() is False

    def test_should_compact_above_threshold(self):
        chain = MessageChain()
        ctx = ContextManager(chain, token_threshold=10)  # Very low threshold
        chain.append(
            TranscriptMessage(
                role=MessageRole.USER,
                content=[TextBlock(text="x" * 200)],
            )
        )
        assert ctx.should_compact() is True

    def test_get_status(self, chain_and_context):
        chain, ctx = chain_and_context
        chain.append(
            TranscriptMessage(
                role=MessageRole.USER, content=[TextBlock(text="test")]
            )
        )
        status = ctx.get_status()
        assert status.threshold == 500
        assert status.estimated_tokens > 0
        assert isinstance(status.usage_ratio, float)

    def test_generate_summary(self, chain_and_context):
        chain, ctx = chain_and_context
        chain.append(
            TranscriptMessage(
                role=MessageRole.USER, content=[TextBlock(text="hi")]
            )
        )
        chain.append(
            TranscriptMessage(
                role=MessageRole.ASSISTANT, content=[TextBlock(text="hello")]
            )
        )
        summary = ctx.generate_summary()
        assert "1 user" in summary
        assert "1 assistant" in summary


class TestMicrocompact:
    def test_clears_old_tool_results(self):
        chain = MessageChain()
        ctx = ContextManager(chain, keep_tool_results=1)

        # Add 3 messages with tool results
        for i in range(3):
            chain.append(
                TranscriptMessage(
                    role=MessageRole.USER,
                    content=[
                        ToolResultBlock(
                            tool_use_id=f"t{i}",
                            content="x" * 200,  # > 100 chars
                            is_error=False,
                        )
                    ],
                )
            )

        ctx.microcompact()

        # Check: first 2 should be cleared, last 1 preserved
        active = chain.build_active_chain()
        assert active[0].content[0].content == "[cleared]"
        assert active[1].content[0].content == "[cleared]"
        assert active[2].content[0].content == "x" * 200

    def test_preserves_short_results(self):
        chain = MessageChain()
        ctx = ContextManager(chain, keep_tool_results=0)

        chain.append(
            TranscriptMessage(
                role=MessageRole.USER,
                content=[
                    ToolResultBlock(
                        tool_use_id="t1",
                        content="short",  # <= 100 chars
                        is_error=False,
                    )
                ],
            )
        )

        ctx.microcompact()
        active = chain.build_active_chain()
        assert active[0].content[0].content == "short"
