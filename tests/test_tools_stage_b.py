"""Tests for Stage-B deferred tools registration."""

import pytest

pytest.importorskip("aiohttp", reason="Stage-B web dependencies not installed")

from bourbon.tools import definitions, get_tool_with_metadata


class TestStageBDeferred:
    def test_web_fetch_registered_as_deferred(self):
        defs_default = definitions()
        names_default = {d["name"] for d in defs_default}
        assert "WebFetch" not in names_default, "WebFetch should NOT be in default prompt"

        tool = get_tool_with_metadata("WebFetch")
        assert tool is not None
        assert tool.should_defer is True
        assert tool.always_load is False

    def test_stage_b_visible_when_discovered(self):
        defs = definitions(discovered={"WebFetch"})
        names = {d["name"] for d in defs}
        assert "WebFetch" in names

    def test_aliases_preserved(self):
        tool = get_tool_with_metadata("fetch_url")
        assert tool is not None
        assert tool.name == "WebFetch"
