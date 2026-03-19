"""MCP transport connectors for Bourbon.

Provides connectors for different MCP transport mechanisms.
"""

from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bourbon.mcp_client.config import MCPServerConfig


class MCPConnectionError(Exception):
    """Error connecting to MCP server."""
    pass


class StdioConnector:
    """Stdio transport connector for MCP servers.
    
    Connects to an MCP server by spawning a subprocess and communicating
    over stdin/stdout.
    """
    
    def __init__(self, config: MCPServerConfig):
        """Initialize stdio connector.
        
        Args:
            config: Server configuration with stdio transport settings
        """
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack: Any = None
    
    async def connect(self) -> ClientSession:
        """Connect to the MCP server via stdio.
        
        Returns:
            Connected ClientSession
            
        Raises:
            MCPConnectionError: If connection fails
        """
        if not self.config.command:
            raise MCPConnectionError("No command specified for stdio transport")
        
        # Prepare server parameters
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env if self.config.env else None,
        )
        
        try:
            # Create stdio client
            self._exit_stack = stdio_client(server_params)
            read_stream, write_stream = await self._exit_stack.__aenter__()
            
            # Create and initialize session
            self._session = ClientSession(read_stream, write_stream)
            await self._session.initialize()
            
            return self._session
            
        except Exception as e:
            # Clean up on failure
            if self._exit_stack:
                await self._exit_stack.__aexit__(type(e), e, None)
                self._exit_stack = None
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.config.name}': {e}"
            ) from e
    
    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            await self._session.aclose()
            self._session = None
        
        if self._exit_stack:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
    
    @property
    def session(self) -> ClientSession | None:
        """Get the current session if connected."""
        return self._session
    
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._session is not None


class HttpConnector:
    """HTTP transport connector for MCP servers.
    
    Connects to an MCP server over HTTP using Server-Sent Events (SSE)
    for server-to-client streaming and HTTP POST for client-to-server.
    """
    
    def __init__(self, config: MCPServerConfig):
        """Initialize HTTP connector.
        
        Args:
            config: Server configuration with HTTP transport settings
        """
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack: Any = None
    
    async def connect(self) -> ClientSession:
        """Connect to the MCP server via HTTP.
        
        Returns:
            Connected ClientSession
            
        Raises:
            MCPConnectionError: If connection fails
        """
        if not self.config.url:
            raise MCPConnectionError("No URL specified for HTTP transport")
        
        try:
            # Import here to allow graceful fallback if not available
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as e:
            raise MCPConnectionError(
                f"HTTP transport requires mcp>=1.1.0: {e}"
            ) from e
        
        try:
            # Create HTTP client context manager
            self._exit_stack = streamable_http_client(self.config.url)
            read_stream, write_stream = await self._exit_stack.__aenter__()
            
            # Create and initialize session
            self._session = ClientSession(read_stream, write_stream)
            await self._session.initialize()
            
            return self._session
            
        except Exception as e:
            # Clean up on failure
            if self._exit_stack:
                await self._exit_stack.__aexit__(type(e), e, None)
                self._exit_stack = None
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.config.name}' at {self.config.url}: {e}"
            ) from e
    
    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            await self._session.aclose()
            self._session = None
        
        if self._exit_stack:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
    
    @property
    def session(self) -> ClientSession | None:
        """Get the current session if connected."""
        return self._session
    
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._session is not None
