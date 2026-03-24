"""Sandbox provider selection."""

from __future__ import annotations

from bourbon.sandbox.providers.local import LocalProvider
from bourbon.sandbox.runtime import SandboxProvider


class SandboxProviderNotFound(ValueError):
    """Raised when a sandbox provider name is not recognized."""


def select_provider(name: str) -> SandboxProvider:
    """Return a sandbox provider by name."""
    normalized = name.lower()
    if normalized in {"local", "auto"}:
        return LocalProvider()
    raise SandboxProviderNotFound(f"Sandbox provider not found: {name}")


__all__ = ["SandboxProviderNotFound", "select_provider", "LocalProvider"]
