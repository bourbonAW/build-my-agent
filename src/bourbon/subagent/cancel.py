"""Cancellation primitives for subagent runtime jobs."""

from __future__ import annotations

import threading


class AbortController:
    """Hierarchical cancellation controller.

    Aborting a parent cascades to its current children. Children created after a
    parent was aborted start in the aborted state as well.
    """

    def __init__(self, parent: AbortController | None = None):
        self._event = threading.Event()
        self._parent = parent
        self._children: list[AbortController] = []
        self._lock = threading.RLock()

        if parent is not None:
            parent._add_child(self)
            if parent.is_aborted():
                self.abort()

    def _add_child(self, child: AbortController) -> None:
        with self._lock:
            self._children.append(child)

    def abort(self) -> None:
        """Trigger abort and cascade the signal to children."""
        self._event.set()
        with self._lock:
            children = list(self._children)
        for child in children:
            child.abort()

    def is_aborted(self) -> bool:
        """Return whether this controller or any parent is aborted."""
        if self._event.is_set():
            return True
        return self._parent.is_aborted() if self._parent is not None else False

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until this controller is aborted or timeout expires."""
        if self.is_aborted():
            return True
        return self._event.wait(timeout)
