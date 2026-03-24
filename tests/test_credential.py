"""Tests for credential environment filtering."""

from bourbon.sandbox.credential import CredentialManager


class TestCredentialManager:
    """Test CredentialManager environment filtering."""

    def test_clean_env_passthrough_only(self):
        """Test that only passthrough variables are kept."""
        source_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/test",
            "CUSTOM_VAR": "value",
        }

        result = CredentialManager.clean_env(["PATH", "CUSTOM_VAR"], source_env=source_env)

        assert result == {"PATH": "/usr/bin", "CUSTOM_VAR": "value"}

    def test_clean_env_sensitive_pattern_blocks_even_if_passthrough(self):
        """Test that sensitive variables are blocked even when passthrough is allowed."""
        source_env = {
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "secret",
        }

        result = CredentialManager.clean_env(["PATH", "OPENAI_API_KEY"], source_env=source_env)

        assert result == {"PATH": "/usr/bin"}

    def test_clean_env_anthropic_key_blocked(self):
        """Test that Anthropic credentials are blocked by pattern."""
        source_env = {
            "ANTHROPIC_API_KEY": "secret",
        }

        result = CredentialManager.clean_env(["ANTHROPIC_API_KEY"], source_env=source_env)

        assert result == {}

    def test_clean_env_empty_passthrough_returns_empty_dict(self):
        """Test that an empty passthrough list returns no variables."""
        source_env = {
            "PATH": "/usr/bin",
            "CUSTOM_VAR": "value",
        }

        result = CredentialManager.clean_env([], source_env=source_env)

        assert result == {}

    def test_clean_env_defaults_to_os_environ(self, monkeypatch):
        """Test that os.environ is used when source_env is not provided."""
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("CUSTOM_VAR", "value")
        monkeypatch.setenv("OPENAI_API_KEY", "secret")

        result = CredentialManager.clean_env(["PATH", "CUSTOM_VAR", "OPENAI_API_KEY"])

        assert result == {"PATH": "/usr/bin", "CUSTOM_VAR": "value"}
