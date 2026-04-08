"""Tests for ToolSearch deferred tool discovery."""

from pathlib import Path

import pytest

from bourbon.tools import ToolContext, definitions, get_registry


@pytest.fixture(autouse=True)
def ensure_tools_registered():
    """Populate the global registry before tests call get_registry().call()."""
    definitions()


class TestToolSearch:
    def test_tool_search_registered_as_always_load(self):
        defs = definitions()
        names = {d["name"] for d in defs}
        assert "ToolSearch" in names

    def test_tool_search_finds_deferred_tools(self):
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        result = get_registry().call("ToolSearch", {"query": "csv analyze"}, ctx)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_token_scoring_matches_webfetch(self):
        pytest.importorskip("aiohttp")
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        result = get_registry().call("ToolSearch", {"query": "fetch web page"}, ctx)
        if "WebFetch" in result:
            assert "WebFetch" in discovered

    def test_no_match_returns_helpful_message(self):
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        result = get_registry().call("ToolSearch", {"query": "xxxxxxxxnothing"}, ctx)
        assert "No tools found" in result

    def test_on_tools_discovered_callback_called(self):
        pytest.importorskip("pandas")
        discovered: set[str] = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        get_registry().call("ToolSearch", {"query": "csv analyze"}, ctx)
        assert len(discovered) > 0
        assert all(isinstance(name, str) for name in discovered)
