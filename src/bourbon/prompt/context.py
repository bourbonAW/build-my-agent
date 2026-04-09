import asyncio
from datetime import date
from pathlib import Path

from bourbon.prompt.types import PromptContext


class ContextInjector:
    """Prepend environment context to a human-authored user message."""

    _GIT_TIMEOUT = 2.0
    _GIT_STATUS_MAX_LINES = 50

    async def inject(self, user_message: str, ctx: PromptContext) -> str:
        env_info = await self._get_env_info(ctx)
        reminder = f"<system-reminder>\n{env_info}\n</system-reminder>"
        return f"{reminder}\n{user_message}"

    async def _get_env_info(self, ctx: PromptContext) -> str:
        parts = [
            f"Working directory: {ctx.workdir}",
            f"Today's date: {date.today().isoformat()}",
        ]
        git_info = await self._get_git_status(ctx.workdir)
        if git_info:
            parts.append(f"Git status:\n{git_info}")
        return "\n".join(parts)

    async def _get_git_status(self, workdir: Path) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(workdir),
                "status",
                "--short",
                "-b",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._GIT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return None

            if proc.returncode != 0:
                return None

            text = stdout.decode().strip()
            return self._truncate_git_status(text)
        except Exception:
            return None

    def _truncate_git_status(self, text: str) -> str:
        """Cap git status lines to avoid inflating the transcript."""
        lines = text.splitlines()
        if len(lines) <= self._GIT_STATUS_MAX_LINES:
            return text

        kept = lines[: self._GIT_STATUS_MAX_LINES]
        omitted = len(lines) - self._GIT_STATUS_MAX_LINES
        kept.append(f"[... {omitted} more lines truncated ...]")
        return "\n".join(kept)
