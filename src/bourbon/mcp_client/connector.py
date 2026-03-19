"""MCP transport connectors for Bourbon.

Provides connectors for different MCP transport mechanisms.
"""

import shutil
import subprocess
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bourbon.mcp_client.config import MCPServerConfig


class MCPConnectionError(Exception):
    """Error connecting to MCP server."""
    pass


class MCPServerNotInstalledError(MCPConnectionError):
    """MCP server package is not installed and auto-download is disabled."""
    pass


class StdioConnector:
    """Stdio transport connector for MCP servers.
    
    Connects to an MCP server by spawning a subprocess and communicating
    over stdin/stdout.
    
    Note: This connector does NOT auto-download packages. If the MCP server
    is not installed, it will raise an error.
    """
    
    def __init__(self, config: MCPServerConfig):
        """Initialize stdio connector.
        
        Args:
            config: Server configuration with stdio transport settings
        """
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack: Any = None
    
    def _validate_command(self) -> None:
        """Validate that the command exists and MCP server is installed.
        
        Raises:
            MCPServerNotInstalledError: If the MCP server is not installed
            MCPConnectionError: If the base command (npx/node) is not found
        """
        if not self.config.command:
            raise MCPConnectionError("No command specified for stdio transport")
        
        # Check if base command exists (npx, node, python, etc.)
        base_cmd = self.config.command
        if not shutil.which(base_cmd):
            raise MCPConnectionError(
                f"Command '{base_cmd}' not found. Please install it first."
            )
        
        # Special handling for npx - check if package is installed
        if base_cmd == "npx":
            self._validate_npx_package()
    
    def _validate_npx_package(self) -> None:
        """Check if the npm package for npx is already installed.
        
        Raises:
            MCPServerNotInstalledError: If the package is not installed
        """
        if not self.config.args:
            return
        
        # Extract package name from args (e.g., "-y", "@upstash/context7-mcp@latest" -> "@upstash/context7-mcp")
        package_name = None
        for arg in self.config.args:
            # Skip flags
            if arg.startswith("-"):
                continue
            # First non-flag arg is typically the package name
            package_name = arg
            break
        
        if not package_name:
            return
        
        # Remove version suffix if present (@latest, @1.0.0, etc.)
        if "@" in package_name and not package_name.startswith("@"):
            package_name = package_name.split("@")[0]
        elif package_name.startswith("@"):
            # Scoped package like @org/package@version
            parts = package_name.rsplit("@", 1)
            if len(parts) == 2 and "/" in parts[1]:
                # No version suffix, keep as is
                pass
            elif len(parts) == 2:
                package_name = parts[0]
        
        # Check if package is installed globally
        try:
            result = subprocess.run(
                ["npm", "list", "-g", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return  # Package is installed globally
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Check if package is in local node_modules
        try:
            result = subprocess.run(
                ["npm", "list", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return  # Package is installed locally
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Check if package can be resolved without network (dry-run)
        try:
            result = subprocess.run(
                ["npx", "--dry-run", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # If dry-run succeeds, package is cached locally
            if result.returncode == 0:
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # Package is not installed
        raise MCPServerNotInstalledError(
            f"MCP server package '{package_name}' is not installed. "
            f"Please install it first:\n"
            f"  npm install -g {package_name}\n"
            f"Or disable this MCP server in config."
        )
    
    async def connect(self) -> ClientSession:
        """Connect to the MCP server via stdio.
        
        Returns:
            Connected ClientSession
            
        Raises:
            MCPServerNotInstalledError: If the MCP server package is not installed
            MCPConnectionError: If connection fails
        """
        # Validate command exists and MCP server is installed (no auto-download)
        self._validate_command()
        
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
