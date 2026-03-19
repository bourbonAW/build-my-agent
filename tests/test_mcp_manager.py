"""Tests for MCP Manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bourbon.mcp_client.config import MCPConfig, MCPServerConfig
from bourbon.mcp_client.manager import MCPManager, ConnectionResult
from bourbon.tools import ToolRegistry


class TestMCPManager:
    """Tests for MCPManager."""

    @pytest.fixture
    def empty_config(self):
        """Create empty MCP config."""
        return MCPConfig(enabled=True, servers=[])

    @pytest.fixture
    def tool_registry(self):
        """Create fresh tool registry."""
        return ToolRegistry()

    @pytest.fixture
    def manager(self, empty_config, tool_registry):
        """Create MCP manager with empty config."""
        return MCPManager(
            config=empty_config,
            tool_registry=tool_registry,
        )

    def test_init(self, manager, empty_config, tool_registry):
        """Test manager initialization."""
        assert manager.config == empty_config
        assert manager.tool_registry == tool_registry
        assert manager._connectors == {}
        assert manager._connection_results == {}

    @pytest.mark.asyncio
    async def test_connect_all_empty_config(self, manager):
        """Test connect_all with empty config."""
        results = await manager.connect_all()
        assert results == {}

    @pytest.mark.asyncio
    async def test_connect_all_disabled(self, tool_registry):
        """Test connect_all when MCP is disabled."""
        config = MCPConfig(enabled=False)
        manager = MCPManager(config=config, tool_registry=tool_registry)
        results = await manager.connect_all()
        assert results == {}

    @pytest.mark.asyncio
    async def test_disconnect_all_empty(self, manager):
        """Test disconnect_all with no connections."""
        # Should not raise
        await manager.disconnect_all()

    def test_get_connection_status_unknown(self, manager):
        """Test get_connection_status for unknown server."""
        status = manager.get_connection_status("unknown")
        assert status["connected"] is False
        assert "not configured" in status["error"]

    def test_list_mcp_tools_empty(self, manager):
        """Test list_mcp_tools with no tools."""
        tools = manager.list_mcp_tools()
        assert tools == []

    def test_get_connection_summary_empty(self, manager):
        """Test get_connection_summary with no connections."""
        summary = manager.get_connection_summary()
        assert summary["enabled"] is True
        assert summary["configured"] == 0
        assert summary["attempted"] == 0
        assert summary["connected"] == 0
        assert summary["failed"] == 0
        assert summary["total_tools"] == 0
        assert summary["servers"] == {}

    def test_get_connection_summary_with_servers(self, tool_registry):
        """Test get_connection_summary with configured servers."""
        config = MCPConfig(
            enabled=True,
            servers=[
                MCPServerConfig(name="server1", transport="stdio", command="echo"),
                MCPServerConfig(name="server2", transport="stdio", command="cat"),
            ],
        )
        manager = MCPManager(config=config, tool_registry=tool_registry)
        
        summary = manager.get_connection_summary()
        assert summary["configured"] == 2

    @pytest.mark.asyncio
    async def test_connect_server_http_success(self, manager):
        """Test successful HTTP connection (mocked)."""
        config = MCPServerConfig(
            name="http_server",
            transport="http",
            url="http://localhost:3000/mcp",
            max_retries=1,
        )
        
        # Mock the HTTP connector
        with patch("bourbon.mcp_client.manager.HttpConnector") as mock_connector_class:
            mock_connector = MagicMock()
            mock_session = MagicMock()
            mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))
            mock_connector.connect = AsyncMock(return_value=mock_session)
            mock_connector_class.return_value = mock_connector
            
            result = await manager._connect_server(config)
            
            assert result.success is True
            assert result.server_name == "http_server"
            mock_connector_class.assert_called_once_with(config)

    def test_format_tool_result_text_only(self, manager):
        """Test formatting tool result with text content."""
        from mcp.types import CallToolResult, TextContent
        
        result = CallToolResult(
            content=[TextContent(type="text", text="Hello, World!")],
            isError=False,
        )
        
        formatted = manager._format_tool_result(result)
        assert formatted == "Hello, World!"

    def test_format_tool_result_multiple_texts(self, manager):
        """Test formatting tool result with multiple text contents."""
        from mcp.types import CallToolResult, TextContent
        
        result = CallToolResult(
            content=[
                TextContent(type="text", text="Line 1"),
                TextContent(type="text", text="Line 2"),
            ],
            isError=False,
        )
        
        formatted = manager._format_tool_result(result)
        assert formatted == "Line 1\nLine 2"

    def test_format_tool_result_empty(self, manager):
        """Test formatting empty tool result."""
        from mcp.types import CallToolResult
        
        result = CallToolResult(content=[], isError=False)
        
        formatted = manager._format_tool_result(result)
        assert formatted == "(no output)"

    def test_create_tool_handler(self, manager):
        """Test creating tool handler."""
        mock_session = MagicMock()
        mock_session.call_tool = AsyncMock(return_value=MagicMock(
            content=[MagicMock(type="text", text="Result")],
        ))
        manager._runtime = MagicMock()
        manager._runtime.run.return_value = MagicMock(
            content=[MagicMock(type="text", text="Result")],
        )
        
        handler = manager._create_tool_handler(mock_session, "test_tool", "test_server")

        result = handler(arg1="value1")
        
        assert "Result" in result
        manager._runtime.run.assert_called_once()

    def test_create_tool_handler_error(self, manager):
        """Test tool handler with error."""
        mock_session = MagicMock()
        mock_session.call_tool = AsyncMock(side_effect=Exception("Tool error"))
        manager._runtime = MagicMock()
        manager._runtime.run.side_effect = Exception("Tool error")
        
        handler = manager._create_tool_handler(mock_session, "test_tool", "test_server")

        result = handler(arg1="value1")
        
        assert "Error" in result
        assert "test_server:test_tool" in result


class TestConnectionResult:
    """Tests for ConnectionResult."""

    def test_success_result(self):
        """Test successful connection result."""
        result = ConnectionResult(
            success=True,
            server_name="test",
            tools_count=5,
        )
        assert result.success is True
        assert result.server_name == "test"
        assert result.tools_count == 5
        assert result.error is None

    def test_failure_result(self):
        """Test failed connection result."""
        result = ConnectionResult(
            success=False,
            server_name="test",
            error="Connection refused",
        )
        assert result.success is False
        assert result.error == "Connection refused"
        assert result.tools_count == 0
