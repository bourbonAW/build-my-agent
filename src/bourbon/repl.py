"""REPL interface for Bourbon."""

import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.text import Text

from bourbon.agent import Agent, AgentError
from bourbon.config import Config
from bourbon.debug import debug_log
from bourbon.mcp_client import MCPServerNotInstalledError
from bourbon.permissions import PermissionChoice
from bourbon.tasks.service import TaskService
from bourbon.tasks.store import TaskStore


class StreamingDisplay:
    """Animated renderable for REPL activity plus the current pending text tail."""

    FRAMES = [
        "[     ]",
        "[=    ]",
        "[==   ]",
        "[===  ]",
        "[==== ]",
        "[=====]",
    ]
    FRAME_INTERVAL = 0.2

    def __init__(self, started_at: float):
        self.started_at = started_at
        self.has_streamed_text = False
        self.pending_tail = ""

    def append_chunk(self, text: str) -> None:
        """Mark streamed text as active in the live footer."""
        if text:
            self.has_streamed_text = True
            self.pending_tail += text

    def set_pending_tail(self, text: str) -> None:
        """Replace the pending tail shown in the live footer."""
        self.pending_tail = text

    def _frame(self) -> str:
        """Return the current animation frame."""
        elapsed = max(0.0, time.monotonic() - self.started_at)
        idx = int(elapsed / self.FRAME_INTERVAL) % len(self.FRAMES)
        return self.FRAMES[idx]

    def _status_text(self) -> Text:
        """Build the animated status line."""
        status_label = (
            "Bourbon is replying..." if self.has_streamed_text else "Bourbon is thinking..."
        )
        status = Text()
        status.append("🥃 ", style="bold #D4A373")
        status.append(self._frame(), style="bold #D4A373")
        status.append(" ")
        status.append(status_label, style="dim")
        return status

    def __rich_console__(self, console, options):
        renderables = [self._status_text()]
        if self.pending_tail:
            renderables.append(Text(self.pending_tail))
        yield Group(*renderables)


@dataclass
class _ActiveStreamState:
    """Bookkeeping for append-only streaming output."""

    live: Live
    display: StreamingDisplay
    full_text: str = ""
    flushed_text: str = ""


def _split_stable_markdown(buffer: str) -> tuple[str, str]:
    """Split accumulated text into a committed markdown prefix and pending tail.

    Commit only complete markdown blocks so multi-line structures such as
    headings, lists, tables, and fenced code blocks stay together.
    """
    if not buffer:
        return "", ""

    fence_count = 0
    last_block_boundary = 0
    offset = 0

    for line in buffer.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fence_count += 1

        if fence_count % 2 == 0 and line == "\n":
            last_block_boundary = offset + len(line)

        offset += len(line)

    if last_block_boundary > 0:
        return buffer[:last_block_boundary], buffer[last_block_boundary:]

    if "\n" not in buffer:
        return "", buffer

    if buffer.endswith("\n") and fence_count % 2 == 0:
        return "", buffer

    last_newline = buffer.rfind("\n")
    return buffer[: last_newline + 1], buffer[last_newline + 1 :]



