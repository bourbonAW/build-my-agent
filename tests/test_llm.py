"""Tests for LLM client."""

import pytest

from bourbon.config import Config
from bourbon.llm import LLMError, create_client


class TestCreateClient:
    """Test client creation."""

    def test_missing_anthropic_key(self):
        """Test error when Anthropic key is missing."""
        config = Config()
        config.llm.default_provider = "anthropic"
        config.llm.anthropic.api_key = ""

        with pytest.raises(LLMError, match="API key not configured"):
            create_client(config)

    def test_missing_openai_key(self):
        """Test error when OpenAI key is missing."""
        config = Config()
        config.llm.default_provider = "openai"
        config.llm.openai.api_key = ""

        with pytest.raises(LLMError, match="API key not configured"):
            create_client(config)

    def test_unknown_provider(self):
        """Test error for unknown provider."""
        config = Config()
        config.llm.default_provider = "unknown"

        with pytest.raises(LLMError, match="Unknown provider"):
            create_client(config)

    def test_create_anthropic_client(self):
        """Test creating Anthropic client - skipped due to Python 3.14 compat."""
        pytest.skip("Python 3.14 beta compatibility issue with pydantic")

    def test_create_openai_client(self):
        """Test creating OpenAI client - skipped due to Python 3.14 compat."""
        pytest.skip("Python 3.14 beta compatibility issue with pydantic")
