"""MCP Client manager for Bourbon.

Manages MCP server connections and integrates MCP tools into Bourbon's tool system.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.types import CallToolResult, TextContent

from bourbon.mcp_client.config import MCPConfig, MCPServerConfig
from bourbon.mcp_client.connector import (
    HttpConnector,
    MCPConnectionError,
    MCPServerNotInstalledError,
    StdioConnector,
)
from bourbon.mcp_client.runtime import AsyncRuntime
from bourbon.tools import RiskLevel, Tool, ToolRegistry


@dataclass
class ConnectionResult:
    """Result of connecting to an MCP server."""
    
    success: bool
    server_name: str
    tools_count: int = 0
    error: str | None = None


class MCPManager:
    """Manages MCP client connections and tool registration.
    
    This class handles:
    - Connecting to configured MCP servers
    - Discovering and registering MCP tools
    - Managing connection lifecycle
    """
    
    def __init__(
        self,
        config: MCPConfig,
        tool_registry: ToolRegistry,
        workdir: Path | None = None,
    ):
        """Initialize MCP manager.
        
        Args:
            config: MCP configuration
            tool_registry: Registry to register MCP tools
            workdir: Working directory for path resolution
        """
        self.config = config
        self.tool_registry = tool_registry
        self.workdir = workdir or Path.cwd()
        
        # Map of server name to connector
        self._connectors: dict[str, StdioConnector | HttpConnector] = {}
        # Map of server name to connection result
        self._connection_results: dict[str, ConnectionResult] = {}
        self._runtime: AsyncRuntime | None = None

    def _ensure_runtime(self) -> AsyncRuntime:
        """Get or create the background runtime used by sync callers."""
        if self._runtime is None:
            self._runtime = AsyncRuntime()
        return self._runtime

    def connect_all_sync(self, timeout: float | None = None) -> dict[str, ConnectionResult]:
        """Connect to MCP servers from sync code."""
        runtime = self._ensure_runtime()
        return runtime.run(self.connect_all(), timeout=timeout)

    def disconnect_all_sync(self, timeout: float | None = None) -> None:
        """Disconnect MCP servers and stop the background runtime."""
        runtime = self._runtime
        if runtime is None:
            return

        try:
            runtime.run(self.disconnect_all(), timeout=timeout)
        finally:
            runtime.stop()
            self._runtime = None
    
    async def connect_all(self) -> dict[str, ConnectionResult]:
        """Connect to all enabled MCP servers.
        
        Returns:
            Mapping of server names to connection results
        """
        if not self.config.enabled:
            return {}
        
        enabled_servers = self.config.get_enabled_servers()
        results: dict[str, ConnectionResult] = {}
        
        for server_config in enabled_servers:
            result = await self._connect_server(server_config)
            results[server_config.name] = result
            self._connection_results[server_config.name] = result
        
        return results
    
    async def _connect_server(self, config: MCPServerConfig) -> ConnectionResult:
        """Connect to a single MCP server with retry logic.
        
        Args:
            config: Server configuration
            
        Returns:
            Connection result
            
        Raises:
            MCPServerNotInstalledError: If the server is not installed (no retry)
        """
        import asyncio
        
        last_error: Exception | None = None
        
        for attempt in range(config.max_retries):
            try:
                # Create connector based on transport type
                if config.transport == "stdio":
                    connector = StdioConnector(config)
                elif config.transport == "http":
                    connector = HttpConnector(config)
                else:
                    return ConnectionResult(
                        success=False,
                        server_name=config.name,
                        error=f"Transport '{config.transport}' not supported",
                    )
                
                # Connect to server
                session = await connector.connect()
                self._connectors[config.name] = connector
                
                # Discover and register tools
                tools_count = await self._register_server_tools(config.name, session)
                
                return ConnectionResult(
                    success=True,
                    server_name=config.name,
                    tools_count=tools_count,
                )
                
            except MCPServerNotInstalledError:
                # Don't retry if server is not installed - fail fast
                raise
            except MCPConnectionError as e:
                last_error = e
                if attempt < config.max_retries - 1:
                    wait_time = config.retry_delay * (2 ** attempt)  # Exponential backoff
                    print(f"MCP server '{config.name}' connection failed (attempt {attempt + 1}/{config.max_retries}), retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                import traceback
                error_detail = f"{e}\n{traceback.format_exc()}"
                return ConnectionResult(
                    success=False,
                    server_name=config.name,
                    error=f"Unexpected error: {error_detail}",
                )
        
        # All retries exhausted
        error_msg = str(last_error) if last_error else "Unknown error"
        if config.max_retries > 1:
            error_msg = f"Failed after {config.max_retries} attempts: {error_msg}"
        
        return ConnectionResult(
            success=False,
            server_name=config.name,
            error=error_msg,
        )
    
    async def _register_server_tools(
        self,
        server_name: str,
        session: ClientSession,
    ) -> int:
        """Register tools from an MCP server.
        
        Args:
            server_name: Name of the server
            session: Connected MCP session
            
        Returns:
            Number of tools registered
        """
        try:
            # List available tools from server
            tools_result = await session.list_tools()
            
            for mcp_tool in tools_result.tools:
                # Create tool with namespace prefix
                tool_name = f"{server_name}:{mcp_tool.name}"
                
                # Create handler for this tool
                handler = self._create_tool_handler(
                    session,
                    mcp_tool.name,
                    server_name,
                )
                
                # Create and register tool
                tool = Tool(
                    name=tool_name,
                    description=f"[{server_name} MCP] {mcp_tool.description or 'No description'}",
                    input_schema=mcp_tool.inputSchema,
                    handler=handler,
                    risk_level=RiskLevel.MEDIUM,  # Default to MEDIUM for external tools
                )
                
                self.tool_registry.register(tool)
            
            return len(tools_result.tools)
            
        except Exception as e:
            # Log error but don't fail the connection
            import traceback
            print(f"Warning: Failed to register tools from '{server_name}': {e}")
            print(f"Debug: Exception type: {type(e).__name__}")
            traceback.print_exc()
            return 0
    
    def _create_tool_handler(
        self,
        session: ClientSession,
        tool_name: str,
        server_name: str,
    ) -> callable:
        """Create a handler function for an MCP tool.
        
        Args:
            session: MCP client session
            tool_name: Original tool name (without namespace)
            server_name: Server name for error reporting
            
        Returns:
            Handler function
        """
        timeout = self.config.default_timeout

        def handler(**kwargs) -> str:
            """Execute the MCP tool."""
            try:
                runtime = self._ensure_runtime()
                result: CallToolResult = runtime.run(
                    session.call_tool(tool_name, arguments=kwargs),
                    timeout=timeout,
                )
                return self._format_tool_result(result)
            except Exception as e:
                return f"Error calling {server_name}:{tool_name}: {e}"
        
        return handler
    
    def _format_tool_result(self, result: CallToolResult) -> str:
        """Format MCP tool result for display.
        
        Args:
            result: Tool call result
            
        Returns:
            Formatted string output
        """
        parts = []
        
        for content in result.content:
            if isinstance(content, TextContent):
                parts.append(content.text)
            else:
                # Handle other content types (images, etc.)
                parts.append(f"[{content.type} content]")
        
        return "\n".join(parts) if parts else "(no output)"
    
    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for server_name, connector in self._connectors.items():
            try:
                await connector.disconnect()
            except Exception as e:
                print(f"Warning: Error disconnecting from '{server_name}': {e}")
        
        self._connectors.clear()
        self._connection_results.clear()
    
    def get_connection_status(self, server_name: str) -> dict[str, Any]:
        """Get connection status for a server.
        
        Args:
            server_name: Name of the server
            
        Returns:
            Status information dictionary
        """
        result = self._connection_results.get(server_name)
        connector = self._connectors.get(server_name)
        
        if result is None:
            return {
                "connected": False,
                "error": "Server not configured",
            }
        
        return {
            "connected": result.success and (connector.is_connected() if connector else False),
            "tools_count": result.tools_count,
            "error": result.error,
        }
    
    def list_mcp_tools(self) -> list[str]:
        """List all registered MCP tool names.
        
        Returns:
            List of tool names with server prefix
        """
        mcp_tools = []
        for tool in self.tool_registry.list_tools():
            # MCP tools have colon in their name (server:tool)
            if ":" in tool.name:
                mcp_tools.append(tool.name)
        return mcp_tools
    
    def get_connection_summary(self) -> dict[str, Any]:
        """Get summary of all MCP connections.
        
        Returns:
            Summary dictionary
        """
        total = len(self._connection_results)
        connected = sum(
            1 for r in self._connection_results.values() if r.success
        )
        total_tools = sum(
            r.tools_count for r in self._connection_results.values()
        )
        
        return {
            "enabled": self.config.enabled,
            "configured": len(self.config.servers),
            "attempted": total,
            "connected": connected,
            "failed": total - connected,
            "total_tools": total_tools,
            "servers": {
                name: {
                    "connected": result.success,
                    "tools": result.tools_count,
                    "error": result.error,
                }
                for name, result in self._connection_results.items()
            },
        }