class REPL:
    """Read-Eval-Print Loop for Bourbon."""

    # REPL commands
    COMMANDS = {
        "/exit": "Exit the REPL",
        "/quit": "Exit the REPL",
        "/compact": "Manually compress context",
        "/todos": "Show legacy in-memory todo list",
        "/tasks": "Show persistent workflow tasks",
        "/task <id>": "Show one workflow task",
        "/task-show <id>": "Show one workflow task",
        "/skills": "List available skills",
        "/mcp": "Show MCP server status",
        "/clear": "Clear conversation history",
        "/help": "Show help message",
    }

    # Skill activation prefix
    SKILL_PREFIX = "/skill/"

    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        session_id: uuid.UUID | None = None,
        resume_last: bool = False,
    ):
        """Initialize REPL.

        Args:
            config: Bourbon configuration
            workdir: Working directory
            session_id: Specific session to resume
            resume_last: Resume the latest session for this workdir
        """
        self.config = config
        self.workdir = workdir or Path.cwd()

        # Initialize Rich console
        self.console = Console()

        # Initialize agent with tool execution callbacks
        try:
            self.agent = Agent(
                config,
                workdir=workdir,
                on_tool_start=self._on_tool_start,
                on_tool_end=self._on_tool_end,
                session_id=session_id,
                resume_last=resume_last,
            )
        except AgentError as e:
            self.console.print(f"[red]Error initializing agent: {e}[/red]")
            sys.exit(1)

        # Initialize MCP connections
        self._init_mcp()

        # Initialize prompt session with history
        history_file = Path.home() / ".bourbon" / "history" / "bourbon_history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        self.session = PromptSession(
            message=self._get_prompt,
            bottom_toolbar=self._get_bottom_toolbar,
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            enable_history_search=True,
        )

        # Style for prompt
        self.style = Style.from_dict(
            {
                "prompt": "#5F9EA0 bold",  # Cadet blue
            }
        )

        # Bottom toolbar style
        self.toolbar_style = Style.from_dict(
            {
                "bottom-toolbar": "bg:#333333 #ffffff",
                "bottom-toolbar.text": "#888888",
            }
        )
        self._active_stream: _ActiveStreamState | None = None

    def _get_prompt(self) -> HTML:
        """Generate prompt."""
        return HTML("🥃 bourbon >> ")

    def _get_bottom_toolbar(self) -> HTML:
        """Generate bottom toolbar with context usage indicator (right-aligned)."""
        # Check if context display is disabled
        if not getattr(self.config.ui, "show_token_count", True):
            return HTML("")

        try:
            tokens = self.agent.get_session_tokens()
            threshold = self.agent.session.context_manager.token_threshold

            # Calculate percentage
            percent = min(100.0, (tokens / threshold * 100) if threshold > 0 else 0)

            # Format numbers
            tokens_k = tokens / 1000
            threshold_k = threshold / 1000

            # Color coding for toolbar
            if percent < 50:
                color = "#888888"  # gray
            elif percent < 80:
                color = "#FFA500"  # orange
            else:
                color = "#FF4444"  # red

            # Right-aligned context info using prompt_toolkit's right-aligned formatting
            ctx_text = f"context: {percent:.1f}% ({tokens_k:.1f}k/{threshold_k:.1f}k)"
            return HTML(f'<style fg="{color}">{ctx_text}</style>')
        except Exception:
            return HTML('<style fg="#888888">context: --</style>')

    def _on_tool_start(self, tool_name: str, tool_input: dict) -> None:
        """Callback when a tool starts executing.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters
        """
        # Format tool input for display
        params = ", ".join(f"{k}={repr(v)[:50]}" for k, v in tool_input.items())
        self._flush_stream_output(force_pending_tail=True)
        self.console.print(f"[dim]▶ {tool_name}({params})[/dim]")

    def _on_tool_end(self, tool_name: str, output: str) -> None:
        """Callback when a tool finishes executing.

        Args:
            tool_name: Name of the tool
            output: Tool output
        """
        # Show output preview (first line, truncated)
        output_preview = output.split("\n")[0][:100]
        if len(output) > 100:
            output_preview += "..."
        if len(output.split("\n")) > 1:
            output_preview += f" ({len(output.split(chr(10)))} lines)"

        # Use different color based on success/error
        self._flush_stream_output(force_pending_tail=True)
        if output.startswith("Error"):
            self.console.print(f"[red]✗ {tool_name}: {output_preview}[/red]")
        else:
            self.console.print(f"[green]✓ {tool_name}: {output_preview}[/green]")

    def _print_stream_delta(self, text: str) -> None:
        """Append a committed markdown delta to the terminal."""
        if not text:
            return
        self.console.print(Markdown(text))

    def _flush_stream_output(
        self,
        *,
        force_pending_tail: bool = False,
        render_pending_tail_as_markdown: bool = False,
    ) -> None:
        """Flush stable streamed output into the append-only terminal timeline."""
        state = self._active_stream
        if state is None:
            return

        stable_prefix, pending_tail = _split_stable_markdown(state.full_text)
        next_pending_tail = pending_tail

        if len(stable_prefix) > len(state.flushed_text):
            delta = stable_prefix[len(state.flushed_text) :]
            self._print_stream_delta(delta)
            state.flushed_text = stable_prefix

        if force_pending_tail and len(state.full_text) > len(state.flushed_text):
            forced_tail = state.full_text[len(state.flushed_text) :]
            if render_pending_tail_as_markdown:
                self.console.print(Markdown(forced_tail))
            else:
                self.console.print(Text(forced_tail))
            state.flushed_text = state.full_text
            next_pending_tail = ""

        state.display.set_pending_tail(next_pending_tail)
        state.live.refresh()

    def run(self) -> None:
        """Run the REPL loop."""
        try:
            self._print_banner()

            while True:
                try:
                    # Get user input
                    user_input = self.session.prompt(
                        style=self.style,
                    )

                    # Handle empty input
                    if not user_input.strip():
                        continue

                    # Handle commands
                    if user_input.strip().startswith("/"):
                        if self._handle_command(user_input.strip()):
                            break
                        continue

                    # Process user input through agent
                    self._process_input(user_input)

                except KeyboardInterrupt:
                    # Ctrl+C - continue loop
                    self.console.print("\n[yellow]Use /exit or Ctrl+D to quit[/yellow]")
                    continue
                except EOFError:
                    # Ctrl+D - exit
                    self.console.print("\n[dim]Goodbye![/dim]")
                    break
        finally:
            self._shutdown_mcp()

    def _process_input(self, user_input: str) -> None:
        """Process user input through agent.

        Args:
            user_input: User's message
        """
        self._process_input_streaming(user_input)

    def _process_input_streaming(self, user_input: str) -> None:
        """Process user input with streaming output and markdown rendering."""
        chunks: list[str] = []
        turn_id = uuid.uuid4().hex[:8]
        started_at = time.monotonic()
        streaming_display = StreamingDisplay(started_at=started_at)
        debug_log(
            "repl.stream.start",
            turn_id=turn_id,
            user_input_len=len(user_input),
        )

        try:
            self.console.print()  # New line before streaming starts

            # Create a live display for streaming content
            with Live(
                streaming_display,
                console=self.console,
                refresh_per_second=10,
                transient=True,
            ) as live:
                self._active_stream = _ActiveStreamState(
                    live=live,
                    display=streaming_display,
                )

                def on_chunk(text: str) -> None:
                    chunks.append(text)
                    streaming_display.append_chunk(text)
                    self._active_stream.full_text += text
                    self._flush_stream_output()
                    current_text = self._active_stream.full_text
                    debug_log(
                        "repl.stream.chunk",
                        turn_id=turn_id,
                        chunk_len=len(text),
                        chunk_count=len(chunks),
                        current_text_len=len(current_text),
                    )
                response = self.agent.step_stream(user_input, on_chunk)
                if self._active_stream.full_text != response:
                    self._active_stream.full_text = response
                self._flush_stream_output(
                    force_pending_tail=True,
                    render_pending_tail_as_markdown=True,
                )

            self._active_stream = None

            debug_log(
                "repl.stream.response",
                turn_id=turn_id,
                response_len=len(response),
                chunk_count=len(chunks),
            )
            debug_log(
                "repl.stream.complete",
                turn_id=turn_id,
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                has_active_permission_request=bool(self.agent.active_permission_request),
            )

        except Exception as e:
            self._active_stream = None
            debug_log(
                "repl.stream.error",
                turn_id=turn_id,
                error=str(e),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            self.console.print(f"[red]Error: {e}[/red]")
            return

        # Handle pending permission request if needed
        if self.agent.active_permission_request:
            self._handle_permission_request()

    def _handle_permission_request(self) -> None:
        """Handle a pending permission request through the dedicated resume API."""
        request = self.agent.active_permission_request
        if not request:
            return

        self.console.print()
        self.console.print(f"[bold yellow]{request.title}[/bold yellow]")
        self.console.print("[dim]" + "━" * 50 + "[/dim]")
        self.console.print(f"[bold]Tool:[/bold] {request.tool_name}")
        self.console.print(f"[bold]Reason:[/bold] {request.reason}")
        self.console.print(f"[bold]Summary:[/bold] {request.description}")
        self.console.print()
        self.console.print("  [bold][1][/bold] Allow once")
        self.console.print("  [bold][2][/bold] Allow for session")
        self.console.print("  [bold][3][/bold] Reject")
        self.console.print()

        while True:
            try:
                choice = self.session.prompt("Enter your choice: ", style=self.style).strip()
                if choice == "1":
                    response = self.agent.resume_permission_request(PermissionChoice.ALLOW_ONCE)
                    break
                if choice == "2":
                    response = self.agent.resume_permission_request(PermissionChoice.ALLOW_SESSION)
                    break
                if choice == "3":
                    response = self.agent.resume_permission_request(PermissionChoice.REJECT)
                    break
                self.console.print("[red]Invalid choice. Please try again.[/red]")
            except (KeyboardInterrupt, EOFError):
                response = self.agent.resume_permission_request(PermissionChoice.REJECT)
                break

        if response:
            self._print_response(response)

    def _print_response(self, response: str) -> None:
        """Print agent response with formatting.

        Args:
            response: Response text
        """
        if not response:
            return

        # Check if response contains code blocks
        if "```" in response:
            # Print as markdown
            self.console.print(Markdown(response))
        else:
            # Print plain text with word-by-word effect for short responses
            if len(response) < 500 and "\n" not in response:
                self._print_streaming(response)
            else:
                self.console.print(response)

    def _print_streaming(self, text: str, delay: float = 0.01) -> None:
        """Print text with streaming effect.

        Args:
            text: Text to print
            delay: Delay between words in seconds
        """
        import time

        words = text.split(" ")
        for i, word in enumerate(words):
            self.console.print(word, end="")
            if i < len(words) - 1:
                self.console.print(" ", end="")
            time.sleep(delay)
        self.console.print()  # Final newline

    def _handle_command(self, command: str) -> bool:
        """Handle REPL command.

        Args:
            command: Command string

        Returns:
            True if REPL should exit
        """
        cmd = command.lower()
        parts = command.split(maxsplit=1)
        base_cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        arg_parts = arg.split() if arg else []

        # Handle skill activation via /skill/skill-name
        if cmd.startswith(self.SKILL_PREFIX):
            skill_name = command[len(self.SKILL_PREFIX) :]
            if skill_name:
                self._activate_skill(skill_name)
            else:
                self.console.print("[red]Usage: /skill/skill-name[/red]")
            return False

        if base_cmd in ("/exit", "/quit"):
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            self.console.print("[dim]Goodbye![/dim]")
            return True

        elif base_cmd == "/compact":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            from bourbon.session.types import CompactTrigger
            result = self.agent.session.maybe_compact(trigger=CompactTrigger.MANUAL)
            if result and result.success:
                self.console.print(
                    f"[dim]Context compressed: {result.archived_count} messages archived.[/dim]"
                )
            else:
                self.console.print("[dim]Context compressed.[/dim]")

        elif base_cmd == "/todos":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            self.console.print(self.agent.get_todos())

        elif base_cmd == "/tasks":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            try:
                self.console.print(self._render_workflow_tasks())
            except Exception as e:
                safe_error = self._safe_task_value(e)
                self.console.print(f"[red]Error reading workflow tasks: {safe_error}[/red]")

        elif base_cmd in ("/task", "/task-show"):
            if len(arg_parts) != 1:
                self.console.print(f"[red]Usage: {base_cmd} <id>[/red]")
            else:
                try:
                    self.console.print(self._render_workflow_task(arg_parts[0]))
                except Exception as e:
                    safe_task_id = self._safe_task_value(arg_parts[0])
                    safe_error = self._safe_task_value(e)
                    self.console.print(
                        f"[red]Error reading workflow task {safe_task_id}: {safe_error}[/red]"
                    )

        elif base_cmd == "/skills":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            skills = self.agent.skills.available_skills
            if skills:
                self.console.print("[bold]Available skills:[/bold]")
                for name in sorted(skills):
                    skill = self.agent.skills.get_skill(name)
                    if skill:
                        self.console.print(f"  • [bold]{name}[/bold]: {skill.description}")
            else:
                self.console.print("[dim]No skills available.[/dim]")

        elif base_cmd == "/mcp":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            self._print_mcp_status()

        elif base_cmd == "/clear":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            self.agent.clear_history()
            self.console.print("[dim]Conversation history cleared.[/dim]")

        elif base_cmd == "/help":
            if self._reject_unexpected_args(base_cmd, arg):
                return False
            self._print_help()

        else:
            self.console.print(f"[red]Unknown command: {command}[/red]")
            self.console.print("Type /help for available commands.")

        return False

    def _reject_unexpected_args(self, command: str, arg: str) -> bool:
        """Print a usage error when a no-argument command receives trailing input."""
        if not arg:
            return False
        self.console.print(f"[red]Usage: {command}[/red]")
        return True

    def _task_service(self) -> TaskService:
        """Return the workflow task service for the current REPL session."""
        storage_dir = Path(self.agent.config.tasks.storage_dir).expanduser()
        return TaskService(TaskStore(storage_dir))

    def _task_list_id(self) -> str:
        """Resolve the current workflow task list id, preferring the session id."""
        session = getattr(self.agent, "session", None)
        session_id = getattr(session, "session_id", None)
        if session_id is not None:
            return str(session_id)
        return str(self.agent.config.tasks.default_list_id)

    def _render_workflow_tasks(self) -> str:
        """Render the current session's workflow tasks."""
        records = self._task_service().list_tasks(self._task_list_id())
        if not records:
            return "No workflow tasks."

        lines = []
        for record in records:
            line = (
                f"{self._safe_task_value(record.id)}. "
                f"\\[{self._safe_task_value(record.status)}\\] "
                f"{self._safe_task_value(record.subject)}"
            )
            if record.active_form:
                line += f" <- {self._safe_task_value(record.active_form)}"
            if record.owner:
                line += f" (owner: {self._safe_task_value(record.owner)})"
            if record.blocked_by:
                line += " blocked_by=" + ",".join(
                    self._safe_task_value(blocker_id) for blocker_id in record.blocked_by
                )
            lines.append(line)
        return "\n".join(lines)

    def _render_workflow_task(self, task_id: str) -> str:
        """Render one workflow task from the current session's task list."""
        record = self._task_service().get_task(self._task_list_id(), task_id)
        if record is None:
            return f"Task not found: {self._safe_task_value(task_id)}"

        lines = [
            f"ID: {self._safe_task_value(record.id)}",
            f"Subject: {self._safe_task_value(record.subject)}",
            f"Description: {self._safe_task_value(record.description)}",
            f"Status: {self._safe_task_value(record.status)}",
            f"Active: {self._safe_task_value(record.active_form or '-')}",
            f"Owner: {self._safe_task_value(record.owner or '-')}",
            "Blocks: "
            + (
                ", ".join(self._safe_task_value(block_id) for block_id in record.blocks)
                if record.blocks
                else "-"
            ),
            "Blocked by: "
            + (
                ", ".join(self._safe_task_value(blocker_id) for blocker_id in record.blocked_by)
                if record.blocked_by
                else "-"
            ),
        ]
        return "\n".join(lines)

    @staticmethod
    def _safe_task_value(value: object) -> str:
        """Escape user-controlled task fields before printing through Rich."""
        return escape(str(value))

    def _activate_skill(self, skill_name: str) -> None:
        """Activate a skill and display its content.

        Args:
            skill_name: Name of skill to activate
        """
        try:
            from bourbon.session.types import MessageRole, TextBlock, TranscriptMessage

            content = self.agent.skills.activate(skill_name)
            self.console.print(f"[green]✓ Skill '{skill_name}' activated[/green]")
            # Add to conversation context via Session
            self.agent.session.add_message(TranscriptMessage(
                role=MessageRole.USER,
                content=[TextBlock(
                    text=f"[User activated skill: {skill_name}]\n\n{content}"
                )],
            ))
            self.agent.session.save()
            self.console.print("[dim]Skill instructions loaded into context.[/dim]")
        except Exception as e:
            self.console.print(f"[red]Error activating skill: {e}[/red]")

    def _print_banner(self) -> None:
        """Print welcome banner."""
        banner = """[bold #D4A373]
🥃 Bourbon - General-Purpose Agent
[/bold #D4A373]
Type your message or use [bold]/help[/bold] for commands.
Use [bold]Ctrl+D[/bold] or [bold]/exit[/bold] to quit.
"""
        self.console.print(banner)

    def _print_help(self) -> None:
        """Print help message."""
        self.console.print("[bold]Available commands:[/bold]")
        for cmd, desc in self.COMMANDS.items():
            self.console.print(f"  [bold]{cmd}[/bold] - {desc}")
        self.console.print(
            "  [bold]/skill/name[/bold] - Activate a skill (e.g., /skill/python-refactoring)"
        )
        self.console.print()
        self.console.print("All other input is sent to the AI agent.")

    def _init_mcp(self) -> None:
        """Initialize MCP connections."""
        if not self.config.mcp.enabled:
            return

        try:
            self.agent.initialize_mcp_sync(timeout=60.0)

            summary = self.agent.mcp.get_connection_summary()
            if summary["connected"] > 0:
                self.console.print(
                    f"[dim]MCP: Connected to {summary['connected']} server(s), "
                    f"{summary['total_tools']} tool(s) available[/dim]"
                )
            if summary["failed"] > 0:
                self.console.print(
                    f"[yellow]MCP: {summary['failed']} server(s) failed to connect[/yellow]"
                )
        except MCPServerNotInstalledError as e:
            # Fatal error: MCP server not installed, exit immediately
            self.console.print(f"[bold red]MCP Error: {e}[/bold red]")
            self.console.print("\n[yellow]To fix this issue:[/yellow]")
            self.console.print("1. Install the missing MCP server package, OR")
            self.console.print("2. Disable the MCP server in ~/.bourbon/config.toml")
            sys.exit(1)
        except Exception as e:
            import traceback

            self.console.print(f"[yellow]MCP initialization failed: {e}[/yellow]")
            self.console.print("[dim red]Detailed error:[/dim red]")
            for line in traceback.format_exc().split("\n"):
                self.console.print(f"[dim red]{line}[/dim red]")
            self.console.print("[dim]Continuing without MCP tools...[/dim]")

    def _shutdown_mcp(self) -> None:
        """Disconnect MCP connections before process exit."""
        if not self.config.mcp.enabled:
            return

        try:
            self.agent.shutdown_mcp_sync(timeout=10.0)
        except Exception as e:
            self.console.print(f"[yellow]MCP shutdown warning: {e}[/yellow]")

    def _print_mcp_status(self) -> None:
        """Print MCP connection status."""
        summary = self.agent.mcp.get_connection_summary()

        if not summary["enabled"]:
            self.console.print("[dim]MCP is disabled.[/dim]")
            return

        self.console.print("[bold]MCP Server Status:[/bold]")
        self.console.print(f"  Enabled: {summary['enabled']}")
        self.console.print(f"  Configured: {summary['configured']} server(s)")
        self.console.print(f"  Connected: {summary['connected']} server(s)")
        self.console.print(f"  Failed: {summary['failed']} server(s)")
        self.console.print(f"  Total Tools: {summary['total_tools']}")

        if summary["servers"]:
            self.console.print()
            self.console.print("[bold]Server Details:[/bold]")
            for name, status in sorted(summary["servers"].items()):
                if status["connected"]:
                    self.console.print(
                        f"  • [green]{name}[/green]: Connected ({status['tools']} tools)"
                    )
                else:
                    error = status.get("error", "Unknown error")
                    self.console.print(f"  • [red]{name}[/red]: Failed - {error}")

        mcp_tools = self.agent.mcp.list_mcp_tools()
        if mcp_tools:
            self.console.print()
            self.console.print("[bold]Available MCP Tools:[/bold]")
            for tool_name in sorted(mcp_tools):
                self.console.print(f"  • {tool_name}")
