"""Credential filtering for sandboxed environments."""

from __future__ import annotations

import os
from fnmatch import fnmatch
from typing import ClassVar


class CredentialManager:
    """Filter environment variables for sandbox execution."""

    _SENSITIVE_PATTERNS: ClassVar[tuple[str, ...]] = (
        "*_KEY",
        "*_SECRET",
        "*_TOKEN",
        "*_PASSWORD",
        "AWS_*",
        "OPENAI_*",
        "ANTHROPIC_*",
        "DATABASE_URL",
        "REDIS_URL",
    )

    @classmethod
    def clean_env(
        cls,
        passthrough_vars: list[str],
        source_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Return a filtered environment containing only allowed variables."""
        env = os.environ if source_env is None else source_env
        return {
            key: value
            for key, value in env.items()
            if key in passthrough_vars and not cls._is_sensitive(key)
        }

    @classmethod
    def _is_sensitive(cls, key: str) -> bool:
        return any(fnmatch(key, pattern) for pattern in cls._SENSITIVE_PATTERNS)
