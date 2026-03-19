"""MCP Client integration for Bourbon.

Enables Bourbon Agent to connect to and use external MCP servers.
"""

from bourbon.mcp_client.config import MCPConfig, MCPServerConfig
from bourbon.mcp_client.manager import MCPManager, ConnectionResult
from bourbon.mcp_client.connector import MCPConnectionError

__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "MCPManager",
    "ConnectionResult",
    "MCPConnectionError",
]
