"""MCP transport connectors for Bourbon.

Provides connectors for different MCP transport mechanisms.
"""

import shutil
import subprocess
from contextlib import AsyncExitStack, suppress
from pathlib import Path

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
        self._exit_stack: AsyncExitStack | None = None

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
            raise MCPConnectionError(f"Command '{base_cmd}' not found. Please install it first.")

        # Special handling for npx - check if package is installed
        if base_cmd == "npx":
            self._validate_npx_package()

    def _extract_npx_package_spec(self, args: list[str]) -> tuple[int | None, str | None]:
        """Return the npx package argument index and raw package spec."""
        for index, arg in enumerate(args):
            if arg.startswith("-"):
                continue
            return index, arg
        return None, None

    def _normalize_npx_package_name(self, package_name: str) -> str:
        """Remove version suffix from an npm package name if present."""
        clean_name = package_name
        if "@" in package_name and not package_name.startswith("@"):
            clean_name = package_name.split("@")[0]
        elif package_name.startswith("@"):
            # Scoped package like @org/package@version
            parts = package_name.rsplit("@", 1)
            if len(parts) == 2 and "/" not in parts[1]:
                clean_name = parts[0]
        return clean_name

    def _resolve_direct_npx_binary(self, args: list[str]) -> tuple[str, list[str]] | None:
        """Prefer an installed package binary over an npx wrapper when possible."""
        package_index, package_spec = self._extract_npx_package_spec(args)
        if package_index is None or package_spec is None:
            return None

        clean_name = self._normalize_npx_package_name(package_spec)
        binary_name = clean_name.split("/")[-1]
        if not shutil.which(binary_name):
            return None

        return binary_name, args[package_index + 1 :]

    def _validate_npx_package(self) -> None:
        """Check if the npm package for npx is already installed.

        Supports npm, pnpm, and yarn global installations.

        Raises:
            MCPServerNotInstalledError: If the package is not installed
        """
        if not self.config.args:
            return

        # Extract package name from args (for example:
        # "-y", "@upstash/context7-mcp@latest" -> "@upstash/context7-mcp").
        _, package_name = self._extract_npx_package_spec(self.config.args)

        if not package_name:
            return

        # Remove version suffix if present (@latest, @1.0.0, etc.)
        clean_name = self._normalize_npx_package_name(package_name)

        # Check npm global
        if self._check_npm_global(clean_name):
            return

        # Check pnpm global
        if self._check_pnpm_global(clean_name):
            return

        # Check yarn global
        if self._check_yarn_global(clean_name):
            return

        # Check local node_modules
        if self._check_local_npm(clean_name):
            return

        # Check if package can be resolved without network (npx cache)
        if self._check_npx_cache(package_name):
            return

        # Package is not installed
        raise MCPServerNotInstalledError(
            f"MCP server package '{clean_name}' is not installed. "
            f"Please install it first:\n"
            f"  npm install -g {clean_name}\n"
            f"  # or: pnpm install -g {clean_name}\n"
            f"  # or: yarn global add {clean_name}\n"
            f"Or disable this MCP server in config."
        )

    def _check_npm_global(self, package_name: str) -> bool:
        """Check if package is installed globally via npm."""
        try:
            result = subprocess.run(
                ["npm", "list", "-g", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _check_pnpm_global(self, package_name: str) -> bool:
        """Check if package is installed globally via pnpm."""
        try:
            result = subprocess.run(
                ["pnpm", "list", "-g", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and package_name in result.stdout:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return False

    def _check_yarn_global(self, package_name: str) -> bool:
        """Check if package is installed globally via yarn."""
        try:
            result = subprocess.run(
                ["yarn", "global", "list", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and package_name in result.stdout:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return False

    def _check_local_npm(self, package_name: str) -> bool:
        """Check if package is in local node_modules."""
        try:
            result = subprocess.run(
                ["npm", "list", package_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _check_npx_cache(self, package_name: str) -> bool:
        """Check if package is in npx cache.

        First tries 'npx --dry-run' for quick check, but falls back to
        directly scanning the npm cache directory if that times out.
        """
        # Try npx --dry-run first (fast when it works)
        try:
            result = subprocess.run(
                ["npx", "--dry-run", package_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # Fall through to directory scan

        # Fallback: scan npm cache directory directly
        return self._scan_npx_cache_directory(package_name)

    def _scan_npx_cache_directory(self, package_name: str) -> bool:
        """Scan npm npx cache directory for the package.

        Args:
            package_name: Package name to look for (e.g., 'firecrawl-mcp')

        Returns:
            True if package is found in cache
        """
        # Get npm cache directory
        try:
            result = subprocess.run(
                ["npm", "config", "get", "cache"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False
            npm_cache = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Default fallback
            npm_cache = Path.home() / ".npm"

        npx_cache_dir = Path(npm_cache) / "_npx"
        if not npx_cache_dir.exists():
            return False

        # Normalize package name (remove version suffix)
        clean_name = self._normalize_npx_package_name(package_name)

        # Scan all cache entries
        try:
            for entry in npx_cache_dir.iterdir():
                if not entry.is_dir():
                    continue
                package_json = entry / "package.json"
                if not package_json.exists():
                    continue

                try:
                    content = package_json.read_text()
                    # Quick string check before parsing JSON
                    if f'"{clean_name}"' in content:
                        import json

                        data = json.loads(content)
                        deps = data.get("dependencies", {})
                        if clean_name in deps:
                            return True
                except (OSError, json.JSONDecodeError):
                    continue
        except (OSError, PermissionError):
            pass

        return False

    async def connect(self) -> ClientSession:
        """Connect to the MCP server via stdio.

        Returns:
            Connected ClientSession

        Raises:
            MCPServerNotInstalledError: If the MCP server package is not installed
            MCPConnectionError: If connection fails
        """
        import asyncio

        # Validate command exists and MCP server is installed (no auto-download)
        self._validate_command()

        command = self.config.command
        args = list(self.config.args)
        if command == "npx":
            resolved_command = self._resolve_direct_npx_binary(args)
            if resolved_command is not None:
                command, args = resolved_command

        # Prepare server parameters
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=self.config.env if self.config.env else None,
        )

        try:
            # Use AsyncExitStack to properly manage async context managers
            self._exit_stack = AsyncExitStack()

            # Enter stdio_client context - this starts the subprocess
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )

            # ClientSession must be entered as an async context manager so its
            # internal receive loop starts before initialize().
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            # Initialize the session (perform MCP handshake) with 30 second timeout
            # Some servers like Context7 need more time for initial setup
            try:
                await asyncio.wait_for(self._session.initialize(), timeout=30.0)
            except TimeoutError as err:
                raise MCPConnectionError(
                    f"MCP server '{self.config.name}' initialization timeout (30s). "
                    f"The server may be hanging or not responding."
                ) from err

            return self._session

        except Exception as e:
            # Clean up on failure - ignore cleanup errors
            if self._exit_stack:
                with suppress(Exception):
                    await self._exit_stack.aclose()
                self._exit_stack = None
            self._session = None
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.config.name}': {e}"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None

        self._session = None

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
        self._exit_stack: AsyncExitStack | None = None

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
            raise MCPConnectionError(f"HTTP transport requires mcp>=1.1.0: {e}") from e

        try:
            # Use AsyncExitStack to properly manage async context managers
            self._exit_stack = AsyncExitStack()

            # Enter streamable_http_client context
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                streamable_http_client(self.config.url)
            )

            # ClientSession must be entered as an async context manager so its
            # internal receive loop starts before initialize().
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()

            return self._session

        except Exception as e:
            # Clean up on failure - ignore cleanup errors
            if self._exit_stack:
                with suppress(Exception):
                    await self._exit_stack.aclose()
                self._exit_stack = None
            self._session = None
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.config.name}' at {self.config.url}: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None

        self._session = None

    @property
    def session(self) -> ClientSession | None:
        """Get the current session if connected."""
        return self._session

    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._session is not None
