from bourbon.audit.events import EventType


def test_memory_event_types_exist() -> None:
    assert EventType.MEMORY_WRITE == "memory_write"
    assert EventType.MEMORY_SEARCH == "memory_search"
    assert EventType.MEMORY_FLUSH == "memory_flush"
