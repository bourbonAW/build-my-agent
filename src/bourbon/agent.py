"""Core agent loop for Bourbon."""

import time
import warnings
from collections.abc import Callable
from typing import Any
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from bourbon.access_control import AccessController
from bourbon.access_control.policy import PolicyAction
from bourbon.audit import AuditLogger
from bourbon.audit.events import AuditEvent
from bourbon.config import Config
from bourbon.debug import debug_log
from bourbon.llm import LLMError, create_client
from bourbon.mcp_client import MCPManager
from bourbon.permissions import (
    PermissionAction,
    PermissionChoice,
    PermissionDecision,
    PermissionRequest,
    SessionPermissionStore,
    SuspendedToolRound,
)
from bourbon.permissions.presentation import build_permission_request
from bourbon.prompt import ALL_SECTIONS, ContextInjector, PromptBuilder, PromptContext
from bourbon.sandbox import SandboxManager
from bourbon.session.manager import SessionManager
from bourbon.session.storage import TranscriptStore
from bourbon.session.types import (
    CompactTrigger,
    MessageRole,
    TextBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
    TranscriptMessage,
)
from bourbon.skills import SkillManager
from bourbon.subagent.manager import SubagentManager
from bourbon.subagent.types import SubagentMode
from bourbon.tasks.constants import TASK_V2_TOOLS
from bourbon.todos import TodoManager
from bourbon.tools import (
    ToolContext,
    _get_async_runtime,
    definitions,
    get_registry,
    get_tool_with_metadata,
)
from bourbon.tools.execution_queue import ToolExecutionQueue


class AgentError(Exception):
    """Agent execution error."""

    pass


TASK_NUDGE_THRESHOLD = 10


