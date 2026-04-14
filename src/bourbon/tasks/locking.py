"""Filesystem locking helpers for task storage."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import TextIO


class FileLock:
    """Exclusive advisory lock backed by a lock file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._handle: TextIO | None = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._handle = self.path.open("r+")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
