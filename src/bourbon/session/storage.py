"""TranscriptStore - Two-layer persistence model.

Layer 1: Transcript (append-only JSONL) - complete history, never modified
Layer 2: Session state (in-memory) - active chain, mutable via compact/clear

Additionally:
- Compact manifest (overwriteable JSON) - records parent_uuid overrides from compact
- Session metadata (overwriteable JSON) - session-level metadata
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from .types import (
    CompactMetadata,
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


def _message_to_dict(msg: TranscriptMessage) -> dict:
    """Serialize TranscriptMessage to dict for JSONL storage."""
    content_list = []
    for block in msg.content:
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

    result: dict = {
        "uuid": str(msg.uuid),
        "session_id": str(msg.session_id),
        "role": msg.role.value,
        "content": content_list,
        "timestamp": msg.timestamp.isoformat(),
        "parent_uuid": str(msg.parent_uuid) if msg.parent_uuid else None,
        "logical_parent_uuid": (
            str(msg.logical_parent_uuid) if msg.logical_parent_uuid else None
        ),
        "source_tool_uuid": (
            str(msg.source_tool_uuid) if msg.source_tool_uuid else None
        ),
        "is_sidechain": msg.is_sidechain,
        "agent_id": msg.agent_id,
        "is_compact_boundary": msg.is_compact_boundary,
    }

    if msg.usage:
        result["usage"] = {
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "total_tokens": msg.usage.total_tokens,
        }

    if msg.compact_metadata:
        result["compact_metadata"] = {
            "trigger": msg.compact_metadata.trigger.value,
            "pre_compact_token_count": msg.compact_metadata.pre_compact_token_count,
            "post_compact_token_count": msg.compact_metadata.post_compact_token_count,
            "first_archived_uuid": str(msg.compact_metadata.first_archived_uuid),
            "last_archived_uuid": str(msg.compact_metadata.last_archived_uuid),
            "summary": msg.compact_metadata.summary,
            "archived_at": msg.compact_metadata.archived_at.isoformat(),
        }

    return result


def _parse_content_block(block_dict: dict) -> MessageContent:
    """Parse a content block dict into the appropriate dataclass."""
    block_type = block_dict.get("type", "text")
    if block_type == "text":
        return TextBlock(text=block_dict.get("text", ""))
    elif block_type == "tool_use":
        return ToolUseBlock(
            id=block_dict.get("id", ""),
            name=block_dict.get("name", ""),
            input=block_dict.get("input", {}),
        )
    elif block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=block_dict.get("tool_use_id", ""),
            content=block_dict.get("content", ""),
            is_error=block_dict.get("is_error", False),
        )
    return TextBlock(text=str(block_dict))


def _dict_to_message(data: dict) -> TranscriptMessage:
    """Deserialize dict from JSONL to TranscriptMessage."""
    content = [_parse_content_block(b) for b in data.get("content", [])]

    usage = None
    if "usage" in data:
        u = data["usage"]
        usage = TokenUsage(
            input_tokens=u.get("input_tokens", 0),
            output_tokens=u.get("output_tokens", 0),
            total_tokens=u.get("total_tokens", 0),
        )

    compact_metadata = None
    if "compact_metadata" in data:
        cm = data["compact_metadata"]
        compact_metadata = CompactMetadata(
            trigger=CompactTrigger(cm["trigger"]),
            pre_compact_token_count=cm["pre_compact_token_count"],
            post_compact_token_count=cm["post_compact_token_count"],
            first_archived_uuid=UUID(cm["first_archived_uuid"]),
            last_archived_uuid=UUID(cm["last_archived_uuid"]),
            summary=cm.get("summary", ""),
            archived_at=datetime.fromisoformat(cm["archived_at"]),
        )

    return TranscriptMessage(
        uuid=UUID(data["uuid"]),
        session_id=UUID(data["session_id"]),
        parent_uuid=UUID(data["parent_uuid"]) if data.get("parent_uuid") else None,
        logical_parent_uuid=(
            UUID(data["logical_parent_uuid"])
            if data.get("logical_parent_uuid")
            else None
        ),
        role=MessageRole(data["role"]),
        content=content,
        timestamp=datetime.fromisoformat(data["timestamp"]),
        usage=usage,
        source_tool_uuid=(
            UUID(data["source_tool_uuid"]) if data.get("source_tool_uuid") else None
        ),
        is_sidechain=data.get("is_sidechain", False),
        agent_id=data.get("agent_id"),
        is_compact_boundary=data.get("is_compact_boundary", False),
        compact_metadata=compact_metadata,
    )


class TranscriptStore:
    """Two-layer persistence: append-only transcript + overwriteable compact manifest.

    Directory layout:
        {base_dir}/{project_name}/{session_id}.jsonl       - transcript (append-only)
        {base_dir}/{project_name}/{session_id}.meta.json   - metadata (overwriteable)
        {base_dir}/{project_name}/{session_id}.compact.json - compact manifest (overwriteable)
    """

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def _session_dir(self, project_name: str) -> Path:
        return self.base_dir / project_name

    def _transcript_path(self, project_name: str, session_id: UUID) -> Path:
        return self._session_dir(project_name) / f"{session_id}.jsonl"

    def _metadata_path(self, project_name: str, session_id: UUID) -> Path:
        return self._session_dir(project_name) / f"{session_id}.meta.json"

    def _compact_manifest_path(self, project_name: str, session_id: UUID) -> Path:
        return self._session_dir(project_name) / f"{session_id}.compact.json"

    def append_to_transcript(
        self,
        project_name: str,
        session_id: UUID,
        messages: list[TranscriptMessage],
    ) -> None:
        """Append messages to transcript. Append-only, never modify existing lines."""
        path = self._transcript_path(project_name, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a") as f:
            for msg in messages:
                f.write(json.dumps(_message_to_dict(msg), ensure_ascii=False) + "\n")

    def load_transcript(
        self, project_name: str, session_id: UUID
    ) -> list[TranscriptMessage]:
        """Load complete transcript history."""
        path = self._transcript_path(project_name, session_id)
        if not path.exists():
            return []

        messages = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    messages.append(_dict_to_message(data))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue  # Skip malformed lines

        return messages

    def save_metadata(
        self, project_name: str, session_id: UUID, metadata: SessionMetadata
    ) -> None:
        """Save/update session metadata."""
        path = self._metadata_path(project_name, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "uuid": str(metadata.uuid),
            "parent_uuid": str(metadata.parent_uuid) if metadata.parent_uuid else None,
            "project_dir": metadata.project_dir,
            "created_at": metadata.created_at.isoformat(),
            "last_activity": metadata.last_activity.isoformat(),
            "message_count": metadata.message_count,
            "total_tokens_used": metadata.total_tokens_used,
            "is_active": metadata.is_active,
            "description": metadata.description,
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_metadata(
        self, project_name: str, session_id: UUID
    ) -> SessionMetadata | None:
        """Load session metadata."""
        path = self._metadata_path(project_name, session_id)
        if not path.exists():
            return None

        try:
            with open(path) as f:
                data = json.load(f)

            return SessionMetadata(
                uuid=UUID(data["uuid"]),
                parent_uuid=(
                    UUID(data["parent_uuid"]) if data.get("parent_uuid") else None
                ),
                project_dir=data["project_dir"],
                created_at=datetime.fromisoformat(data["created_at"]),
                last_activity=datetime.fromisoformat(data["last_activity"]),
                message_count=data.get("message_count", 0),
                total_tokens_used=data.get("total_tokens_used", 0),
                is_active=data.get("is_active", True),
                description=data.get("description", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def save_compact_manifest(
        self,
        project_name: str,
        session_id: UUID,
        overrides: dict[str, str | None],
    ) -> None:
        """
        Persist compact parent_uuid overrides. Overwrites previous manifest.

        File: {base_dir}/{project_name}/{session_id}.compact.json
        Format: { "overrides": { "uuid_str": "parent_uuid_str_or_null" } }
        """
        path = self._compact_manifest_path(project_name, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump({"overrides": overrides}, f, indent=2)

    def load_compact_manifest(
        self, project_name: str, session_id: UUID
    ) -> dict[str, str | None]:
        """Load compact manifest. Returns empty dict if not found."""
        path = self._compact_manifest_path(project_name, session_id)
        if not path.exists():
            return {}

        try:
            with open(path) as f:
                data = json.load(f)
            return data.get("overrides", {})
        except (json.JSONDecodeError, KeyError):
            return {}

    def list_sessions(self, project_name: str) -> list[SessionSummary]:
        """List all sessions for a project."""
        session_dir = self._session_dir(project_name)
        if not session_dir.exists():
            return []

        summaries = []
        for meta_file in session_dir.glob("*.meta.json"):
            try:
                session_id = UUID(meta_file.stem.replace(".meta", ""))
                metadata = self.load_metadata(project_name, session_id)
                if metadata:
                    summaries.append(
                        SessionSummary(
                            uuid=metadata.uuid,
                            description=metadata.description,
                            last_activity=metadata.last_activity,
                            message_count=metadata.message_count,
                            is_resumable=metadata.is_active,
                        )
                    )
            except ValueError:
                continue

        summaries.sort(key=lambda s: s.last_activity, reverse=True)
        return summaries

    def delete_session(self, project_name: str, session_id: UUID) -> bool:
        """Delete all files for a session."""
        deleted = False
        for path in [
            self._transcript_path(project_name, session_id),
            self._metadata_path(project_name, session_id),
            self._compact_manifest_path(project_name, session_id),
        ]:
            if path.exists():
                path.unlink()
                deleted = True
        return deleted
