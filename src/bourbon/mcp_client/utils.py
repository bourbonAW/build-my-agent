"""Utility functions for MCP Client integration.

Helper functions for formatting and error handling.
"""

from bourbon.mcp_client.config import MCPServerConfig


def format_server_info(config: MCPServerConfig) -> str:
    """Format server configuration for display.
    
    Args:
        config: Server configuration
        
    Returns:
        Formatted string description
    """
    parts = [
        f"Server: {config.name}",
        f"  Transport: {config.transport}",
        f"  Enabled: {config.enabled}",
    ]
    
    if config.transport == "stdio":
        parts.append(f"  Command: {config.command}")
        if config.args:
            parts.append(f"  Args: {' '.join(config.args)}")
        if config.env:
            parts.append(f"  Env: {', '.join(config.env.keys())}")
    elif config.transport == "http":
        parts.append(f"  URL: {config.url}")
    
    return "\n".join(parts)


def expand_env_vars(value: str) -> str:
    """Expand environment variables in a string.
    
    Supports ${VAR} syntax.
    
    Args:
        value: String potentially containing env var references
        
    Returns:
        String with env vars expanded
    """
    import os
    import re
    
    def replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    
    return re.sub(r'\$\{(\w+)\}', replace_var, value)


def expand_env_vars_in_dict(data: dict[str, str]) -> dict[str, str]:
    """Expand environment variables in all values of a dictionary.
    
    Args:
        data: Dictionary with string values
        
    Returns:
        New dictionary with expanded values
    """
    return {k: expand_env_vars(v) for k, v in data.items()}
