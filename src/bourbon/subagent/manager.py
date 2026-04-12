"""Core subagent runtime-job manager."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bourbon.config import Config
from bourbon.debug import debug_log
from bourbon.subagent.cancel import AbortController
from bourbon.subagent.cleanup import ResourceManager
from bourbon.subagent.executor import AsyncExecutor
from bourbon.subagent.registry import RunRegistry
from bourbon.subagent.result import AgentToolResult, finalize_agent_tool
from bourbon.subagent.session_adapter import SubagentSessionAdapter
from bourbon.subagent.tools import AGENT_TYPE_CONFIGS, ToolFilter
from bourbon.subagent.types import AgentDefinition, RunStatus, SubagentRun

AgentFactory = Callable[[SubagentRun, AgentDefinition], Any]


class SubagentManager:
    """Orchestrates subagent runtime-job lifecycle."""

    def __init__(
        self,
        config: Config,
        workdir: Path,
        parent_agent: Any | None = None,
        *,
        agent_factory: AgentFactory | None = None,
        executor: AsyncExecutor | None = None,
        registry: RunRegistry | None = None,
        resource_manager: ResourceManager | None = None,
    ):
        self.config = config
        self.workdir = workdir
        self.parent_agent = parent_agent
        self.agent_factory = agent_factory
        self.executor = executor or AsyncExecutor()
        self.registry = registry or RunRegistry()
        self.resource_manager = resource_manager or ResourceManager()

    def spawn(
        self,
        description: str,
        prompt: str,
        *,
        agent_type: str = "default",
        model: str | None = None,
        max_turns: int | None = None,
        run_in_background: bool = False,
        agent_factory: AgentFactory | None = None,
    ) -> AgentToolResult | str:
        """Start a subagent run synchronously or in the background."""
        agent_def = self._agent_definition(agent_type)
        run = SubagentRun(
            description=description,
            prompt=prompt,
            agent_type=agent_type,
            model=model or agent_def.model,
            max_turns=max_turns or agent_def.max_turns,
            is_async=run_in_background,
            abort_controller=AbortController(),
        )
        self.registry.register(run)
        self.resource_manager.register(run)
        debug_log(
            "subagent.spawn.registered",
            run_id=run.run_id,
            description=description,
            prompt_len=len(prompt),
            agent_type=agent_type,
            model=run.model,
            max_turns=run.max_turns,
            is_async=run.is_async,
            explicit_max_turns=max_turns is not None,
        )

        run_agent_factory = agent_factory or self.agent_factory
        if run_in_background:
            self.executor.submit(run.run_id, self._run_lifecycle, run, run_agent_factory)
            return run.run_id

        return self._run_lifecycle(run, run_agent_factory)

    def get_run(self, run_id: str) -> SubagentRun | None:
        """Return one runtime job by ID."""
        return self.registry.get_run(run_id)

    def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        agent_type: str | None = None,
    ) -> list[SubagentRun]:
        """List runtime jobs."""
        return self.registry.list_runs(status=status, agent_type=agent_type)

    def kill_run(self, run_id: str) -> str:
        """Signal a runtime job to stop."""
        run = self.registry.get_run(run_id)
        if run is None:
            return f"Run not found: {run_id}"

        if run.abort_controller is not None:
            run.abort_controller.abort()
        run.status = RunStatus.KILLED

        future = self.executor.get_future(run_id)
        if future is not None:
            future.cancel()

        return f"Stopped run: {run_id}"

    def stop_run(self, run_id: str) -> str:
        """Alias used by the REPL command surface."""
        return self.kill_run(run_id)

    def get_run_output(self, run_id: str) -> str:
        """Return the current output for a runtime job."""
        run = self.registry.get_run(run_id)
        if run is None:
            return f"Run not found: {run_id}"
        if run.result is not None:
            return run.result
        if run.error is not None:
            return f"Error: {run.error}"
        return f"Run {run_id} is {run.status.value}."

    def render_run_list(self) -> str:
        """Render runtime jobs for REPL display."""
        runs = self.registry.list_runs()
        if not runs:
            return "No runtime jobs."

        lines = []
        for run in runs:
            lines.append(
                f"{run.run_id} [{run.status.value}] {run.description} ({run.agent_type})"
            )
        return "\n".join(lines)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown background execution resources."""
        self.executor.shutdown(wait=wait)

    def _agent_definition(self, agent_type: str) -> AgentDefinition:
        try:
            return AGENT_TYPE_CONFIGS[agent_type]
        except KeyError as exc:
            known = ", ".join(sorted(AGENT_TYPE_CONFIGS))
            raise ValueError(
                f"Unknown subagent type '{agent_type}'. Known types: {known}"
            ) from exc

    def _run_lifecycle(
        self,
        run: SubagentRun,
        agent_factory: AgentFactory | None = None,
    ) -> AgentToolResult:
        start_time_ms = time.time() * 1000
        self.registry.update_status(run.run_id, RunStatus.RUNNING)
        debug_log(
            "subagent.lifecycle.start",
            run_id=run.run_id,
            agent_type=run.agent_type,
            max_turns=run.max_turns,
            is_async=run.is_async,
        )

        try:
            agent_def = self._agent_definition(run.agent_type)
            subagent = self._create_subagent(run, agent_def, agent_factory)
            run._subagent = subagent
            debug_log(
                "subagent.lifecycle.agent_created",
                run_id=run.run_id,
                agent_type=run.agent_type,
                agent_class=type(subagent).__name__,
            )

            step_started_at = time.monotonic()
            final_content = subagent.step(run.prompt)
            debug_log(
                "subagent.lifecycle.step.complete",
                run_id=run.run_id,
                agent_type=run.agent_type,
                result_len=len(final_content or ""),
                elapsed_ms=int((time.monotonic() - step_started_at) * 1000),
            )
            self._copy_agent_usage(subagent, run)

            result = finalize_agent_tool(
                run=run,
                messages=[],
                final_content=final_content,
                start_time_ms=start_time_ms,
            )
            run.result = result.content

            if run.abort_controller is not None and run.abort_controller.is_aborted():
                run.status = RunStatus.KILLED
            else:
                self.registry.complete(run.run_id, result.content)
            debug_log(
                "subagent.lifecycle.complete",
                run_id=run.run_id,
                agent_type=run.agent_type,
                status=run.status.value,
                total_tokens=run.total_tokens,
                total_duration_ms=result.total_duration_ms,
            )
            return result
        except KeyboardInterrupt:
            if run.abort_controller is not None:
                run.abort_controller.abort()
            run.status = RunStatus.KILLED
            debug_log(
                "subagent.lifecycle.interrupted",
                run_id=run.run_id,
                agent_type=run.agent_type,
                status=run.status.value,
            )
            raise
        except Exception as exc:
            self.registry.fail(run.run_id, str(exc))
            debug_log(
                "subagent.lifecycle.failed",
                run_id=run.run_id,
                agent_type=run.agent_type,
                error=str(exc),
            )
            raise

    def _create_subagent(
        self,
        run: SubagentRun,
        agent_def: AgentDefinition,
        agent_factory: AgentFactory | None = None,
    ) -> Any:
        if agent_factory is not None:
            return agent_factory(run, agent_def)

        from bourbon.agent import Agent

        system_prompt = getattr(self.parent_agent, "system_prompt", None)
        if agent_def.system_prompt_suffix:
            system_prompt = (
                f"{system_prompt}\n\n{agent_def.system_prompt_suffix}"
                if system_prompt
                else agent_def.system_prompt_suffix
            )

        subagent = Agent(
            config=self.config,
            workdir=self.workdir,
            system_prompt=system_prompt,
        )
        subagent._max_tool_rounds = run.max_turns
        subagent._subagent_agent_def = agent_def
        subagent._subagent_tool_filter = ToolFilter()

        parent_session_manager = getattr(self.parent_agent, "_session_manager", None)
        if parent_session_manager is not None:
            adapter = SubagentSessionAdapter(
                parent_store=parent_session_manager.store,
                project_name=parent_session_manager.project_name,
                project_dir=str(self.workdir),
                run_id=run.run_id,
            )
            subagent.session = adapter.create_session()

        return subagent

    @staticmethod
    def _copy_agent_usage(subagent: Any, run: SubagentRun) -> None:
        get_token_usage = getattr(subagent, "get_token_usage", None)
        if callable(get_token_usage):
            usage = get_token_usage()
        else:
            usage = getattr(subagent, "token_usage", {})

        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        run.total_tokens = total_tokens
