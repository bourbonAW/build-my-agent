"""Tests for persistent workflow task types."""

from bourbon.tasks import TaskRecord


class TestTaskRecord:
    def test_defaults_status_to_pending(self):
        record = TaskRecord(id="1", subject="a", description="b")

        assert record.status == "pending"

    def test_to_dict_uses_expected_key_names(self):
        record = TaskRecord(
            id="42",
            subject="Ship persistence layer",
            description="Implement file-backed task storage",
            status="open",
            active_form="Implementing persistence layer",
            owner="bourbon",
            blocks=["43"],
            blocked_by=["41"],
            metadata={"priority": "high"},
        )

        data = record.to_dict()

        assert data == {
            "id": "42",
            "subject": "Ship persistence layer",
            "description": "Implement file-backed task storage",
            "status": "open",
            "activeForm": "Implementing persistence layer",
            "owner": "bourbon",
            "blocks": ["43"],
            "blockedBy": ["41"],
            "metadata": {"priority": "high"},
        }

    def test_from_dict_reads_camel_case_fields(self):
        record = TaskRecord.from_dict(
            {
                "id": "7",
                "subject": "Review",
                "description": "Review stored task payload",
                "status": "blocked",
                "activeForm": "Waiting on review",
                "owner": "agent",
                "blocks": ["9"],
                "blockedBy": ["6"],
                "metadata": {"source": "test"},
            }
        )

        assert record.active_form == "Waiting on review"
        assert record.blocked_by == ["6"]
        assert record.blocks == ["9"]
        assert record.metadata == {"source": "test"}

    def test_from_dict_defaults_missing_status_to_pending(self):
        record = TaskRecord.from_dict(
            {
                "id": "8",
                "subject": "Review",
                "description": "Missing status should default",
            }
        )

        assert record.status == "pending"
