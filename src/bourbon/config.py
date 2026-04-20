"""Configuration management for Bourbon."""

from dataclasses import dataclass, field
from pathlib import Path

import toml

from bourbon.mcp_client.config import MCPConfig


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


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
    max_tool_rounds: int = 50  # Maximum tool execution rounds per user request


@dataclass
class TasksConfig:
    """Task persistence configuration."""

    enabled: bool = True
    storage_dir: str = "~/.bourbon/tasks"
    default_list_id: str = "default"


@dataclass
class MemoryConfig:
    """Memory system configuration."""

    enabled: bool = True
    storage_dir: str = "~/.bourbon/projects"
    auto_flush_on_compact: bool = True
    auto_extract: bool = False
    recall_limit: int = 8
    recall_transcript_session_limit: int = 10
    memory_md_token_limit: int = 1200
    user_md_token_limit: int = 600
    core_block_token_limit: int = 1200


@dataclass
class ObservabilityConfig:
    """OpenTelemetry observability configuration."""

    enabled: bool = False
    service_name: str = "bourbon"
    otlp_endpoint: str = ""
    otlp_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ObservabilityConfig":
        return cls(
            enabled=bool(data.get("enabled", False)),
            service_name=str(data.get("service_name", "bourbon")),
            otlp_endpoint=str(data.get("otlp_endpoint", "")),
            otlp_headers=dict(data.get("otlp_headers", {})),
        )


@dataclass
class Config:
    """Root configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    tasks: TasksConfig = field(default_factory=TasksConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    access_control: dict = field(
        default_factory=lambda: {
            "default_action": "allow",
            "file": {
                "allow": ["{workdir}/**"],
                "deny": ["~/.ssh/**", "~/.aws/**"],
                "mandatory_deny": ["~/.ssh/**"],
            },
            "command": {
                # Keep in sync with run_bash()'s `dangerous` list in tools/base.py,
                # which acts as a safety-net fallback when sandbox is disabled.
                "deny_patterns": [
                    "rm -rf /",
                    "sudo *",
                    "shutdown",
                    "reboot",
                    "> /dev/sda",
                    "mkfs.",
                ],
                "need_approval_patterns": ["pip install *", "apt *"],
            },
        }
    )
    sandbox: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "provider": "auto",
            "filesystem": {
                "writable": ["{workdir}"],
                "readonly": ["/usr", "/lib"],
                "deny": ["~/.ssh", "~/.aws"],
            },
            "network": {"enabled": False, "allow_domains": []},
            "resources": {
                "timeout": 120,
                "max_memory": "512M",
                "max_output": 50000,
            },
            "credentials": {
                "clean_env": True,
                "passthrough_vars": ["PATH", "HOME", "LANG"],
            },
            "docker": {
                "image": "python:3.11-slim",
                "pull_policy": "if-not-present",
                "user": "nobody",
            },
        }
    )
    audit: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "log_dir": "~/.bourbon/audit/",
            "format": "jsonl",
        }
    )

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
        tasks_data = data.get("tasks", {})
        memory_data = data.get("memory", {})
        observability_data = data.get("observability", {})
        mcp_data = data.get("mcp", {})
        access_control_data = data.get("access_control", {})
        sandbox_data = data.get("sandbox", {})
        audit_data = data.get("audit", {})

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
            tasks=TasksConfig(**tasks_data),
            memory=MemoryConfig(**memory_data),
            observability=ObservabilityConfig.from_dict(observability_data),
            mcp=MCPConfig.from_dict(mcp_data),
            access_control=_deep_merge(Config().access_control, access_control_data),
            sandbox=_deep_merge(Config().sandbox, sandbox_data),
            audit=_deep_merge(Config().audit, audit_data),
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
                "max_tool_rounds": self.ui.max_tool_rounds,
            },
            "tasks": {
                "enabled": self.tasks.enabled,
                "storage_dir": self.tasks.storage_dir,
                "default_list_id": self.tasks.default_list_id,
            },
            "memory": {
                "enabled": self.memory.enabled,
                "storage_dir": self.memory.storage_dir,
                "auto_flush_on_compact": self.memory.auto_flush_on_compact,
                "auto_extract": self.memory.auto_extract,
                "recall_limit": self.memory.recall_limit,
                "recall_transcript_session_limit": self.memory.recall_transcript_session_limit,
                "memory_md_token_limit": self.memory.memory_md_token_limit,
                "user_md_token_limit": self.memory.user_md_token_limit,
                "core_block_token_limit": self.memory.core_block_token_limit,
            },
            "observability": {
                "enabled": self.observability.enabled,
                "service_name": self.observability.service_name,
                "otlp_endpoint": self.observability.otlp_endpoint,
                "otlp_headers": self.observability.otlp_headers,
            },
            "mcp": self.mcp.to_dict(),
            "access_control": self.access_control,
            "sandbox": self.sandbox,
            "audit": self.audit,
        }


class ConfigManager:
    """Manages configuration files."""

    CONFIG_DIR_NAME = ".bourbon"
    CONFIG_FILE_NAME = "config.toml"

    def __init__(self, home_dir: Path | None = None):
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
                f"Configuration not found at {config_path}\nRun 'bourbon --init' to create one."
            )

        with open(config_path) as f:
            data = toml.load(f)

        return Config.from_dict(data)

    def save_config(self, config: Config) -> None:
        """Save configuration to file."""
        self.ensure_config_dir()
        config_path = self.get_config_path()

        with open(config_path, "w") as f:
            toml.dump(config.to_dict(), f)

        config_path.chmod(0o600)
