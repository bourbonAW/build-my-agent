"""Core agent loop for Bourbon."""

import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
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
from bourbon.sandbox import SandboxManager
from bourbon.session.manager import Session, SessionManager
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
from bourbon.todos import TodoManager
from bourbon.tools import (
    definitions,
    get_registry,
    get_tool_with_metadata,
    handler,
)


class AgentError(Exception):
    """Agent execution error."""

    pass


@dataclass
class PendingConfirmation:
    """Represents a pending user confirmation for high-risk operation failure."""

    tool_name: str
    tool_input: dict
    error_output: str
    options: list[str]
    confirmation_type: str = "high_risk_failure"


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
        # Legacy placeholder kept for compatibility with older tests/callers.
        # Active sessions now use Session.context_manager for all compression logic.
        self.compressor = None

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

        # Build system prompt (will be updated after MCP connect)
        self._custom_system_prompt = system_prompt
        self.system_prompt = system_prompt or self._build_system_prompt()

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

        # Track rounds without todo update for nagging
        self._rounds_without_todo = 0

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

        # Pending confirmation for high-risk operation failures
        self.pending_confirmation: PendingConfirmation | None = None

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
        """Update prompt state after MCP initialization."""
        if results and not self._custom_system_prompt:
            summary = self.mcp.get_connection_summary()
            if summary["total_tools"] > 0:
                self.system_prompt = self._build_system_prompt()
        return results

    def _build_system_prompt(self) -> str:
        """Build system prompt with skills and instructions."""
        lines = [
            f"You are Bourbon, a general-purpose AI assistant working in {self.workdir}.",
            "",
            "You can help users with a wide variety of tasks including coding, data analysis,",
            "investment research, writing, and general knowledge work.",
            "",
            "You have access to:",
            "- Built-in tools for file operations, code search, and execution",
            (
                "- Specialized Skills for domain-specific tasks "
                "(investment analysis, project management, etc.)"
            ),
            "- MCP tools for external integrations (databases, APIs, etc.)",
            "",
            "When working on multi-step tasks, use TodoWrite to track progress.",
            "",
            "IMPORTANT: Do not repeat the same actions. If you've already explored or analyzed,",
            "provide a summary and move forward. Avoid getting stuck in loops.",
            "",
            "CRITICAL: When you want to use a tool, you MUST use the tool_calls format.",
            "Do not just describe what you plan to do - actually invoke the tools.",
            "",
            self._get_skills_section(),
            "",
            self._get_mcp_section(),
            "",
            "TASK ADAPTABILITY:",
            "- For coding tasks: Use code search, file editing, and testing tools",
            "- For investment tasks: Activate investment-agent skill for portfolio analysis",
            "- For data tasks: Use file operations and data processing tools",
            "- For general questions: Use your knowledge and available tools as needed",
            "",
            "CRITICAL ERROR HANDLING RULES:",
            (
                "1. HIGH RISK operations (software install/uninstall, version changes, "
                "system commands, destructive operations):"
            ),
            (
                "   - If the operation fails (e.g., version not found, package unavailable), "
                "you MUST STOP and ask the user for confirmation"
            ),
            (
                "   - NEVER automatically switch versions, install alternatives, or change "
                "parameters without user approval"
            ),
            (
                "   - Examples: pip install package==wrong_version, apt install "
                "nonexistent-package, rm important-files"
            ),
            "",
            "2. LOW RISK operations (read_file, search, exploration):",
            (
                "   - If a file is not found, you MAY search for similar files and "
                "attempt to read the correct one"
            ),
            "   - If search returns no results, you MAY adjust patterns and retry",
            "   - Always report what you found and what action you took",
            "",
            "3. MEDIUM RISK operations (file modifications):",
            "   - If write/edit fails, report the error and ask before attempting alternatives",
            "",
        ]
        return "\n".join(lines)

    def _get_mcp_section(self) -> str:
        """Generate MCP tools section for system prompt.

        Returns information about available MCP tools.
        """
        if not hasattr(self, "mcp"):
            return ""

        summary = self.mcp.get_connection_summary()

        if not summary["enabled"] or summary["total_tools"] == 0:
            return ""

        mcp_tools = self.mcp.list_mcp_tools()
        if not mcp_tools:
            return ""

        lines = [
            "MCP TOOLS",
            "=========",
            "",
            "The following external tools are available from MCP servers:",
            "",
        ]

        # Group tools by server
        server_tools: dict[str, list[str]] = {}
        for tool_name in mcp_tools:
            if ":" in tool_name:
                server, tool = tool_name.split(":", 1)
                server_tools.setdefault(server, []).append(tool)

        for server, tools in sorted(server_tools.items()):
            lines.append(f"  {server}:")
            for tool in sorted(tools):
                lines.append(f"    - {server}:{tool}")
            lines.append("")

        lines.append("Use these tools just like any other tool.")

        return "\n".join(lines)

    def _get_skills_section(self) -> str:
        """Generate skills section for system prompt.

        Returns catalog of available skills with activation instructions.
        """
        catalog = self.skills.get_catalog()

        if not catalog:
            return "(No skills available)"

        lines = [
            "SKILLS",
            "======",
            "",
            "The following skills provide specialized instructions for specific tasks.",
            "When a task matches a skill's description, use the 'skill' tool to load",
            "its full instructions before proceeding.",
            "",
            catalog,
            "",
            "To activate a skill, use:",
            "  <function_calls>",
            '    <invoke name="skill">',
            '      <parameter name="name">skill-name</parameter>',
            "    </invoke>",
            "  </function_calls>",
        ]
        return "\n".join(lines)

    def step(self, user_input: str) -> str:
        """Process one user input and return assistant response."""
        # Check if we're resuming from a pending confirmation
        if self.pending_confirmation:
            return self._handle_confirmation_response(user_input)

        # Add user message via Session
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=user_input)],
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
            has_pending_confirmation=bool(self.pending_confirmation),
        )

        # Check if we're resuming from a pending confirmation
        if self.pending_confirmation:
            response = self._handle_confirmation_response(user_input)
            debug_log(
                "agent.step_stream.complete",
                response_len=len(response),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                resumed_confirmation=True,
            )
            return response

        # Add user message via Session
        user_msg = TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=user_input)],
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
            has_pending_confirmation=bool(self.pending_confirmation),
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
                    tool_definition_count=len(definitions()),
                )
                event_stream = self.llm.chat_stream(
                    messages=messages,
                    tools=definitions(),
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
                tool_results = self._execute_tools(tool_use_blocks)

                # Check if we have a pending confirmation
                if self.pending_confirmation:
                    debug_log(
                        "agent.stream.pending_confirmation",
                        tool_round=tool_round,
                        response_len=len(accumulated_text),
                    )
                    return accumulated_text + "\n" + self._format_confirmation_prompt()

                # Add all tool results as single user message (Anthropic protocol requirement)
                tool_turn_msg = self._build_tool_results_transcript_message(
                    tool_results, assistant_msg.uuid
                )
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
                    self.session.add_message(TranscriptMessage(
                        role=MessageRole.ASSISTANT,
                        content=[TextBlock(text=error_msg)],
                    ))
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

    def _handle_confirmation_response(self, user_input: str) -> str:
        """Handle user response to a pending confirmation."""
        confirmation = self.pending_confirmation
        self.pending_confirmation = None

        if confirmation and confirmation.confirmation_type == "policy_approval":
            normalized = user_input.strip().lower()
            if self._is_approval_response(normalized):
                output = self._execute_regular_tool(
                    confirmation.tool_name,
                    confirmation.tool_input,
                    skip_policy_check=True,
                )
                if self.pending_confirmation:
                    return self._format_confirmation_prompt()
                return output
            return f"Skipped {confirmation.tool_name}: approval not granted."

        # Add the user's choice to the conversation via Session
        context = (
            f"[Previous high-risk operation failed: {confirmation.tool_name}]\n"
            f"[Error: {confirmation.error_output}]\n"
            f"[User decision: {user_input}]\n"
            f"Please proceed based on the user's decision above."
        )
        self.session.add_message(TranscriptMessage(
            role=MessageRole.USER,
            content=[TextBlock(text=context)],
        ))
        self.session.save()

        # Continue the conversation
        return self._run_conversation_loop()

    def _run_conversation_loop(self) -> str:
        """Run conversation loop until we get a final response."""
        tool_round = 0

        while tool_round < self._max_tool_rounds:
            # Call LLM
            try:
                messages = self.session.get_messages_for_llm()
                response = self.llm.chat(
                    messages=messages,
                    tools=definitions(),
                    system=self.system_prompt,
                    max_tokens=64000,
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
                self.session.add_message(TranscriptMessage(
                    role=MessageRole.ASSISTANT,
                    content=[TextBlock(text=error_msg)],
                ))
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
                return "".join(text_parts)

            # Execute tools
            if tool_use_blocks:
                tool_results = self._execute_tools(tool_use_blocks)

                # Check if we have a pending confirmation (high-risk error)
                if self.pending_confirmation:
                    # Return confirmation prompt to user
                    return self._format_confirmation_prompt()

                # Add all tool results as single user message
                tool_turn_msg = self._build_tool_results_transcript_message(
                    tool_results, assistant_msg.uuid
                )
                self.session.add_message(tool_turn_msg)
                self.session.save()
            else:
                # No actual tool_use blocks found despite stop_reason
                print("[DEBUG] stop_reason was tool_use but no tool_use blocks found!")
                text_parts = [
                    block["text"] for block in response["content"] if block.get("type") == "text"
                ]
                return "".join(text_parts)

            tool_round += 1

        return (
            "[Reached maximum tool execution rounds. "
            "Providing final response based on what was learned.]"
        )

    def _format_confirmation_prompt(self) -> str:
        """Format pending confirmation for display to user."""
        if not self.pending_confirmation:
            return ""

        conf = self.pending_confirmation
        if conf.confirmation_type == "policy_approval":
            title = "APPROVAL REQUIRED"
            description = "This operation requires approval before execution."
        else:
            title = "HIGH-RISK OPERATION FAILED"
            description = "This is a high-risk operation. Please choose how to proceed:"
        lines = [
            "",
            f"⚠️  {title}",
            "━" * 50,
            f"Operation: {conf.tool_name}",
            f"Input: {conf.tool_input}",
            f"Error: {conf.error_output}",
            "",
            description,
            "",
        ]
        for i, option in enumerate(conf.options, 1):
            lines.append(f"  [{i}] {option}")
        lines.append("  [c] Cancel this operation")
        lines.append("")
        lines.append("Enter your choice: ")

        return "\n".join(lines)

    @staticmethod
    def _is_approval_response(user_input: str) -> bool:
        """Return True when the user approved the pending operation."""
        return user_input in {"1", "y", "yes"} or "approve" in user_input

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

    def _execute_regular_tool(
        self,
        tool_name: str,
        tool_input: dict,
        *,
        skip_policy_check: bool = False,
    ) -> str:
        """Execute one tool call with policy, audit, and sandbox integration."""
        tool_handler_fn = handler(tool_name)
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
                self.pending_confirmation = PendingConfirmation(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    error_output=f"Requires approval: {decision.reason}",
                    options=["Approve and execute", "Skip this operation"],
                    confirmation_type="policy_approval",
                )
                return f"Requires approval: {decision.reason}"

        if tool_handler_fn is None:
            return f"Unknown tool: {tool_name}"

        if tool_name == "bash" and getattr(self.sandbox, "enabled", False):
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

        try:
            call_input = dict(tool_input)
            if tool_name in {"bash", "read_file", "write_file", "edit_file"}:
                call_input.setdefault("workdir", self.workdir)
            output = tool_handler_fn(**call_input)
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

        self.audit.record(
            AuditEvent.tool_call(
                tool_name=tool_name,
                tool_input_summary=str(tool_input)[:200],
            )
        )

        if (
            tool_metadata
            and output.startswith("Error")
            and tool_metadata.is_high_risk_operation(tool_input)
        ):
            self.pending_confirmation = PendingConfirmation(
                tool_name=tool_name,
                tool_input=tool_input,
                error_output=output,
                options=self._generate_options(tool_name, tool_input, output),
                confirmation_type="high_risk_failure",
            )

        return output

    def _execute_tools(self, tool_use_blocks: list[dict]) -> list[dict]:
        """Execute tool calls.

        Args:
            tool_use_blocks: List of tool_use content blocks

        Returns:
            List of tool results
        """
        results = []
        used_todo = False
        manual_compact = False

        for block in tool_use_blocks:
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            tool_id = block.get("id", "")

            # Debug: log tool execution (uncomment for debugging)
            # print(f"[DEBUG] Executing tool: {tool_name} with input: {tool_input}")

            # Notify start of tool execution
            if self.on_tool_start:
                self.on_tool_start(tool_name, tool_input)

            # Handle special tools
            if tool_name == "compress":
                manual_compact = True
                output = "Compressing context..."
            elif tool_name == "TodoWrite":
                used_todo = True
                try:
                    output = self.todos.update(tool_input.get("items", []))
                except ValueError as e:
                    output = f"Error: {e}"
            elif tool_name == "skill":
                # skill tool is handled by registered handler, but we keep
                # this for backward compatibility during transition
                try:
                    skill_name = tool_input.get("name", "")
                    output = self.skills.activate(skill_name)
                except Exception as e:
                    output = f"Error activating skill '{skill_name}': {e}"
            else:
                output = self._execute_regular_tool(tool_name, tool_input)
                if self.pending_confirmation:
                    if self.on_tool_end:
                        self.on_tool_end(tool_name, output)

                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": str(output)[:50000],
                        }
                    )
                    return results

            # Notify end of tool execution
            if self.on_tool_end:
                self.on_tool_end(tool_name, output)

            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": str(output)[:50000],
                }
            )

        # Todo nag
        self._rounds_without_todo = 0 if used_todo else self._rounds_without_todo + 1
        if self.todos.has_open_items() and self._rounds_without_todo >= 3:
            results.insert(
                0,
                {
                    "type": "text",
                    "text": "<reminder>You have open todos. Consider updating them.</reminder>",
                },
            )

        if manual_compact:
            self._manual_compact()

        return results

    def _generate_options(self, tool_name: str, tool_input: dict, error_output: str) -> list[str]:
        """Generate options for user based on the failed operation."""
        options = []

        if tool_name == "bash":
            command = tool_input.get("command", "")

            # Package installation errors
            if "pip install" in command or "pip3 install" in command:
                options.append("Try installing the latest version")
                options.append("Show available versions and let me choose")

            # apt/yum errors
            elif "apt " in command or "apt-get " in command or "yum " in command:
                options.append("Try with sudo")
                options.append("Search for alternative package names")

            # rm errors
            elif command.strip().startswith("rm "):
                options.append("Force remove with -f")
                options.append("Remove recursively with -r")

            else:
                options.append("Retry the same command")
                options.append("Try a modified version")

        elif tool_name in ("write_file", "edit_file"):
            options.append("Retry with different permissions")
            options.append("Try writing to a different location")

        if not options:
            options.append("Retry")
            options.append("Skip this operation")

        return options

    def _build_assistant_transcript_message(
        self, content: list[dict]
    ) -> TranscriptMessage:
        """Convert LLM response content blocks to TranscriptMessage."""
        blocks = []
        for block in content:
            if block.get("type") == "text":
                blocks.append(TextBlock(text=block.get("text", "")))
            elif block.get("type") == "tool_use":
                blocks.append(ToolUseBlock(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    input=block.get("input", {}),
                ))
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

    def _auto_compact(self) -> None:
        """Perform automatic context compression.

        DEPRECATED: Use session.maybe_compact() instead.
        """
        self.session.maybe_compact()

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
