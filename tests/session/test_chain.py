"""Tests for MessageChain."""

import copy

import pytest
from uuid import uuid4

from bourbon.session.chain import MessageChain, build_conversation_from_transcript
from bourbon.session.types import (
    TranscriptMessage,
    MessageRole,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


class TestMessageChain:
    """MessageChain tests."""

    def test_empty_chain(self):
        chain = MessageChain()
        assert chain.message_count == 0
        assert chain.build_active_chain() == []

    def test_append_builds_parent_links(self):
        chain = MessageChain()

        msg1 = TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
        chain.append(msg1)

        msg2 = TranscriptMessage(
            role=MessageRole.ASSISTANT, content=[TextBlock(text="2")]
        )
        chain.append(msg2)

        assert msg2.parent_uuid == msg1.uuid
        assert chain.leaf_uuid == msg2.uuid

    def test_build_active_chain_order(self):
        chain = MessageChain()

        msgs = [
            TranscriptMessage(
                role=MessageRole.USER, content=[TextBlock(text=str(i))]
            )
            for i in range(3)
        ]
        for msg in msgs:
            chain.append(msg)

        active = chain.build_active_chain()
        assert len(active) == 3
        assert active[0] == msgs[0]
        assert active[1] == msgs[1]
        assert active[2] == msgs[2]

    def test_compact_removes_from_memory(self):
        chain = MessageChain()

        msgs = [
            TranscriptMessage(
                role=MessageRole.USER, content=[TextBlock(text=str(i))]
            )
            for i in range(5)
        ]
        for msg in msgs:
            chain.append(msg)

        result = chain.compact(preserve_count=2)

        assert result.success is True
        assert result.archived_count == 3
        assert result.preserved_count == 2
        assert chain.message_count == 3  # boundary + 2 preserved

        # Verify old messages removed from memory
        assert msgs[0].uuid not in chain._messages
        assert msgs[1].uuid not in chain._messages
        assert msgs[2].uuid not in chain._messages

    def test_compact_boundary_not_in_llm_messages(self):
        chain = MessageChain()

        for i in range(5):
            chain.append(
                TranscriptMessage(
                    role=MessageRole.USER,
                    content=[TextBlock(text=str(i))],
                )
            )

        chain.compact(preserve_count=2)

        llm_msgs = chain.get_llm_messages()
        assert len(llm_msgs) == 2  # Only preserved messages

    def test_logical_parent_not_used_in_active_chain(self):
        chain = MessageChain()

        msg1 = TranscriptMessage(
            role=MessageRole.USER, content=[TextBlock(text="1")]
        )
        chain.append(msg1)

        msg2 = TranscriptMessage(
            role=MessageRole.ASSISTANT, content=[TextBlock(text="2")]
        )
        chain.append(msg2)

        # Set wrong logical_parent
        msg2.logical_parent_uuid = uuid4()

        # Active chain should still be correct
        active = chain.build_active_chain()
        assert len(active) == 2
        assert active[1] == msg2

    def test_clear_empties_chain(self):
        chain = MessageChain()

        for i in range(3):
            chain.append(
                TranscriptMessage(
                    role=MessageRole.USER,
                    content=[TextBlock(text=str(i))],
                )
            )

        chain.clear()

        assert chain.message_count == 0
        assert chain.leaf_uuid is None

    def test_compact_insufficient_messages(self):
        chain = MessageChain()
        chain.append(
            TranscriptMessage(role=MessageRole.USER, content=[TextBlock(text="1")])
        )
        result = chain.compact(preserve_count=3)
        assert result.success is False
        assert "insufficient_messages" in result.reason


class TestCompactManifestRoundTrip:
    """Compact manifest persistence and rebuild critical path tests.

    Verifies core invariant: compact() parent_uuid_overrides must be persisted
    via manifest for rebuild_from_transcript() to correctly rebuild the chain
    after restart.

    Key modeling constraints:
    - transcript is append-only, messages written to disk before compact retain original parent_uuid
    - tests use copy.deepcopy to freeze "disk state" snapshots, avoiding pollution by compact() in-memory mutations
    - after compact, boundary_msg is appended to transcript (maybe_compact behavior)
    """

    def test_compact_manifest_survives_restart(self):
        """
        Verify complete round-trip: compact -> save manifest -> rebuild_from_transcript.

        Scenario:
        1. Chain has 5 messages, each append simulates persistence (deepcopy freezes disk state)
        2. compact(preserve_count=2) archives first 3, preserves last 2
        3. boundary_msg appended to disk_transcript (simulates maybe_compact behavior)
        4. Save parent_uuid_overrides to manifest
        5. Simulate restart: rebuild with disk_transcript (with boundary) + manifest
        6. Rebuilt chain should only contain boundary + 2 preserved messages (3 total)
        """
        chain = MessageChain()
        msgs = []
        disk_transcript = []  # Simulates append-only disk: compact-time writes original parent_uuid

        for i in range(5):
            msg = TranscriptMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=[TextBlock(text=f"message {i}")],
            )
            chain.append(msg)
            msgs.append(msg)
            # Simulate append_to_transcript: freeze current parent_uuid (deepcopy)
            disk_transcript.append(copy.deepcopy(msg))

        assert chain.message_count == 5

        # Step 1: compact, preserve last 2
        result = chain.compact(preserve_count=2, summary="archived messages 0-2")

        assert result.parent_uuid_overrides, "compact must produce parent_uuid_overrides"

        # Post-compact in-memory chain: 1 boundary + 2 preserved = 3
        active_after_compact = chain.build_active_chain()
        assert len(active_after_compact) == 3, (
            f"should have boundary + 2 preserved, got {len(active_after_compact)}"
        )
        assert (
            active_after_compact[0].is_compact_boundary is True
        ), "first should be compact boundary"

        # Step 2: simulate maybe_compact appending boundary to transcript
        boundary_msg = chain.get(result.boundary_uuid)
        disk_transcript.append(boundary_msg)

        # Step 3: persist manifest
        saved_overrides = dict(result.parent_uuid_overrides)

        # Step 4: simulate restart - use disk_transcript (with boundary, 5 original messages
        # have original parent_uuid) + manifest overrides to rebuild
        new_chain = MessageChain()
        new_chain.rebuild_from_transcript(
            disk_transcript, parent_uuid_overrides=saved_overrides
        )

        # Verify rebuilt chain matches post-compact state: boundary + 2 preserved = 3
        rebuilt_active = new_chain.build_active_chain()
        assert len(rebuilt_active) == 3, (
            f"rebuilt should have boundary + 2 preserved, got {len(rebuilt_active)}"
        )
        assert (
            rebuilt_active[0].is_compact_boundary is True
        ), "rebuilt first should be compact boundary"
        assert (
            rebuilt_active[-1].uuid == msgs[-1].uuid
        ), "leaf should be last original message"
        assert (
            rebuilt_active[-2].uuid == msgs[-2].uuid
        ), "second-to-last should be msgs[-2]"

    def test_rebuild_without_manifest_includes_archived(self):
        """
        Verify that without manifest overrides, rebuild incorrectly traverses all archived messages.
        This test proves the necessity of the manifest mechanism:
        - With overrides: first_preserved.parent_uuid -> boundary (traverses only 3)
        - Without overrides: first_preserved.parent_uuid -> msgs[2] (traverses all 5)
        """
        chain = MessageChain()
        msgs = []
        disk_transcript = []

        for i in range(5):
            msg = TranscriptMessage(
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=[TextBlock(text=f"message {i}")],
            )
            chain.append(msg)
            msgs.append(msg)
            disk_transcript.append(copy.deepcopy(msg))  # Freeze disk state

        result = chain.compact(preserve_count=2, summary="archived")
        assert result.parent_uuid_overrides

        # Append boundary to disk transcript
        boundary_msg = chain.get(result.boundary_uuid)
        disk_transcript.append(boundary_msg)

        # Without parent_uuid_overrides: disk's first_preserved (msgs[3] deepcopy)
        # has parent_uuid still pointing to msgs[2].uuid (original value)
        # Traversal: leaf(msgs[4]) -> msgs[3] -> msgs[2] -> msgs[1] -> msgs[0]
        # boundary unreachable (no message points to it), doesn't appear in active chain
        new_chain = MessageChain()
        new_chain.rebuild_from_transcript(disk_transcript)  # No overrides

        rebuilt_active = new_chain.build_active_chain()
        assert len(rebuilt_active) == 5, (
            f"without manifest should incorrectly include all 5 archived, got {len(rebuilt_active)}"
        )
