"""Tests for MCP transport connectors."""

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from bourbon.mcp_client.config import MCPServerConfig
from bourbon.mcp_client.connector import HttpConnector, StdioConnector


class DummySession:
    """Minimal async context manager that looks like an MCP session."""

    def __init__(self) -> None:
        self.initialize = AsyncMock()
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.exited = True
        return None


class TestStdioConnector(unittest.IsolatedAsyncioTestCase):
    """Tests for stdio transport connector."""

    async def test_connect_enters_client_session_context(self):
        """Stdio connections should enter ClientSession before initialize()."""
        config = MCPServerConfig(
            name="test",
            transport="stdio",
            command="npx",
            args=["example-server"],
        )
        connector = StdioConnector(config)
        session = DummySession()
        read_stream = object()
        write_stream = object()

        @asynccontextmanager
        async def fake_stdio_client(_server_params):
            yield read_stream, write_stream

        with (
            patch.object(connector, "_validate_command"),
            patch(
                "bourbon.mcp_client.connector.stdio_client",
                return_value=fake_stdio_client(None),
            ),
            patch(
                "bourbon.mcp_client.connector.ClientSession",
                return_value=session,
            ) as mock_client_session,
        ):
            connected_session = await connector.connect()

        assert connected_session is session
        assert session.entered is True
        session.initialize.assert_awaited_once()
        mock_client_session.assert_called_once_with(read_stream, write_stream)

    async def test_connect_prefers_installed_binary_over_npx_wrapper(self):
        """Use an installed package binary directly when npx would just wrap it."""
        config = MCPServerConfig(
            name="context7",
            transport="stdio",
            command="npx",
            args=["-y", "@upstash/context7-mcp@latest", "--foo"],
        )
        connector = StdioConnector(config)
        session = DummySession()
        read_stream = object()
        write_stream = object()
        captured = {}

        @asynccontextmanager
        async def fake_stdio_client(server_params):
            captured["server_params"] = server_params
            yield read_stream, write_stream

        with (
            patch.object(connector, "_validate_command"),
            patch(
                "bourbon.mcp_client.connector.shutil.which",
                side_effect=lambda command: (
                    "/opt/homebrew/bin/context7-mcp" if command == "context7-mcp" else None
                ),
            ),
            patch(
                "bourbon.mcp_client.connector.stdio_client",
                side_effect=fake_stdio_client,
            ),
            patch(
                "bourbon.mcp_client.connector.ClientSession",
                return_value=session,
            ),
        ):
            await connector.connect()

        server_params = captured["server_params"]
        assert server_params.command == "context7-mcp"
        assert server_params.args == ["--foo"]

    async def test_disconnect_uses_exit_stack_cleanup(self):
        """Disconnect should rely on the exit stack instead of session.aclose()."""
        config = MCPServerConfig(
            name="test",
            transport="stdio",
            command="npx",
            args=["example-server"],
        )
        connector = StdioConnector(config)
        connector._session = object()
        exit_stack = MagicMock()
        exit_stack.aclose = AsyncMock()
        connector._exit_stack = exit_stack

        await connector.disconnect()

        exit_stack.aclose.assert_awaited_once()
        assert connector._session is None
        assert connector._exit_stack is None


class TestHttpConnector(unittest.IsolatedAsyncioTestCase):
    """Tests for HTTP transport connector."""

    async def test_connect_enters_client_session_context(self):
        """HTTP connections should enter ClientSession before initialize()."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:3000/mcp",
        )
        connector = HttpConnector(config)
        session = DummySession()
        read_stream = object()
        write_stream = object()

        @asynccontextmanager
        async def fake_http_client(_url):
            yield read_stream, write_stream

        with (
            patch(
                "mcp.client.streamable_http.streamable_http_client",
                return_value=fake_http_client(None),
            ),
            patch(
                "bourbon.mcp_client.connector.ClientSession",
                return_value=session,
            ) as mock_client_session,
        ):
            connected_session = await connector.connect()

        assert connected_session is session
        assert session.entered is True
        session.initialize.assert_awaited_once()
        mock_client_session.assert_called_once_with(read_stream, write_stream)
