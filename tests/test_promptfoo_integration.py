from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def _load_promptfoo_case_paths() -> list[str]:
    config_path = ROOT / "promptfooconfig.yaml"
    paths: list[str] = []

    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- file://"):
            paths.append(stripped.removeprefix("- file://"))

    return paths


def _load_top_level_section(section_name: str) -> str:
    lines = (ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8").splitlines()
    collected: list[str] = []
    in_section = False

    for line in lines:
        if in_section:
            if line and not line.startswith(" "):
                break
            collected.append(line)
        elif line == f"{section_name}:":
            in_section = True
            collected.append(line)

    return "\n".join(collected)


def test_promptfoo_config_only_references_existing_case_files() -> None:
    missing = [path for path in _load_promptfoo_case_paths() if not (ROOT / path).exists()]
    assert not missing


def test_promptfoo_config_sets_agent_provider_as_default() -> None:
    config_text = (ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8")
    assert "defaultTest:" in config_text
    assert "provider: python:evals/promptfoo_provider.py" in config_text


def test_promptfoo_global_providers_only_include_agent_provider() -> None:
    providers_block = _load_top_level_section("providers")
    assert "python:evals/promptfoo_provider.py" in providers_block
    assert "python:evals/promptfoo_artifact_provider.py" not in providers_block


def test_promptfoo_global_provider_uses_project_virtualenv_python() -> None:
    providers_block = _load_top_level_section("providers")
    assert "pythonExecutable: .venv/bin/python" in providers_block


def test_promptfoo_provider_installs_toml_compat_shim(monkeypatch, tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from evals import promptfoo_provider

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "toml":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "toml", raising=False)

    promptfoo_provider._install_toml_compat()
    toml = sys.modules["toml"]

    config_path = tmp_path / "config.toml"
    config_path.write_text("[llm]\ndefault_provider = 'anthropic'\n", encoding="utf-8")

    with config_path.open("rb") as fh:
        data = toml.load(fh)

    assert data["llm"]["default_provider"] == "anthropic"


def test_promptfoo_provider_supports_inline_setup_files(monkeypatch) -> None:
    sys.path.insert(0, str(ROOT))
    from evals import promptfoo_provider

    fake_agent_module = ModuleType("bourbon.agent")
    fake_config_module = ModuleType("bourbon.config")

    class FakeAgent:
        def __init__(self, config: dict, workdir: Path) -> None:
            self.workdir = workdir
            self.audit = SimpleNamespace(enabled=False)
            self.skills = SimpleNamespace(_skills={})

        def reset_token_usage(self) -> None:
            return None

        def _build_system_prompt(self) -> str:
            return "system-prompt"

        def step(self, prompt: str) -> str:
            config_file = self.workdir / "config.toml"
            if not config_file.exists():
                return "missing config.toml"
            return config_file.read_text(encoding="utf-8")

        def get_token_usage(self) -> dict[str, int]:
            return {}

    class FakeConfigManager:
        def load_config(self) -> dict:
            return {}

    fake_agent_module.Agent = FakeAgent
    fake_config_module.ConfigManager = FakeConfigManager

    monkeypatch.setitem(sys.modules, "bourbon.agent", fake_agent_module)
    monkeypatch.setitem(sys.modules, "bourbon.config", fake_config_module)

    result = promptfoo_provider.call_api(
        "ignored",
        {
            "vars": {
                "case_id": "inline-setup",
                "setup_files": {
                    "config.toml": "[mcp]\nenabled = true\ndefault_timeout = 60\n",
                },
            }
        },
        {},
    )

    payload = json.loads(result["output"])
    assert "[mcp]" in payload["text"]
    assert "default_timeout = 60" in payload["text"]
