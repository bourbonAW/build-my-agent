"""Configuration management for Bourbon."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import toml


@dataclass
class AnthropicConfig:
    """Anthropic LLM configuration."""

    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 8000
    temperature: float = 0.7


@dataclass
class OpenAIConfig:
    """OpenAI LLM configuration."""

    api_key: str = ""
    model: str = "gpt-4o"
    base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 8000
    temperature: float = 0.7


@dataclass
class LLMConfig:
    """LLM configuration container."""

    default_provider: str = "anthropic"
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)


@dataclass
class BashConfig:
    """Bash tool configuration."""

    allowed_commands: list[str] = field(default_factory=lambda: ["*"])
    blocked_commands: list[str] = field(
        default_factory=lambda: ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/sda"]
    )
    timeout_seconds: int = 120


@dataclass
class RgConfig:
    """ripgrep tool configuration."""

    binary_path: str = "rg"
    default_args: list[str] = field(
        default_factory=lambda: ["--smart-case", "--hidden", "--glob", "!.git"]
    )
    max_results: int = 100


@dataclass
class AstGrepConfig:
    """ast-grep tool configuration."""

    binary_path: str = "ast-grep"
    default_args: list[str] = field(default_factory=lambda: ["--json"])


@dataclass
class ToolsConfig:
    """Tools configuration container."""

    bash: BashConfig = field(default_factory=BashConfig)
    rg: RgConfig = field(default_factory=RgConfig)
    ast_grep: AstGrepConfig = field(default_factory=AstGrepConfig)


@dataclass
class UIConfig:
    """UI configuration."""

    theme: str = "dracula"
    auto_compact: bool = True
    token_threshold: int = 100000
    show_token_count: bool = True
    syntax_highlighting: bool = True


@dataclass
class Config:
    """Root configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary."""
        llm_data = data.get("llm", {})
        anthropic_data = llm_data.get("anthropic", {})
        openai_data = llm_data.get("openai", {})

        tools_data = data.get("tools", {})
        bash_data = tools_data.get("bash", {})
        rg_data = tools_data.get("rg", {})
        ast_grep_data = tools_data.get("ast_grep", {})

        ui_data = data.get("ui", {})

        return cls(
            llm=LLMConfig(
                default_provider=llm_data.get("default_provider", "anthropic"),
                anthropic=AnthropicConfig(**anthropic_data),
                openai=OpenAIConfig(**openai_data),
            ),
            tools=ToolsConfig(
                bash=BashConfig(**bash_data),
                rg=RgConfig(**rg_data),
                ast_grep=AstGrepConfig(**ast_grep_data),
            ),
            ui=UIConfig(**ui_data),
        )

    def to_dict(self) -> dict:
        """Convert Config to dictionary."""
        return {
            "llm": {
                "default_provider": self.llm.default_provider,
                "anthropic": {
                    "api_key": self.llm.anthropic.api_key,
                    "model": self.llm.anthropic.model,
                    "base_url": self.llm.anthropic.base_url,
                    "max_tokens": self.llm.anthropic.max_tokens,
                    "temperature": self.llm.anthropic.temperature,
                },
                "openai": {
                    "api_key": self.llm.openai.api_key,
                    "model": self.llm.openai.model,
                    "base_url": self.llm.openai.base_url,
                    "max_tokens": self.llm.openai.max_tokens,
                    "temperature": self.llm.openai.temperature,
                },
            },
            "tools": {
                "bash": {
                    "allowed_commands": self.tools.bash.allowed_commands,
                    "blocked_commands": self.tools.bash.blocked_commands,
                    "timeout_seconds": self.tools.bash.timeout_seconds,
                },
                "rg": {
                    "binary_path": self.tools.rg.binary_path,
                    "default_args": self.tools.rg.default_args,
                    "max_results": self.tools.rg.max_results,
                },
                "ast_grep": {
                    "binary_path": self.tools.ast_grep.binary_path,
                    "default_args": self.tools.ast_grep.default_args,
                },
            },
            "ui": {
                "theme": self.ui.theme,
                "auto_compact": self.ui.auto_compact,
                "token_threshold": self.ui.token_threshold,
                "show_token_count": self.ui.show_token_count,
                "syntax_highlighting": self.ui.syntax_highlighting,
            },
        }


class ConfigManager:
    """Manages configuration files."""

    CONFIG_DIR_NAME = ".bourbon"
    CONFIG_FILE_NAME = "config.toml"

    def __init__(self, home_dir: Optional[Path] = None):
        """Initialize with optional home directory override."""
        self._home = home_dir or Path.home()

    def get_config_dir(self) -> Path:
        """Get configuration directory path."""
        return self._home / self.CONFIG_DIR_NAME

    def get_config_path(self) -> Path:
        """Get configuration file path."""
        return self.get_config_dir() / self.CONFIG_FILE_NAME

    def ensure_config_dir(self) -> Path:
        """Ensure configuration directory exists."""
        config_dir = self.get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    def create_default_config(self, anthropic_key: str = "", openai_key: str = "") -> Config:
        """Create default configuration file."""
        self.ensure_config_dir()

        config = Config()
        config.llm.anthropic.api_key = anthropic_key
        config.llm.openai.api_key = openai_key

        config_path = self.get_config_path()
        with open(config_path, "w") as f:
            toml.dump(config.to_dict(), f)

        # Secure the file
        config_path.chmod(0o600)

        return config

    def load_config(self) -> Config:
        """Load configuration from file."""
        config_path = self.get_config_path()

        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration not found at {config_path}\n" f"Run 'bourbon --init' to create one."
            )

        with open(config_path, "r") as f:
            data = toml.load(f)

        return Config.from_dict(data)

    def save_config(self, config: Config) -> None:
        """Save configuration to file."""
        self.ensure_config_dir()
        config_path = self.get_config_path()

        with open(config_path, "w") as f:
            toml.dump(config.to_dict(), f)

        config_path.chmod(0o600)
