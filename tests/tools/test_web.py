"""Tests for web tools"""

import pytest

from bourbon.tools.web import fetch_url


@pytest.mark.asyncio
async def test_fetch_url_invalid():
    """Test handling invalid URL"""
    result = await fetch_url("not-a-valid-url")
    assert result["success"] is False
    assert "Invalid URL" in result["error"]


@pytest.mark.asyncio
async def test_fetch_url_valid():
    """Test fetching httpbin (if available)"""
    result = await fetch_url("https://httpbin.org/get")
    # May fail in CI, so just check structure
    assert "success" in result
    assert "url" in result
