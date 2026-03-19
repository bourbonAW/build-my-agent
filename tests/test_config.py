"""Tests for configuration system."""

import os
import tempfile
from pathlib import Path

import pytest
import toml

from bourbon.config import Config, ConfigManager


class TestConfig:
    """Test configuration dataclass."""

    def test_default_config(self):
        """Test config with default values."""
        config = Config()
        assert config.llm.default_provider == "anthropic"
        assert config.ui.theme == "dracula"
        assert config.tools.bash.timeout_seconds == 120

    def test_config_from_dict(self):
        """Test loading config from dictionary."""
        data = {
            "llm": {
                "default_provider": "openai",
                "openai": {"api_key": "test-key", "model": "gpt-4o"},
            },
            "ui": {"theme": "monokai"},
        }
        config = Config.from_dict(data)
        assert config.llm.default_provider == "openai"
        assert config.llm.openai.api_key == "test-key"
        assert config.ui.theme == "monokai"


class TestConfigManager:
    """Test configuration manager."""

    def test_get_config_dir(self):
        """Test config directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            expected = Path(tmpdir) / ".bourbon"
            assert manager.get_config_dir() == expected

    def test_ensure_config_dir_creates_directory(self):
        """Test that ensure_config_dir creates the directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()
            assert manager.get_config_dir().exists()

    def test_create_default_config(self):
        """Test creating default config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()

            # Create with test API key
            config = manager.create_default_config(anthropic_key="test-ant-key")

            assert config.llm.anthropic.api_key == "test-ant-key"
            assert config.llm.default_provider == "anthropic"

            # Verify file was created
            config_path = manager.get_config_path()
            assert config_path.exists()

            # Verify it's valid TOML
            data = toml.load(config_path)
            assert data["llm"]["default_provider"] == "anthropic"

    def test_load_config(self):
        """Test loading existing config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()

            # Create config first
            manager.create_default_config(anthropic_key="my-key")

            # Load it
            config = manager.load_config()
            assert config.llm.anthropic.api_key == "my-key"

    def test_load_config_missing_file(self):
        """Test loading when config doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["HOME"] = tmpdir
            manager = ConfigManager()
            manager.ensure_config_dir()

            # Should raise error with helpful message
            with pytest.raises(FileNotFoundError):
                manager.load_config()
