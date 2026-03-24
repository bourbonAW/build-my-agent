"""MCP Client integration for Bourbon.

Enables Bourbon Agent to connect to and use external MCP servers.
"""

from bourbon.mcp_client.config import MCPConfig, MCPServerConfig
from bourbon.mcp_client.connector import (
    HttpConnector,
    MCPConnectionError,
    MCPServerNotInstalledError,
    StdioConnector,
)
from bourbon.mcp_client.manager import ConnectionResult, MCPManager

__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "MCPManager",
    "ConnectionResult",
    "MCPConnectionError",
    "MCPServerNotInstalledError",
    "StdioConnector",
    "HttpConnector",
]
