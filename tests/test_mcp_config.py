"""Tests for MCP configuration."""

import pytest

from bourbon.mcp_client.config import MCPConfig, MCPServerConfig


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""

    def test_basic_stdio_config(self):
        """Test basic stdio server config."""
        config = MCPServerConfig(
            name="test",
            transport="stdio",
            command="echo",
            args=["hello"],
        )
        assert config.name == "test"
        assert config.transport == "stdio"
        assert config.command == "echo"
        assert config.args == ["hello"]
        assert config.enabled is True

    def test_basic_http_config(self):
        """Test basic HTTP server config."""
        config = MCPServerConfig(
            name="remote",
            transport="http",
            url="http://localhost:3000/mcp",
        )
        assert config.name == "remote"
        assert config.transport == "http"
        assert config.url == "http://localhost:3000/mcp"

    def test_stdio_requires_command(self):
        """Test that stdio transport requires command."""
        with pytest.raises(ValueError, match="command is required"):
            MCPServerConfig(
                name="test",
                transport="stdio",
            )

    def test_http_requires_url(self):
        """Test that HTTP transport requires URL."""
        with pytest.raises(ValueError, match="url is required"):
            MCPServerConfig(
                name="test",
                transport="http",
            )

    def test_invalid_transport(self):
        """Test that invalid transport raises error."""
        with pytest.raises(ValueError, match="Invalid transport"):
            MCPServerConfig(
                name="test",
                transport="invalid",
                command="echo",
            )

    def test_from_dict_stdio(self):
        """Test creating config from dict for stdio."""
        data = {
            "name": "fetch",
            "transport": "stdio",
            "command": "uvx",
            "args": ["mcp-server-fetch"],
            "enabled": True,
        }
        config = MCPServerConfig.from_dict(data)
        assert config.name == "fetch"
        assert config.command == "uvx"
        assert config.args == ["mcp-server-fetch"]

    def test_from_dict_http(self):
        """Test creating config from dict for HTTP."""
        data = {
            "name": "api",
            "transport": "http",
            "url": "http://localhost:3000/mcp",
        }
        config = MCPServerConfig.from_dict(data)
        assert config.name == "api"
        assert config.url == "http://localhost:3000/mcp"

    def test_from_dict_missing_name(self):
        """Test that missing name raises error."""
        with pytest.raises(ValueError, match="missing required 'name' field"):
            MCPServerConfig.from_dict(
                {
                    "transport": "stdio",
                    "command": "echo",
                }
            )

    def test_to_dict_stdio(self):
        """Test serialization of stdio config."""
        config = MCPServerConfig(
            name="test",
            transport="stdio",
            command="echo",
            args=["hello"],
            env={"KEY": "value"},
        )
        data = config.to_dict()
        assert data["name"] == "test"
        assert data["transport"] == "stdio"
        assert data["command"] == "echo"
        assert data["args"] == ["hello"]
        assert data["env"] == {"KEY": "value"}

    def test_to_dict_http(self):
        """Test serialization of HTTP config."""
        config = MCPServerConfig(
            name="api",
            transport="http",
            url="http://localhost:3000/mcp",
            headers={"Authorization": "Bearer token"},
            timeout=60.0,
        )
        data = config.to_dict()
        assert data["name"] == "api"
        assert data["transport"] == "http"
        assert data["url"] == "http://localhost:3000/mcp"
        assert data["headers"] == {"Authorization": "Bearer token"}
        assert data["timeout"] == 60.0
        assert "command" not in data

    def test_retry_settings(self):
        """Test retry configuration."""
        config = MCPServerConfig(
            name="remote",
            transport="http",
            url="http://example.com/mcp",
            max_retries=5,
            retry_delay=2.0,
        )
        assert config.max_retries == 5
        assert config.retry_delay == 2.0


class TestMCPConfig:
    """Tests for MCPConfig."""

    def test_default_config(self):
        """Test default config values."""
        config = MCPConfig()
        assert config.enabled is True
        assert config.default_timeout == 30
        assert config.servers == []

    def test_from_dict_empty(self):
        """Test creating from empty dict."""
        config = MCPConfig.from_dict({})
        assert config.enabled is True
        assert config.servers == []

    def test_from_dict_none(self):
        """Test creating from None."""
        config = MCPConfig.from_dict(None)
        assert config.enabled is True
        assert config.servers == []

    def test_from_dict_with_servers(self):
        """Test creating from dict with servers."""
        data = {
            "enabled": True,
            "default_timeout": 60,
            "servers": [
                {
                    "name": "fetch",
                    "transport": "stdio",
                    "command": "uvx",
                    "args": ["mcp-server-fetch"],
                },
                {
                    "name": "api",
                    "transport": "http",
                    "url": "http://localhost:3000/mcp",
                },
            ],
        }
        config = MCPConfig.from_dict(data)
        assert config.enabled is True
        assert config.default_timeout == 60
        assert len(config.servers) == 2
        assert config.servers[0].name == "fetch"
        assert config.servers[1].name == "api"

    def test_from_dict_skips_invalid_server(self):
        """Test that invalid servers are skipped."""
        data = {
            "servers": [
                {
                    "name": "valid",
                    "transport": "stdio",
                    "command": "echo",
                },
                {
                    "transport": "stdio",  # Missing name
                    "command": "echo",
                },
            ],
        }
        config = MCPConfig.from_dict(data)
        assert len(config.servers) == 1
        assert config.servers[0].name == "valid"

    def test_to_dict(self):
        """Test serialization."""
        config = MCPConfig(
            enabled=False,
            default_timeout=45,
            servers=[
                MCPServerConfig(name="test", transport="stdio", command="echo"),
            ],
        )
        data = config.to_dict()
        assert data["enabled"] is False
        assert data["default_timeout"] == 45
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "test"

    def test_get_enabled_servers(self):
        """Test getting only enabled servers."""
        config = MCPConfig(
            enabled=True,
            servers=[
                MCPServerConfig(name="enabled1", transport="stdio", command="echo"),
                MCPServerConfig(name="disabled", transport="stdio", command="echo", enabled=False),
                MCPServerConfig(name="enabled2", transport="stdio", command="echo"),
            ],
        )
        enabled = config.get_enabled_servers()
        assert len(enabled) == 2
        assert enabled[0].name == "enabled1"
        assert enabled[1].name == "enabled2"

    def test_get_enabled_servers_when_disabled(self):
        """Test that no servers returned when MCP disabled."""
        config = MCPConfig(
            enabled=False,
            servers=[
                MCPServerConfig(name="test", transport="stdio", command="echo"),
            ],
        )
        enabled = config.get_enabled_servers()
        assert enabled == []