class Agent:
    """Bourbon agent."""

    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
        system_prompt: str | None = None,
        session_id: UUID | None = None,
        resume_last: bool = False,
    ):
        """Initialize agent.

        Args:
            config: Bourbon configuration
            workdir: Working directory
            on_tool_start: Callback when a tool starts
            on_tool_end: Callback when a tool ends
            system_prompt: Custom system prompt
            session_id: Specific session ID to resume
            resume_last: Resume the most recent session
        """
        self.config = config
        self.workdir = workdir or Path.cwd()
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end

        # Initialize components
        self.todos = TodoManager()
        self.skills = SkillManager(self.workdir)
        self._discovered_tools: set[str] = set()
        # Legacy placeholder kept for compatibility with older tests/callers.
        # Active sessions now use Session.context_manager for all compression logic.
        self.compressor = None
        # Set by SubagentManager for child agents. Normal top-level agents leave
        # these unset and receive the full tool surface.
        self._subagent_agent_def = None
        self._subagent_tool_filter = None

        # Initialize LLM client
        try:
            self.llm = create_client(config)
        except LLMError as e:
            raise AgentError(f"Failed to initialize LLM: {e}") from e

        # Initialize MCP manager (but don't connect yet)
        self.mcp = MCPManager(
            config=config.mcp,
            tool_registry=get_registry(),
            workdir=self.workdir,
        )

        # Build system prompt using prompt module
        self._prompt_ctx = PromptContext(
            workdir=self.workdir,
            skill_manager=self.skills,
            mcp_manager=self.mcp,
        )
        self._prompt_builder = PromptBuilder(
            sections=ALL_SECTIONS,
            custom_prompt=system_prompt,
            append_prompt=None,
        )
        self._context_injector = ContextInjector()
        self.system_prompt = _get_async_runtime().run(self._prompt_builder.build(self._prompt_ctx))

        # Initialize Session system
        session_dir = Path.home() / ".bourbon" / "sessions"
        project_name = self.workdir.name or "default"
        store = TranscriptStore(base_dir=session_dir)
        self._session_manager = SessionManager(
            store=store,
            project_name=project_name,
            project_dir=str(self.workdir),
            token_threshold=config.ui.token_threshold,
            compact_preserve_count=3,
        )

        # Create or resume session
        if session_id:
            self.session = self._session_manager.resume_session(session_id)
            if not self.session:
                self.session = self._session_manager.create_session(session_id=session_id)
        elif resume_last:
            self.session = self._session_manager.resume_latest()
            if not self.session:
                self.session = self._session_manager.create_session()
        else:
            self.session = self._session_manager.create_session()

        # Runtime job manager for Agent tool subagents.
        self.subagent_manager = SubagentManager(
            config=config,
            workdir=self.workdir,
            parent_agent=self,
        )

        # Maximum tool execution rounds to prevent infinite loops
        # Can be configured via config.ui.max_tool_rounds (default: 50)
        self._max_tool_rounds = getattr(config.ui, "max_tool_rounds", 50)

        # Initialize security components
        audit_config = config.audit if hasattr(config, "audit") else {}
        log_dir = Path(audit_config.get("log_dir", "~/.bourbon/audit/")).expanduser()
        self.audit = AuditLogger(
            log_dir=log_dir,
            enabled=audit_config.get("enabled", True),
        )

        ac_config = config.access_control if hasattr(config, "access_control") else {}
        self.access_controller = AccessController(config=ac_config, workdir=self.workdir)

        sandbox_config = config.sandbox if hasattr(config, "sandbox") else {}
        self.sandbox = SandboxManager(config=sandbox_config, workdir=self.workdir, audit=self.audit)

        # Permission runtime state
        self.session_permissions = SessionPermissionStore()
        self.suspended_tool_round: SuspendedToolRound | None = None
        self.active_permission_request: PermissionRequest | None = None
        # Subagent visibility mode, set by SubagentManager for child agents.
        self.subagent_mode: SubagentMode = SubagentMode.NORMAL
        # Teammate task list inheritance, overriding session_id for task resolution.
        self.task_list_id_override: str | None = None
        # Consecutive rounds without task management tool calls, used by task nudge.
        self._rounds_without_task: int = 0

        # Track consecutive failures per tool to limit retries
        self._tool_consecutive_failures: dict[str, int] = {}
        self._max_tool_consecutive_failures = 3

        # Track token usage across all steps
        self.token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    @property
    def messages(self) -> list[dict]:
        """Get current messages for LLM (read-only view).

        DEPRECATED: Returns a copy. Modifications won't take effect.
        Use session.add_message() instead.
        """
        if not hasattr(self, "session"):
            return []
        return self.session.get_messages_for_llm()

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        """DEPRECATED: Setting messages directly is ignored.

        Use session.add_message() or session.chain.clear() instead.
        """
        if not hasattr(self, "session"):
            # During test setup via object.__new__, session may not exist yet
            return
        if not value:
            # Common pattern: agent.messages = [] means clear
            self.session.chain.clear()
        else:
            warnings.warn(
                "Setting messages directly is deprecated and will be ignored. "
                "Use session.add_message() instead.",
                DeprecationWarning,
                stacklevel=2,
            )

    async def initialize_mcp(self) -> dict:
        """Initialize MCP connections.

        This should be called after agent creation to connect to MCP servers.

        Returns:
            Dictionary with connection results
        """
        results = await self.mcp.connect_all()
        return self._finalize_mcp_initialization(results)

    def initialize_mcp_sync(self, timeout: float | None = None) -> dict:
        """Initialize MCP connections from sync code."""
        results = self.mcp.connect_all_sync(timeout=timeout)
        return self._finalize_mcp_initialization(results)

    def shutdown_mcp_sync(self, timeout: float | None = None) -> None:
        """Disconnect MCP connections from sync code."""
        self.mcp.disconnect_all_sync(timeout=timeout)

    def _finalize_mcp_initialization(self, results: dict) -> dict:
        """MCP init complete; next step() call will rebuild system_prompt automatically."""
        return results

    def step(self, user_input: str) -> str:
        """Process one user input and return assistant response."""
        self.system_prompt = _get_async_runtime().run(self._prompt_builder.build(self._prompt_ctx))

        if self.active_permission_request:
            return "Error: Permission request pending. Resolve it before sending new input."

        enriched_input = _get_async_runtime().run(
            self._context_injector.inject(user_input, self._prompt_ctx)
        )

        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=enriched_input)],
        )
        self.session.add_message(user_msg)
        self.session.save()

        # Pre-process: micro-compact
        self.session.context_manager.microcompact()

        # Check if we need full compression
        self.session.maybe_compact()

        # Run the conversation loop
        return self._run_conversation_loop()

    def step_stream(
        self,
        user_input: str,
        on_text_chunk: Callable[[str], None],
    ) -> str:
        """Process user input with streaming text output.

        Args:
            user_input: User's message
            on_text_chunk: Callback invoked for each text chunk (for real-time display).
                          The callback should handle immediate UI updates.

        Returns:
            Complete response text (for history and optional markdown re-rendering)
        """
        started_at = time.monotonic()
        debug_log(
            "agent.step_stream.start",
            user_input_len=len(user_input),
            message_count=self.session.chain.message_count,
            has_active_permission_request=bool(self.active_permission_request),
        )

        self.system_prompt = _get_async_runtime().run(self._prompt_builder.build(self._prompt_ctx))

        if self.active_permission_request:
            return "Error: Permission request pending. Resolve it before sending new input."

        enriched_input = _get_async_runtime().run(
            self._context_injector.inject(user_input, self._prompt_ctx)
        )

        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=enriched_input)],
        )
        self.session.add_message(user_msg)
        self.session.save()

        # Pre-process: micro-compact
        self.session.context_manager.microcompact()

        # Check if we need full compression
        self.session.maybe_compact()

        # Run the streaming conversation loop
        response = self._run_conversation_loop_stream(on_text_chunk)
        debug_log(
            "agent.step_stream.complete",
            response_len=len(response),
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
            has_active_permission_request=bool(self.active_permission_request),
        )
        return response

    def _run_conversation_loop_stream(
        self,
        on_text_chunk: Callable[[str], None],
    ) -> str:
        """Run conversation loop with streaming output."""
        import logging

        tool_round = 0
        accumulated_text = ""
        stream_started_at = time.monotonic()

        while tool_round < self._max_tool_rounds:
            # Call LLM with streaming
            try:
                messages = self.session.get_messages_for_llm()
                debug_log(
                    "agent.stream.llm_call.start",
                    tool_round=tool_round,
                    message_count=len(messages),
                    tool_definition_count=len(self._tool_definitions()),
                )
                event_stream = self.llm.chat_stream(
                    messages=messages,
                    tools=self._tool_definitions(),
                    system=self.system_prompt,
                    max_tokens=64000,
                )

                current_text = ""
                has_tool_calls = False
                # Collect ALL tool_use events (model may return multiple per turn)
                tool_use_blocks: list[dict] = []
                saw_text = False

                for event in event_stream:
                    if event["type"] == "text":
                        text_chunk = event["text"]
                        current_text += text_chunk
                        accumulated_text += text_chunk
                        debug_log(
                            "agent.stream.event.text",
                            tool_round=tool_round,
                            chunk_len=len(text_chunk),
                            current_text_len=len(current_text),
                            accumulated_text_len=len(accumulated_text),
                            first_text_chunk=not saw_text,
                        )
                        saw_text = True
                        # Protect callback — log and continue on error (per design spec)
                        try:
                            on_text_chunk(text_chunk)
                        except Exception:
                            logging.getLogger(__name__).warning(
                                "on_text_chunk callback error", exc_info=True
                            )
                            debug_log(
                                "agent.stream.chunk_callback.error",
                                tool_round=tool_round,
                            )

                    elif event["type"] == "tool_use":
                        has_tool_calls = True
                        tool_use_blocks.append(event)
                        debug_log(
                            "agent.stream.event.tool_use",
                            tool_round=tool_round,
                            tool_name=event.get("name"),
                            tool_id=event.get("id"),
                        )

                    elif event["type"] == "usage":
                        usage = event
                        self.token_usage["input_tokens"] += usage.get("input_tokens", 0)
                        self.token_usage["output_tokens"] += usage.get("output_tokens", 0)
                        self.token_usage["total_tokens"] = (
                            self.token_usage["input_tokens"] + self.token_usage["output_tokens"]
                        )
                        debug_log(
                            "agent.stream.event.usage",
                            tool_round=tool_round,
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            total_tokens=self.token_usage["total_tokens"],
                        )

                    elif event["type"] == "stop":
                        stop_reason = event.get("stop_reason", "end_turn")
                        has_tool_calls = stop_reason == "tool_use" or has_tool_calls
                        debug_log(
                            "agent.stream.event.stop",
                            tool_round=tool_round,
                            stop_reason=stop_reason,
                            tool_use_count=len(tool_use_blocks),
                            current_text_len=len(current_text),
                            elapsed_ms=int((time.monotonic() - stream_started_at) * 1000),
                        )

                # Build assistant response content
                content = []
                if current_text:
                    content.append({"type": "text", "text": current_text})
                for tool_data in tool_use_blocks:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tool_data["id"],
                            "name": tool_data["name"],
                            "input": tool_data["input"],
                        }
                    )

                # Add assistant response to Session
                assistant_msg = self._build_assistant_transcript_message(content)
                if self.token_usage["total_tokens"] > 0:
                    assistant_msg.usage = TokenUsage(
                        input_tokens=self.token_usage["input_tokens"],
                        output_tokens=self.token_usage["output_tokens"],
                        total_tokens=self.token_usage["total_tokens"],
                    )
                self.session.add_message(assistant_msg)
                self.session.save()

                if not has_tool_calls or not tool_use_blocks:
                    # Final response - return accumulated text
                    debug_log(
                        "agent.stream.final_response",
                        tool_round=tool_round,
                        response_len=len(accumulated_text),
                    )
                    return accumulated_text

                # Execute ALL tool calls (matches sync _run_conversation_loop behavior)
                debug_log(
                    "agent.stream.tools.execute",
                    tool_round=tool_round,
                    tool_use_count=len(tool_use_blocks),
                )
                tool_results = self._execute_tools(
                    tool_use_blocks,
                    source_assistant_uuid=assistant_msg.uuid,
                )

                if self.active_permission_request:
                    debug_log(
                        "agent.stream.permission_request_pending",
                        tool_round=tool_round,
                        response_len=len(accumulated_text),
                    )
                    return accumulated_text

                # Add all tool results as single user message (Anthropic protocol requirement)
                tool_turn_msg = self._build_tool_results_transcript_message(
                    tool_results, assistant_msg.uuid
                )
                self._append_task_nudge_if_due(tool_turn_msg, tool_use_blocks)
                self.session.add_message(tool_turn_msg)
                self.session.save()

            except LLMError as e:
                # Fallback: retry once with non-streaming API (per design spec)
                logging.getLogger(__name__).warning(
                    f"Streaming API error, falling back to non-streaming: {e}"
                )
                debug_log(
                    "agent.stream.error",
                    tool_round=tool_round,
                    error=str(e),
                    fallback="non_streaming",
                )
                try:
                    return self._run_conversation_loop()
                except Exception:
                    error_msg = f"LLM Error: {e}"
                    self.session.add_message(
                        TranscriptMessage(
                            role=MessageRole.ASSISTANT,
                            content=[TextBlock(text=error_msg)],
                        )
                    )
                    self.session.save()
                    debug_log(
                        "agent.stream.fallback.error",
                        tool_round=tool_round,
                        error=error_msg,
                    )
                    return accumulated_text + error_msg

            tool_round += 1

        debug_log(
            "agent.stream.max_rounds",
            tool_round=tool_round,
            response_len=len(accumulated_text),
        )
        return (
            accumulated_text + "\n[Reached maximum tool execution rounds. "
            "Providing final response based on what was learned.]"
        )

    def _run_conversation_loop(self) -> str:
        """Run conversation loop until we get a final response."""
        tool_round = 0

        while tool_round < self._max_tool_rounds:
            # Call LLM
            try:
                messages = self.session.get_messages_for_llm()
                tool_defs = self._tool_definitions()
                llm_call_started_at = time.monotonic()
                debug_log(
                    "agent.loop.llm_call.start",
                    tool_round=tool_round,
                    message_count=len(messages),
                    tool_definition_count=len(tool_defs),
                    **self._subagent_debug_fields(),
                )
                response = self.llm.chat(
                    messages=messages,
                    tools=tool_defs,
                    system=self.system_prompt,
                    max_tokens=64000,
                )
                response_content = response.get("content", [])
                response_tool_uses = [
                    block for block in response_content if block.get("type") == "tool_use"
                ]
                debug_log(
                    "agent.loop.llm_call.end",
                    tool_round=tool_round,
                    stop_reason=response.get("stop_reason"),
                    content_block_count=len(response_content),
                    tool_use_count=len(response_tool_uses),
                    elapsed_ms=int((time.monotonic() - llm_call_started_at) * 1000),
                    **self._subagent_debug_fields(),
                )

                # Track token usage
                if "usage" in response:
                    usage = response["usage"]
                    self.token_usage["input_tokens"] += usage.get("input_tokens", 0)
                    self.token_usage["output_tokens"] += usage.get("output_tokens", 0)
                    self.token_usage["total_tokens"] = (
                        self.token_usage["input_tokens"] + self.token_usage["output_tokens"]
                    )
            except LLMError as e:
                error_msg = f"LLM Error: {e}"
                self.session.add_message(
                    TranscriptMessage(
                        role=MessageRole.ASSISTANT,
                        content=[TextBlock(text=error_msg)],
                    )
                )
                self.session.save()
                return error_msg

            # Debug: log response (uncomment for debugging)
            # print(f"[DEBUG] Response stop_reason: {response.get('stop_reason')}")
            # print(
            #     f"[DEBUG] Response content blocks: "
            #     f"{[b.get('type') for b in response.get('content', [])]}"
            # )

            # Check if response contains tool calls
            has_tool_calls = response["stop_reason"] == "tool_use"
            tool_use_blocks = [b for b in response["content"] if b.get("type") == "tool_use"]

            if not has_tool_calls and tool_use_blocks:
                # Sometimes stop_reason is not tool_use but we have tool_use blocks
                has_tool_calls = True
                # print(f"[DEBUG] Found {len(tool_use_blocks)} tool_use blocks despite stop_reason")

            # Add assistant response to Session
            assistant_msg = self._build_assistant_transcript_message(response["content"])
            # Capture usage before add_message
            if "usage" in response:
                usage = response["usage"]
                assistant_msg.usage = TokenUsage(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                )
            self.session.add_message(assistant_msg)
            self.session.save()

            if not has_tool_calls:
                # Extract and return text response
                text_parts = [
                    block["text"] for block in response["content"] if block.get("type") == "text"
                ]
                result = "".join(text_parts)
                debug_log(
                    "agent.loop.final_response",
                    tool_round=tool_round,
                    response_len=len(result),
                    **self._subagent_debug_fields(),
                )
                return result

            # Execute tools
            if tool_use_blocks:
                debug_log(
                    "agent.loop.tools.execute",
                    tool_round=tool_round,
                    tool_use_count=len(tool_use_blocks),
                    tool_names=[block.get("name", "") for block in tool_use_blocks],
                    **self._subagent_debug_fields(),
                )
                tool_results = self._execute_tools(
                    tool_use_blocks,
                    source_assistant_uuid=assistant_msg.uuid,
                )

                if self.active_permission_request:
                    debug_log(
                        "agent.loop.permission_request_pending",
                        tool_round=tool_round,
                        **self._subagent_debug_fields(),
                    )
                    return ""

                # Add all tool results as single user message
                tool_turn_msg = self._build_tool_results_transcript_message(
                    tool_results, assistant_msg.uuid
                )
                self._append_task_nudge_if_due(tool_turn_msg, tool_use_blocks)
                self.session.add_message(tool_turn_msg)
                self.session.save()
            else:
                # No actual tool_use blocks found despite stop_reason
                debug_log("agent.loop.tool_use_blocks_missing", tool_round=tool_round)
                text_parts = [
                    block["text"] for block in response["content"] if block.get("type") == "text"
                ]
                return "".join(text_parts)

            tool_round += 1

        debug_log(
            "agent.loop.max_rounds",
            tool_round=tool_round,
            max_tool_rounds=self._max_tool_rounds,
            **self._subagent_debug_fields(),
        )
        return (
            "[Reached maximum tool execution rounds. "
            "Providing final response based on what was learned.]"
        )

    def _record_policy_decision(
        self,
        *,
        tool_name: str,
        tool_input: dict,
        decision,
    ) -> None:
        self.audit.record(
            AuditEvent.policy_decision(
                tool_name=tool_name,
                tool_input_summary=str(tool_input)[:200],
                decision=decision.action.value,
                matched_rule=decision.reason,
                capabilities_required=[
                    capability_decision.capability.value
                    for capability_decision in decision.decisions
                ],
            )
        )

    @staticmethod
    def _format_sandbox_output(sandbox_result) -> str:
        """Convert sandbox stdout/stderr into legacy bash-tool output."""
        if sandbox_result.timed_out:
            return f"Error: Timeout ({sandbox_result.resource_usage.cpu_time:.0f}s)"

        output = f"{sandbox_result.stdout}{sandbox_result.stderr}".strip()
        return output or "(no output)"

    def _get_discovered_tools(self) -> set[str]:
        """Return the discovered-tool set (initialized in __init__)."""
        return self._discovered_tools

    def _subagent_debug_fields(self) -> dict[str, object]:
        """Return common debug fields for top-level or subagent execution."""
        agent_def = getattr(self, "_subagent_agent_def", None)
        return {
            "is_subagent": agent_def is not None,
            "subagent_type": getattr(agent_def, "agent_type", None),
        }

    def _tool_definitions(self) -> list[dict]:
        """Return tool definitions visible to this agent."""
        tool_defs = definitions(discovered=self._get_discovered_tools())
        filter_engine = getattr(self, "_subagent_tool_filter", None)
        agent_def = getattr(self, "_subagent_agent_def", None)
        if filter_engine is None or agent_def is None:
            return tool_defs
        filtered_tools = filter_engine.filter_tools(
            tool_defs,
            agent_def,
            subagent_mode=self.subagent_mode,
        )
        if len(filtered_tools) != len(tool_defs):
            visible_names = {tool.get("name") for tool in filtered_tools}
            hidden_names = [
                str(tool.get("name", ""))
                for tool in tool_defs
                if tool.get("name") not in visible_names
            ]
            debug_log(
                "subagent.tools.filtered",
                agent_type=agent_def.agent_type,
                total_tools=len(tool_defs),
                visible_tools=len(filtered_tools),
                hidden_tools=hidden_names,
            )
        return filtered_tools

    def _subagent_tool_denial(self, tool_name: str) -> str | None:
        """Return a denial message when a hidden subagent tool is invoked."""
        filter_engine = getattr(self, "_subagent_tool_filter", None)
        agent_def = getattr(self, "_subagent_agent_def", None)
        if filter_engine is None or agent_def is None:
            return None
        if filter_engine.is_allowed(
            tool_name,
            agent_def,
            subagent_mode=self.subagent_mode,
        ):
            return None
        debug_log(
            "subagent.tool.denied",
            tool_name=tool_name,
            agent_type=agent_def.agent_type,
        )
        return f"Denied: Tool '{tool_name}' is not available to {agent_def.agent_type} subagents."

    def _make_tool_context(self) -> ToolContext:
        """Construct the shared tool execution context."""
        return ToolContext(
            workdir=self.workdir,
            agent=self,
            skill_manager=self.skills,
            on_tools_discovered=self._get_discovered_tools().update,
        )

    def _permission_decision_for_tool(
        self,
        tool_name: str,
        tool_input: dict,
    ) -> PermissionDecision:
        """Evaluate one tool call against policy and session approvals."""
        decision = self.access_controller.evaluate(tool_name, tool_input)
        self._record_policy_decision(
            tool_name=tool_name,
            tool_input=tool_input,
            decision=decision,
        )

        if decision.action == PolicyAction.DENY:
            return PermissionDecision(
                action=PermissionAction.DENY,
                reason=decision.reason,
            )

        if decision.action == PolicyAction.NEED_APPROVAL:
            if self.session_permissions.has_match(tool_name, tool_input, self.workdir):
                return PermissionDecision(
                    action=PermissionAction.ALLOW,
                    reason="session rule matched",
                )
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason=decision.reason,
            )

        return PermissionDecision(
            action=PermissionAction.ALLOW,
            reason=decision.reason,
        )

    def _suspend_tool_round(
        self,
        *,
        source_assistant_uuid: UUID,
        tool_use_blocks: list[dict],
        completed_results: list[dict],
        next_tool_index: int,
        request: PermissionRequest,
        task_nudge_tool_use_blocks: list[dict] | None = None,
    ) -> None:
        """Persist the current tool round until the permission request is resolved."""
        self.active_permission_request = request
        self.suspended_tool_round = SuspendedToolRound(
            source_assistant_uuid=source_assistant_uuid,
            tool_use_blocks=tool_use_blocks,
            completed_results=completed_results,
            next_tool_index=next_tool_index,
            active_request=request,
            task_nudge_tool_use_blocks=(
                task_nudge_tool_use_blocks
                if task_nudge_tool_use_blocks is not None
                else tool_use_blocks
            ),
        )

    def _append_task_nudge_if_due(
        self,
        tool_turn_msg: TranscriptMessage,
        tool_use_blocks: list[dict],
    ) -> None:
        """Append a task reminder block when enough rounds skip task tools."""
        if not tool_use_blocks:
            return

        rounds = getattr(self, "_rounds_without_task", 0)
        used_task_tool = any(block.get("name") in TASK_V2_TOOLS for block in tool_use_blocks)
        if used_task_tool:
            self._rounds_without_task = 0
            return

        rounds += 1
        self._rounds_without_task = rounds
        if rounds < TASK_NUDGE_THRESHOLD:
            return

        reminder = self._build_task_reminder_block()
        if reminder is not None:
            tool_turn_msg.content.append(reminder)
        self._rounds_without_task = 0

    def _build_task_reminder_block(self) -> TextBlock | None:
        """Build a task reminder for pending tasks in the current task list."""
        from bourbon.tasks.service import TaskService
        from bourbon.tasks.store import TaskStore

        storage_dir = Path(self.config.tasks.storage_dir).expanduser()
        service = TaskService(TaskStore(storage_dir))

        task_list_id = (
            getattr(self, "task_list_id_override", None)
            or getattr(getattr(self, "session", None), "session_id", None)
            or getattr(
                getattr(getattr(self, "config", None), "tasks", None),
                "default_list_id",
                None,
            )
            or "default"
        )

        tasks = service.list_tasks(str(task_list_id))
        pending = [task for task in tasks if task.status != "completed"]
        if not pending:
            return None

        lines = "\n".join(
            f"- [{task.status}] {task.subject}"
            + (
                f" (blocked by: {', '.join(task.blocked_by)})"
                if task.blocked_by
                else ""
            )
            for task in pending
        )
        return TextBlock(
            text=(
                "<task_reminder>\n"
                f"You have {len(pending)} pending task(s). "
                "Please update with TaskUpdate or create with TaskCreate.\n\n"
                f"{lines}\n"
                "</task_reminder>"
            )
        )

    def resume_permission_request(self, choice: PermissionChoice) -> str:
        """Resume a suspended tool round after the user resolves a permission request."""
        suspended = self.suspended_tool_round
        if suspended is None:
            return "Error: No suspended permission request."

        request = suspended.active_request
        source_assistant_uuid = suspended.source_assistant_uuid
        results = list(suspended.completed_results)

        self.active_permission_request = None
        self.suspended_tool_round = None

        if choice == PermissionChoice.ALLOW_SESSION and request.match_candidate:
            self.session_permissions.add(request.match_candidate)

        if choice == PermissionChoice.REJECT:
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": request.tool_use_id,
                    "content": f"Rejected by user: {request.reason}",
                    "is_error": True,
                }
            )
        else:
            denial = self._subagent_tool_denial(request.tool_name)
            if denial is not None:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": request.tool_use_id,
                        "content": denial,
                        "is_error": True,
                    }
                )
            else:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": request.tool_use_id,
                        "content": self._execute_regular_tool(
                            request.tool_name,
                            request.tool_input,
                            skip_policy_check=True,
                        ),
                    }
                )

        remaining_blocks = suspended.tool_use_blocks[suspended.next_tool_index + 1 :]
        if remaining_blocks:
            results.extend(
                self._execute_tools(
                    remaining_blocks,
                    source_assistant_uuid=source_assistant_uuid,
                    task_nudge_tool_use_blocks=(
                        suspended.task_nudge_tool_use_blocks
                        if suspended.task_nudge_tool_use_blocks is not None
                        else suspended.tool_use_blocks
                    ),
                )
            )
            if self.active_permission_request:
                return ""

        tool_turn_msg = self._build_tool_results_transcript_message(results, source_assistant_uuid)
        nudge_blocks = (
            suspended.task_nudge_tool_use_blocks
            if suspended.task_nudge_tool_use_blocks is not None
            else suspended.tool_use_blocks
        )
        self._append_task_nudge_if_due(tool_turn_msg, nudge_blocks)
        self.session.add_message(tool_turn_msg)
        self.session.save()
        return self._run_conversation_loop()

    def _execute_regular_tool(
        self,
        tool_name: str,
        tool_input: dict,
        *,
        skip_policy_check: bool = False,
    ) -> str:
        """Execute one tool call with policy, audit, and sandbox integration."""
        tool_metadata = get_tool_with_metadata(tool_name)

        if not skip_policy_check:
            decision = self.access_controller.evaluate(tool_name, tool_input)
            self._record_policy_decision(
                tool_name=tool_name,
                tool_input=tool_input,
                decision=decision,
            )

            if decision.action == PolicyAction.DENY:
                return f"Denied: {decision.reason}"

            if decision.action == PolicyAction.NEED_APPROVAL:
                return f"Requires approval: {decision.reason}"

        if (
            tool_metadata
            and tool_metadata.is_destructive
            and getattr(self.sandbox, "enabled", False)
        ):
            sandbox_result = self.sandbox.execute(
                tool_input.get("command", ""), tool_name=tool_name
            )
            output = self._format_sandbox_output(sandbox_result)
            self.audit.record(
                AuditEvent.tool_call(
                    tool_name=tool_name,
                    tool_input_summary=str(tool_input)[:200],
                    sandboxed=True,
                )
            )
            return output

        # Check if this tool has exceeded consecutive failure limit.
        # Use getattr fallback to support Agent.__new__-constructed stubs in tests.
        _failures_map = getattr(self, "_tool_consecutive_failures", {})
        failures = _failures_map.get(tool_name, 0)
        if failures >= self._max_tool_consecutive_failures:
            # Reset counter so the tool is recoverable after the LLM backs off.
            _failures_map.pop(tool_name, None)
            return (
                f"Error: Tool '{tool_name}' has failed {failures} consecutive times. "
                "Do not retry this tool. Try a different approach or tool."
            )

        try:
            ctx = self._make_tool_context()
            output = get_registry().call(tool_name, tool_input, ctx)
        except Exception as e:
            # Note: _tool_consecutive_failures read-modify-write is not atomic under
            # concurrent execution; failure counting is best-effort in parallel mode.
            _failures_map[tool_name] = failures + 1
            return f"Error executing {tool_name}: {e}"

        self.audit.record(
            AuditEvent.tool_call(
                tool_name=tool_name,
                tool_input_summary=str(tool_input)[:200],
            )
        )

        # Reset on any successful execution (no exception).
        # Do not inspect output text — tool output may legitimately start with "Error".
        _failures_map.pop(tool_name, None)

        return output

    def _execute_tools(
        self,
        tool_use_blocks: list[dict],
        *,
        source_assistant_uuid: UUID,
        task_nudge_tool_use_blocks: list[dict] | None = None,
    ) -> list[dict]:
        """Execute tool calls, running concurrent-safe tools in parallel."""
        if task_nudge_tool_use_blocks is None:
            task_nudge_tool_use_blocks = tool_use_blocks

        results: list[dict | None] = [None] * len(tool_use_blocks)
        manual_compact = False

        def new_queue() -> ToolExecutionQueue:
            return ToolExecutionQueue(
                execute_fn=lambda block: self._execute_regular_tool(
                    block.get("name", ""),
                    block.get("input", {}),
                    skip_policy_check=True,
                ),
                on_tool_start=self.on_tool_start,
                on_tool_end=self.on_tool_end,
            )

        queue: ToolExecutionQueue | None = None

        def ensure_queue() -> ToolExecutionQueue:
            nonlocal queue
            if queue is None:
                queue = new_queue()
            return queue

        def safe_callback(fn: Callable[..., Any] | None, *args: Any) -> None:
            if fn is None:
                return
            with suppress(Exception):
                fn(*args)

        def direct_start(name: str, inp: dict) -> None:
            safe_callback(self.on_tool_start, name, inp)

        def direct_end(name: str, output: str) -> None:
            safe_callback(self.on_tool_end, name, output)

        id_to_index = {block.get("id", ""): i for i, block in enumerate(tool_use_blocks)}

        def fill_queue_results() -> None:
            nonlocal queue
            if queue is None:
                return
            drained = queue
            queue = None
            for result in drained.execute_all():
                index = id_to_index.get(result.get("tool_use_id", ""))
                if index is not None and results[index] is None:
                    results[index] = result

        for index, block in enumerate(tool_use_blocks):
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            tool_id = block.get("id", "")

            denial = self._subagent_tool_denial(tool_name)
            if denial is not None:
                fill_queue_results()
                direct_start(tool_name, tool_input)
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": str(denial)[:50000],
                    "is_error": True,
                }
                direct_end(tool_name, str(denial))
                continue

            if tool_name == "compress":
                fill_queue_results()
                direct_start(tool_name, tool_input)
                manual_compact = True
                output = "Compressing context..."
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": output,
                }
                direct_end(tool_name, output)
                continue

            permission = self._permission_decision_for_tool(tool_name, tool_input)
            if permission.action == PermissionAction.DENY:
                fill_queue_results()
                direct_start(tool_name, tool_input)
                output = f"Denied: {permission.reason}"
                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": output,
                }
                direct_end(tool_name, output)
                continue

            if permission.action == PermissionAction.ASK:
                fill_queue_results()
                direct_start(tool_name, tool_input)
                completed = [result for result in results if result is not None]
                self._suspend_tool_round(
                    source_assistant_uuid=source_assistant_uuid,
                    tool_use_blocks=tool_use_blocks,
                    task_nudge_tool_use_blocks=task_nudge_tool_use_blocks,
                    completed_results=completed,
                    next_tool_index=index,
                    request=build_permission_request(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_use_id=tool_id,
                        decision=permission,
                        workdir=self.workdir,
                    ),
                )
                direct_end(tool_name, "Requires permission")
                return completed

            tool_obj = get_tool_with_metadata(tool_name)
            if tool_obj is not None:
                ensure_queue().add(block, tool_obj, index)
                continue

            fill_queue_results()
            direct_start(tool_name, tool_input)
            output = f"Unknown tool: {tool_name}"
            results[index] = {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": output,
                "is_error": True,
            }
            direct_end(tool_name, output)

        fill_queue_results()

        if manual_compact:
            self._manual_compact()

        return [result for result in results if result is not None]

    def _build_assistant_transcript_message(self, content: list[dict]) -> TranscriptMessage:
        """Convert LLM response content blocks to TranscriptMessage."""
        blocks = []
        for block in content:
            if block.get("type") == "text":
                blocks.append(TextBlock(text=block.get("text", "")))
            elif block.get("type") == "tool_use":
                blocks.append(
                    ToolUseBlock(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input", {}),
                    )
                )
        return TranscriptMessage(role=MessageRole.ASSISTANT, content=blocks)

    def _build_tool_results_transcript_message(
        self,
        results: list[dict],
        source_assistant_uuid: UUID,
    ) -> TranscriptMessage:
        """Convert tool results to a single TranscriptMessage.

        All tool results from one round are merged into one user message
        (Anthropic protocol requires all tool_results in same user turn).
        """
        content = [
            ToolResultBlock(
                tool_use_id=r.get("tool_use_id", ""),
                content=str(r.get("content", "")),
                is_error=r.get("is_error", False),
            )
            for r in results
            if r.get("type") == "tool_result"
        ]
        # Also preserve text blocks (e.g. todo reminders)
        for r in results:
            if r.get("type") == "text":
                content.append(TextBlock(text=r.get("text", "")))
        return TranscriptMessage(
            role=MessageRole.USER,
            content=content,
            source_tool_uuid=source_assistant_uuid,
        )

    def _manual_compact(self) -> None:
        """Perform manual context compression."""
        result = self.session.maybe_compact(trigger=CompactTrigger.MANUAL)
        return result

    def get_todos(self) -> str:
        """Get current todo list."""
        return self.todos.render()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.session.chain.clear()
        self.session.metadata.message_count = 0
        self.session.save()

    def reset_token_usage(self) -> None:
        """Reset token usage counters."""
        self.token_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    def get_token_usage(self) -> dict:
        """Get current token usage."""
        return self.token_usage.copy()

    def get_session_tokens(self) -> int:
        """Estimate current session token count."""
        if hasattr(self, "session"):
            return self.session.context_manager.estimate_tokens()
        # Fallback for legacy tests using object.__new__(Agent)
        if hasattr(self, "compressor"):
            return self.compressor.estimate_tokens(self.messages)
        return 0
