"""MessageChain - Active conversation chain (in-memory only)"""

from collections import OrderedDict
from uuid import UUID

from .types import (
    CompactMetadata,
    CompactResult,
    CompactTrigger,
    MessageRole,
    TextBlock,
    TranscriptMessage,
)


class MessageChain:
    """
    Active Message Chain - mutable in-memory chain.

    Responsibilities:
    1. Maintain currently active messages (for LLM conversation)
    2. Build active chain using parent_uuid (logical_parent_uuid NOT involved!)
    3. Execute compact (remove old messages from memory)

    Note: This is NOT responsible for persistence!
    """

    def __init__(self):
        self._messages: OrderedDict[UUID, TranscriptMessage] = OrderedDict()
        self._leaf_uuid: UUID | None = None
        self._root_uuid: UUID | None = None

    @property
    def leaf_uuid(self) -> UUID | None:
        return self._leaf_uuid

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def append(self, message: TranscriptMessage) -> None:
        """
        Add message to active chain.

        Automatically sets parent_uuid to current leaf.

        I4 note: This method directly mutates the passed message.parent_uuid!
        Caller should be aware that append() takes ownership of the object.
        If caller created a message with explicit parent_uuid (e.g. during rebuild),
        do NOT call append() - operate on self._messages directly.
        """
        if self._leaf_uuid:
            message.parent_uuid = self._leaf_uuid
        else:
            self._root_uuid = message.uuid

        self._messages[message.uuid] = message
        self._leaf_uuid = message.uuid

    def get(self, uuid: UUID) -> TranscriptMessage | None:
        return self._messages.get(uuid)

    def build_active_chain(self) -> list[TranscriptMessage]:
        """
        Build active conversation chain - uses parent_uuid ONLY!

        CRITICAL: logical_parent_uuid does NOT participate in chain construction!

        Returns:
            Message list from root to leaf.
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

            # CRITICAL: only use parent_uuid!
            current_uuid = message.parent_uuid

        chain.reverse()
        return chain

    def get_llm_messages(self) -> list[dict]:
        """
        Get message list for LLM.

        Filters:
        - compact_boundary messages not sent to LLM
        - sidechain messages (reserved, not implemented)
        """
        chain = self.build_active_chain()
        llm_messages = []

        for msg in chain:
            if msg.is_compact_boundary:
                continue
            if msg.is_sidechain:
                continue
            llm_messages.append(msg.to_llm_format())

        return llm_messages

    def compact(
        self,
        preserve_count: int = 3,
        summary: str = "",
        trigger: CompactTrigger = CompactTrigger.AUTO_THRESHOLD,
    ) -> CompactResult:
        """
        Compact active chain.

        Operations:
        1. Preserve last preserve_count messages
        2. Remove old messages from memory chain (transcript still retains them)
        3. Create compact_boundary message
        4. Update parent_uuid

        Args:
            trigger: Trigger reason (MANUAL, AUTO_THRESHOLD, AUTO_EMERGENCY)

        Returns:
            CompactResult
        """
        chain = self.build_active_chain()

        if len(chain) <= preserve_count:
            return CompactResult(
                success=False,
                reason=f"insufficient_messages: {len(chain)} <= {preserve_count}",
            )

        to_archive = chain[:-preserve_count]
        to_preserve = chain[-preserve_count:]

        first_archived = to_archive[0]
        last_archived = to_archive[-1]
        first_preserved = to_preserve[0]

        # Create compact_boundary message
        boundary = TranscriptMessage(
            role=MessageRole.SYSTEM,
            content=[TextBlock(text=f"[Context compressed: {summary}]")],
            is_compact_boundary=True,
            compact_metadata=CompactMetadata(
                trigger=trigger,
                pre_compact_token_count=len(to_archive),
                post_compact_token_count=len(to_preserve),
                first_archived_uuid=first_archived.uuid,
                last_archived_uuid=last_archived.uuid,
                summary=summary,
            ),
        )

        # Remove archived messages from memory
        for msg in to_archive:
            del self._messages[msg.uuid]

        # boundary's parent is None (compact boundary, disconnects from archived messages)
        boundary.parent_uuid = None
        # logical_parent_uuid for debug only (not used in chain construction)
        boundary.logical_parent_uuid = last_archived.uuid

        self._messages[boundary.uuid] = boundary

        # First preserved message's parent points to boundary
        first_preserved.parent_uuid = boundary.uuid
        # logical_parent_uuid preserves original connection (debug only)
        first_preserved.logical_parent_uuid = last_archived.uuid

        # C1 fix: unconditionally update _leaf_uuid and _root_uuid
        self._leaf_uuid = to_preserve[-1].uuid
        self._root_uuid = boundary.uuid

        # Finding 1 fix: record parent_uuid changes for caller to persist to compact manifest
        parent_uuid_overrides: dict[str, str | None] = {
            str(boundary.uuid): None,  # boundary.parent_uuid = None
            str(first_preserved.uuid): str(boundary.uuid),  # first_preserved -> boundary
        }

        return CompactResult(
            success=True,
            archived_count=len(to_archive),
            preserved_count=len(to_preserve),
            boundary_uuid=boundary.uuid,
            parent_uuid_overrides=parent_uuid_overrides,
        )

    def clear(self) -> None:
        """
        Clear active chain.

        Note: Only clears memory, transcript is unaffected.
        """
        self._messages.clear()
        self._leaf_uuid = None
        self._root_uuid = None

    def rebuild_from_transcript(
        self,
        transcript: list[TranscriptMessage],
        resume_from: UUID | None = None,
        parent_uuid_overrides: dict[str, str | None] | None = None,
    ) -> None:
        """
        Rebuild active chain from transcript.

        Finding 1 fix: Apply compact manifest parent_uuid overrides BEFORE traversal,
        ensuring post-restart chain structure matches post-compact memory state.

        Args:
            transcript: Complete message history (from JSONL)
            resume_from: Resume from specified message, None auto-selects latest non-boundary
            parent_uuid_overrides: parent_uuid overrides from compact manifest
                                   { str(msg_uuid): str(new_parent_uuid) | None }
        """
        self.clear()

        if not transcript:
            return

        # Build UUID -> Message mapping
        msg_map = {msg.uuid: msg for msg in transcript}

        # Finding 1 fix: apply overrides BEFORE traversal
        if parent_uuid_overrides:
            for uuid_str, new_parent_str in parent_uuid_overrides.items():
                try:
                    msg_uuid = UUID(uuid_str)
                    if msg_uuid in msg_map:
                        msg_map[msg_uuid].parent_uuid = (
                            UUID(new_parent_str) if new_parent_str else None
                        )
                except ValueError:
                    continue  # Ignore malformed UUIDs

        # Determine resume point
        if resume_from is None:
            for msg in reversed(transcript):
                if not msg.is_compact_boundary:
                    resume_from = msg.uuid
                    break

        if resume_from is None or resume_from not in msg_map:
            return

        # Backtrack from resume point to build chain (parent_uuid only)
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

        chain.reverse()
        for msg in chain:
            self._messages[msg.uuid] = msg

        if chain:
            self._root_uuid = chain[0].uuid
            self._leaf_uuid = chain[-1].uuid


# Helper for compatibility
def build_conversation_from_transcript(
    transcript: list[TranscriptMessage],
) -> list[TranscriptMessage]:
    """
    Build conversation chain from complete transcript (for debugging).

    Note: This may include compacted messages, for debug display only!
    """
    if not transcript:
        return []

    # Find latest non-boundary message
    start_uuid = None
    for msg in reversed(transcript):
        if not msg.is_compact_boundary:
            start_uuid = msg.uuid
            break

    if not start_uuid:
        return []

    msg_map = {msg.uuid: msg for msg in transcript}

    # Use logical_parent_uuid to build logical chain (display only)
    chain = []
    seen = set()
    current = start_uuid

    while current and current not in seen:
        seen.add(current)
        msg = msg_map.get(current)
        if not msg:
            break
        chain.append(msg)
        # Use logical_parent_uuid for display
        current = msg.logical_parent_uuid or msg.parent_uuid

    chain.reverse()
    return chain
