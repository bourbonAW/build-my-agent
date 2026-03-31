"""Promptfoo provider for Bourbon agent evaluation.

Wraps Agent.step() — sets up workspace from fixtures, runs the agent,
and returns structured JSON output with text + workdir for assertions.
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

_workdirs_to_cleanup: list[Path] = []


def _cleanup_workdirs():
    """Clean up all temporary workdirs at process exit."""
    if os.environ.get("EVAL_KEEP_ARTIFACTS"):
        return
    for workdir in _workdirs_to_cleanup:
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)


atexit.register(_cleanup_workdirs)


def _install_toml_compat() -> None:
    """Provide a minimal toml module via stdlib tomllib for promptfoo workers."""
    try:
        import toml  # noqa: F401

        return
    except ModuleNotFoundError:
        import tomllib

    compat = ModuleType("toml")

    def _load(fp):
        return tomllib.load(fp)

    def _loads(text: str):
        return tomllib.loads(text)

    def _unsupported(*args, **kwargs):
        raise NotImplementedError("toml dump support is unavailable in promptfoo provider shim")

    compat.load = _load
    compat.loads = _loads
    compat.dump = _unsupported
    compat.dumps = _unsupported
    compat.TomlDecodeError = tomllib.TOMLDecodeError
    sys.modules["toml"] = compat


def _get_vars(options: dict) -> dict:
    """Support promptfoo passing vars at different levels by version/provider path."""
    config = options.get("config", {})
    vars_ = config.get("vars", {}) if "vars" not in options else options.get("vars", {})
    return vars_ or options.get("vars", {})


def _get_setup_files(vars_: dict) -> dict[str, str]:
    """Normalize inline workspace files from supported vars keys."""
    setup_files: dict[str, str] = {}
    for key in ("setup_files", "create_files", "files"):
        value = vars_.get(key)
        if isinstance(value, dict):
            setup_files.update({str(path): str(content) for path, content in value.items()})
    return setup_files


def _write_setup_files(workdir: Path, setup_files: dict[str, str]) -> None:
    for rel_path, content in setup_files.items():
        file_path = workdir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


def _setup_workspace(
    fixture: str | None,
    case_id: str,
    setup_files: dict[str, str] | None = None,
) -> Path:
    """Create temp workdir, populate fixture contents, and write inline setup files."""
    workdir = Path(tempfile.mkdtemp(prefix=f"eval_{case_id}_"))
    _workdirs_to_cleanup.append(workdir)

    if fixture:
        evals_dir = Path(__file__).parent
        for candidate in [
            evals_dir / "fixtures" / fixture,
            evals_dir / "fixtures" / fixture.split("/")[-1],
        ]:
            if candidate.exists():
                for item in candidate.iterdir():
                    dest = workdir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)
                break

    if setup_files:
        _write_setup_files(workdir, setup_files)

    return workdir


def call_api(prompt, options, context):
    """Promptfoo calls this for each test case.

    Expects:
        vars.fixture (optional): fixture directory name
        vars.skill (optional): skill to activate
        vars.case_id (optional): identifier for temp dir naming

    Returns:
        {"output": json.dumps({"text": ..., "workdir": ..., "duration_ms": ...}),
         "tokenUsage": {...}}
    """
    vars_ = _get_vars(options)
    fixture = vars_.get("fixture")
    skill = vars_.get("skill")
    case_id = vars_.get("case_id", "unknown")
    setup_files = _get_setup_files(vars_)

    start = time.time()
    workdir = _setup_workspace(fixture, case_id, setup_files=setup_files)
    original_cwd = os.getcwd()

    try:
        os.chdir(workdir)

        _install_toml_compat()
        from bourbon.agent import Agent
        from bourbon.config import ConfigManager

        config = ConfigManager().load_config()
        agent = Agent(config=config, workdir=workdir)
        agent.reset_token_usage()

        # Redirect audit log to workdir so assertions can read it
        if hasattr(agent, "audit") and agent.audit.enabled:
            audit_log_path = workdir / "audit.jsonl"
            audit_log_path.touch(exist_ok=True)
            agent.audit.log_file = audit_log_path

        # Configure skill if specified
        if skill:
            try:
                agent.skills._discover()
                agent.skills.activate(skill)
            except Exception:
                pass  # Skill activation failure is test-observable
            agent.system_prompt = agent._build_system_prompt()
        else:
            agent.skills._skills = {}
            agent.system_prompt = agent._build_system_prompt()

        output = agent.step(prompt)
        duration_ms = int((time.time() - start) * 1000)
        token_usage = agent.get_token_usage()

        return {
            "output": json.dumps(
                {"text": output, "workdir": str(workdir), "duration_ms": duration_ms}
            ),
            "tokenUsage": {
                "total": token_usage.get("total_tokens", 0),
                "prompt": token_usage.get("input_tokens", 0),
                "completion": token_usage.get("output_tokens", 0),
            },
        }

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "output": json.dumps(
                {
                    "text": f"Error: {e}",
                    "workdir": str(workdir),
                    "duration_ms": duration_ms,
                    "error": str(e),
                }
            ),
            "error": str(e),
        }

    finally:
        os.chdir(original_cwd)
