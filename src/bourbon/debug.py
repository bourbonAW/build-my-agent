"""Optional JSONL debug logging for runtime diagnostics."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


def _get_log_path() -> Path | None:
    """Return configured debug log path, if any."""
    raw_path = os.environ.get("BOURBON_DEBUG_LOG")
    if raw_path:
        return Path(raw_path).expanduser()

    enabled_flags = ("BOURBON_DEBUG", "BOURBON_DEBUG_PROMPTS")
    if any(
        os.environ.get(flag, "").lower() in {"1", "true", "yes", "on"}
        for flag in enabled_flags
    ):
        return (Path.home() / ".bourbon" / "logs" / "debug.jsonl").expanduser()

    return None


def prompt_fields(
    messages: list[dict] | None,
    system: str | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    """Return full prompt fields for logging, gated on BOURBON_DEBUG_PROMPTS.

    When BOURBON_DEBUG_PROMPTS is set, the returned dict includes the full
    messages list, system prompt, and tool names — suitable for per-round
    prompt inspection. When unset, returns an empty dict so the caller can
    unpack it with ** without changing the log record.
    """
    if os.environ.get("BOURBON_DEBUG_PROMPTS", "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {}
    return {
        "messages": messages,
        "system": system,
        "tool_names": [t.get("name") for t in (tools or [])],
    }


def debug_log(event: str, **fields: Any) -> None:
    """Append a debug record when runtime diagnostics are enabled.

    Logging is intentionally best-effort and must never interfere with normal
    REPL or streaming behavior.
    """
    log_path = _get_log_path()
    if log_path is None:
        return

    record: dict[str, Any] = {
        "ts": time.time(),
        "event": event,
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
    }
    record.update(fields)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
    except Exception:
        # Diagnostics must not break the product path.
        return
