"""Tests for synchronous MCP integration points."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp.types import TextContent

from bourbon.agent import Agent
from bourbon.mcp_client.config import MCPConfig
from bourbon.mcp_client.manager import MCPManager
from bourbon.repl import REPL
from bourbon.tools import ToolRegistry


class TestMCPManagerSync(unittest.TestCase):
    """Tests for sync wrappers around async MCP operations."""

    def test_create_tool_handler_runs_async_call_synchronously(self):
        """MCP tool handlers must return strings to the sync agent loop."""
        manager = MCPManager(config=MCPConfig(), tool_registry=ToolRegistry())
        manager._runtime = MagicMock()
        manager._runtime.run.return_value = SimpleNamespace(
            content=[TextContent(type="text", text="Result")],
        )
        session = MagicMock()

        handler = manager._create_tool_handler(session, "test_tool", "test_server")
        result = handler(arg1="value1")

        assert result == "Result"
        manager._runtime.run.assert_called_once()


class TestAgentSyncMCPInitialization(unittest.TestCase):
    """Tests for synchronous MCP initialization entry points."""

    def test_initialize_mcp_sync_updates_system_prompt_when_tools_are_available(self):
        """Agent should expose a sync MCP init path for the sync REPL."""
        agent = Agent.__new__(Agent)
        agent.mcp = MagicMock()
        results = {"context7": object()}
        agent.mcp.connect_all_sync.return_value = results
        agent.mcp.get_connection_summary.return_value = {"total_tools": 2}
        agent._build_system_prompt = MagicMock(return_value="updated prompt")
        agent._custom_system_prompt = None
        agent.system_prompt = "old prompt"

        returned = Agent.initialize_mcp_sync(agent, timeout=60.0)

        agent.mcp.connect_all_sync.assert_called_once_with(timeout=60.0)
        assert returned is results
        assert agent.system_prompt == "updated prompt"


class TestREPLSyncMCPInitialization(unittest.TestCase):
    """Tests for REPL MCP startup behavior."""

    def test_init_mcp_uses_sync_agent_initializer(self):
        """REPL startup should not create a temporary event loop for MCP."""
        repl = REPL.__new__(REPL)
        repl.config = SimpleNamespace(mcp=SimpleNamespace(enabled=True))
        repl.agent = MagicMock()
        repl.agent.initialize_mcp_sync.return_value = {}
        repl.agent.mcp = MagicMock()
        repl.agent.mcp.get_connection_summary.return_value = {
            "connected": 0,
            "failed": 0,
            "total_tools": 0,
        }
        repl.console = MagicMock()

        REPL._init_mcp(repl)

        repl.agent.initialize_mcp_sync.assert_called_once_with(timeout=60.0)
