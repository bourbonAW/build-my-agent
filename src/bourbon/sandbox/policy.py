"""Filesystem policy intermediate representation.

Converts SandboxContext's three path lists (writable, readonly, deny)
into an ordered list of MountRules that providers consume to generate
OS-specific configurations (bwrap args, SBPL profiles, Docker volumes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from bourbon.sandbox.runtime import SandboxContext


class MountMode(Enum):
    READ_ONLY = "ro"
    READ_WRITE = "rw"
    DENY = "deny"


@dataclass(slots=True)
class MountRule:
    """A single filesystem access rule."""

    path: str
    mode: MountMode


@dataclass(slots=True)
class FilesystemPolicy:
    """Ordered filesystem rules built from SandboxContext.

    Providers iterate this to generate OS-specific configurations.
    """

    rules: list[MountRule]

    @classmethod
    def from_context(cls, context: SandboxContext) -> FilesystemPolicy:
        """Build policy from SandboxContext paths.

        - All paths are expanded (~ → home, symlinks → realpath).
        - workdir is always included as READ_WRITE.
        - Order: READ_WRITE first, then READ_ONLY, then DENY.
          Providers that care about priority (seatbelt: last rule wins)
          use this ordering — deny is last so it overrides allow.
        """
        rules: list[MountRule] = []
        seen: set[str] = set()

        workdir_str = str(context.workdir)
        resolved_workdir = _resolve(workdir_str)
        rules.append(MountRule(path=resolved_workdir, mode=MountMode.READ_WRITE))
        seen.add(resolved_workdir)

        for path in context.writable_paths:
            resolved = _resolve(path)
            if resolved not in seen:
                rules.append(MountRule(path=resolved, mode=MountMode.READ_WRITE))
                seen.add(resolved)

        for path in context.readonly_paths:
            resolved = _resolve(path)
            if resolved not in seen:
                rules.append(MountRule(path=resolved, mode=MountMode.READ_ONLY))
                seen.add(resolved)

        for path in context.deny_paths:
            resolved = _resolve(path)
            rules.append(MountRule(path=resolved, mode=MountMode.DENY))

        return cls(rules=rules)


def _resolve(path: str) -> str:
    """Expand ~ and resolve symlinks to get a canonical absolute path."""
    return os.path.realpath(os.path.expanduser(path))
