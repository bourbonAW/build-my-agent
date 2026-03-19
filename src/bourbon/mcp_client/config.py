"""MCP Client configuration for Bourbon.

Defines configuration structures for MCP server connections.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection.
    
    Supports both stdio and HTTP transports.
    """
    
    name: str
    transport: str  # "stdio" or "http"
    enabled: bool = True
    
    # Connection retry settings
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds between retries
    
    # stdio transport settings
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    
    # http transport settings
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)  # Custom HTTP headers
    timeout: float | None = None  # Connection timeout override
    
    def __post_init__(self):
        """Validate configuration after creation."""
        if self.transport not in ("stdio", "http"):
            raise ValueError(f"Invalid transport: {self.transport}. Must be 'stdio' or 'http'")
        
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"MCP server '{self.name}': command is required for stdio transport")
        elif self.transport == "http":
            if not self.url:
                raise ValueError(f"MCP server '{self.name}': url is required for http transport")
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerConfig":
        """Create MCPServerConfig from dictionary.
        
        Args:
            data: Dictionary containing server configuration
            
        Returns:
            MCPServerConfig instance
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        name = data.get("name")
        if not name:
            raise ValueError("MCP server configuration missing required 'name' field")
        
        transport = data.get("transport", "stdio")
        enabled = data.get("enabled", True)
        max_retries = data.get("max_retries", 3)
        retry_delay = data.get("retry_delay", 1.0)
        
        return cls(
            name=name,
            transport=transport,
            enabled=enabled,
            max_retries=max_retries,
            retry_delay=retry_delay,
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url"),
            headers=data.get("headers", {}),
            timeout=data.get("timeout"),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
        }
        
        if self.transport == "stdio":
            result["command"] = self.command
            if self.args:
                result["args"] = self.args
            if self.env:
                result["env"] = self.env
        elif self.transport == "http":
            result["url"] = self.url
            if self.headers:
                result["headers"] = self.headers
            if self.timeout is not None:
                result["timeout"] = self.timeout
        
        return result


@dataclass
class MCPConfig:
    """MCP Client global configuration.
    
    Manages MCP client settings and server configurations.
    """
    
    enabled: bool = True
    default_timeout: int = 30  # seconds for tool calls
    servers: list[MCPServerConfig] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MCPConfig":
        """Create MCPConfig from dictionary.
        
        Args:
            data: Dictionary containing MCP configuration, or None for defaults
            
        Returns:
            MCPConfig instance
        """
        if data is None:
            return cls()
        
        enabled = data.get("enabled", True)
        default_timeout = data.get("default_timeout", 30)
        
        # Parse servers array
        servers = []
        servers_data = data.get("servers", [])
        if isinstance(servers_data, list):
            for server_data in servers_data:
                try:
                    server_config = MCPServerConfig.from_dict(server_data)
                    servers.append(server_config)
                except ValueError as e:
                    # Log warning but continue with other servers
                    # In production, this should be logged properly
                    print(f"Warning: Skipping invalid MCP server config: {e}")
        
        return cls(
            enabled=enabled,
            default_timeout=default_timeout,
            servers=servers,
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "default_timeout": self.default_timeout,
            "servers": [server.to_dict() for server in self.servers],
        }
    
    def get_enabled_servers(self) -> list[MCPServerConfig]:
        """Get list of enabled server configurations.
        
        Returns:
            List of enabled MCPServerConfig instances
        """
        if not self.enabled:
            return []
        return [server for server in self.servers if server.enabled]
