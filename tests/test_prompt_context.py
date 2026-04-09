import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bourbon.prompt.types import PromptContext


def run(coro):
    return asyncio.run(coro)


def test_inject_prepends_system_reminder():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp/proj"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("hello", ctx))

    assert result.startswith("<system-reminder>")
    assert "</system-reminder>" in result
    assert "hello" in result
    assert result.index("</system-reminder>") < result.index("hello")


def test_inject_includes_workdir():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/home/user/project"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("msg", ctx))

    assert "/home/user/project" in result


def test_inject_includes_today_date():
    from datetime import date

    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("msg", ctx))

    assert date.today().isoformat() in result


def test_inject_includes_git_status_when_available():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp/repo"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value="## main\n M file.py")):
        result = run(injector.inject("msg", ctx))

    assert "## main" in result
    assert " M file.py" in result


def test_inject_omits_git_section_when_none():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp/not-a-repo"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("msg", ctx))

    assert "Git status" not in result


def test_get_git_status_returns_none_on_timeout():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()

    mock_proc = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)
    mock_proc.communicate = MagicMock(return_value=object())

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
    ):
        result = run(injector._get_git_status(Path("/any")))

    assert result is None
    mock_proc.kill.assert_called_once()


def test_get_git_status_returns_none_outside_repo(tmp_path):
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    result = run(injector._get_git_status(tmp_path))
    assert result is None


def test_inject_empty_user_message():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    ctx = PromptContext(workdir=Path("/tmp"))

    with patch.object(injector, "_get_git_status", new=AsyncMock(return_value=None)):
        result = run(injector.inject("", ctx))

    assert result.startswith("<system-reminder>")
    assert "</system-reminder>" in result
    assert result.endswith("\n")


def test_truncate_git_status_caps_output():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    many_lines = "\n".join([f" M file{i}.py" for i in range(200)])

    result = injector._truncate_git_status(many_lines)

    lines = result.splitlines()
    assert len(lines) == injector._GIT_STATUS_MAX_LINES + 1
    assert "truncated" in lines[-1]
    assert "150" in lines[-1]


def test_truncate_git_status_passthrough_when_short():
    from bourbon.prompt.context import ContextInjector

    injector = ContextInjector()
    short = "\n".join([f" M file{i}.py" for i in range(10)])

    result = injector._truncate_git_status(short)

    assert result == short
