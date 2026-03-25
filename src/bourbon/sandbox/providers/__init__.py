"""Sandbox provider selection."""

from __future__ import annotations

import sys

from bourbon.sandbox.providers.local import LocalProvider
from bourbon.sandbox.runtime import SandboxProvider


class SandboxProviderNotFoundError(ValueError):
    """Raised when a sandbox provider name is not recognized."""


SandboxProviderNotFound = SandboxProviderNotFoundError


def select_provider(name: str) -> SandboxProvider:
    """Return a sandbox provider by name.

    Args:
        name: Provider name: "local", "bubblewrap", "seatbelt", "auto"
    """
    normalized = name.lower()

    if normalized == "bubblewrap":
        from bourbon.sandbox.providers.bubblewrap import BwrapProvider

        if not BwrapProvider.is_available():
            raise SandboxProviderNotFound(
                'bubblewrap not found. Install it or set provider = "auto"'
            )
        return BwrapProvider()

    if normalized == "seatbelt":
        from bourbon.sandbox.providers.seatbelt import SeatbeltProvider

        if not SeatbeltProvider.is_available():
            raise SandboxProviderNotFound(
                'seatbelt requires macOS. Set provider = "auto"'
            )
        return SeatbeltProvider()

    if normalized == "local":
        return LocalProvider()

    if normalized == "auto":
        if sys.platform == "linux":
            from bourbon.sandbox.providers.bubblewrap import BwrapProvider

            if BwrapProvider.is_available():
                return BwrapProvider()
        if sys.platform == "darwin":
            from bourbon.sandbox.providers.seatbelt import SeatbeltProvider

            return SeatbeltProvider()
        return LocalProvider()

    raise SandboxProviderNotFound(f"Sandbox provider not found: {name}")


__all__ = [
    "SandboxProviderNotFound",
    "SandboxProviderNotFoundError",
    "select_provider",
    "LocalProvider",
]
