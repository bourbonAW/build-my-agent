"""REPL interface for Bourbon."""

import sys
import time
import uuid
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from bourbon.agent import Agent, AgentError
from bourbon.config import Config
from bourbon.debug import debug_log
from bourbon.mcp_client import MCPServerNotInstalledError


class StreamingDisplay:
    """Animated renderable for REPL activity plus streamed markdown output."""

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
        self.current_text = ""

    def append_chunk(self, text: str) -> None:
        """Append streamed text to the live buffer."""
        if text:
            self.has_streamed_text = True
            self.current_text += text

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
        stable_prefix, pending_tail = _split_stable_markdown(self.current_text)
        renderables = [self._status_text()]
        if stable_prefix:
            renderables.append(Markdown(stable_prefix))
        if pending_tail:
            renderables.append(Text(pending_tail))
        yield Group(*renderables)


def _split_stable_markdown(buffer: str) -> tuple[str, str]:
    """Split accumulated text into a stable markdown prefix and pending tail."""
    if not buffer:
        return "", ""

    if buffer.endswith("\n"):
        stable_prefix = buffer
        pending_tail = ""
    else:
        last_newline = buffer.rfind("\n")
        if last_newline == -1:
            return "", buffer
        stable_prefix = buffer[: last_newline + 1]
        pending_tail = buffer[last_newline + 1 :]

    return stable_prefix, pending_tail



class REPL:
    """Read-Eval-Print Loop for Bourbon."""

    # REPL commands
    COMMANDS = {
        "/exit": "Exit the REPL",
        "/quit": "Exit the REPL",
        "/compact": "Manually compress context",
        "/tasks": "Show todo list",
        "/skills": "List available skills",
        "/mcp": "Show MCP server status",
        "/clear": "Clear conversation history",
        "/help": "Show help message",
    }

    # Skill activation prefix
    SKILL_PREFIX = "/skill/"

    def __init__(self, config: Config, workdir: Path | None = None):
        """Initialize REPL.

        Args:
            config: Bourbon configuration
            workdir: Working directory
        """
        self.config = config
        self.workdir = workdir or Path.cwd()

        # Initialize Rich console
        self.console = Console()

        # Initialize agent with tool execution callbacks
        try:
            self.agent = Agent(
                config,
                workdir,
                on_tool_start=self._on_tool_start,
                on_tool_end=self._on_tool_end,
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
        if output.startswith("Error"):
            self.console.print(f"[red]✗ {tool_name}: {output_preview}[/red]")
        else:
            self.console.print(f"[green]✓ {tool_name}: {output_preview}[/green]")

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
                def on_chunk(text: str) -> None:
                    chunks.append(text)
                    streaming_display.append_chunk(text)
                    # Update live display with accumulated text
                    current_text = "".join(chunks)
                    debug_log(
                        "repl.stream.chunk",
                        turn_id=turn_id,
                        chunk_len=len(text),
                        chunk_count=len(chunks),
                        current_text_len=len(current_text),
                    )
                    live.refresh()

                response = self.agent.step_stream(user_input, on_chunk)

            # After streaming completes, render the full response with markdown
            # Check if response contains markdown that needs special rendering
            debug_log(
                "repl.stream.response",
                turn_id=turn_id,
                response_len=len(response),
                chunk_count=len(chunks),
            )

            self.console.print(Markdown(response))
            debug_log(
                "repl.stream.complete",
                turn_id=turn_id,
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                has_pending_confirmation=bool(self.agent.pending_confirmation),
            )

        except Exception as e:
            debug_log(
                "repl.stream.error",
                turn_id=turn_id,
                error=str(e),
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
            )
            self.console.print(f"[red]Error: {e}[/red]")
            return

        # Handle pending confirmation if needed
        if self.agent.pending_confirmation:
            self._handle_pending_confirmation()

    def _handle_pending_confirmation(self) -> None:
        """Handle pending user confirmation for high-risk operation failure."""
        conf = self.agent.pending_confirmation
        if not conf:
            return

        # Print confirmation prompt with styling
        self.console.print()
        self.console.print("[bold red]⚠️  HIGH-RISK OPERATION FAILED[/bold red]")
        self.console.print("[dim]" + "━" * 50 + "[/dim]")
        self.console.print(f"[bold]Operation:[/bold] {conf.tool_name}")
        self.console.print(f"[bold]Input:[/bold] {conf.tool_input}")
        self.console.print(f"[bold red]Error:[/bold red] {conf.error_output}")
        self.console.print()
        self.console.print(
            "[yellow]This is a high-risk operation. Please choose how to proceed:[/yellow]"
        )
        self.console.print()

        for i, option in enumerate(conf.options, 1):
            self.console.print(f"  [bold][{i}][/bold] {option}")
        self.console.print("  [bold][c][/bold] Cancel this operation")
        self.console.print()

        # Get user choice
        while True:
            try:
                choice = (
                    self.session.prompt(
                        "Enter your choice: ",
                        style=self.style,
                    )
                    .strip()
                    .lower()
                )

                if choice == "c":
                    user_decision = "Cancel this operation"
                    break
                elif choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(conf.options):
                        user_decision = conf.options[idx]
                        break

                self.console.print("[red]Invalid choice. Please try again.[/red]")
            except (KeyboardInterrupt, EOFError):
                user_decision = "Cancel this operation"
                break

        # Continue with user decision
        self.console.print(f"[dim]Proceeding with: {user_decision}[/dim]")
        self._process_input(user_decision)

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

        # Handle skill activation via /skill/skill-name
        if cmd.startswith(self.SKILL_PREFIX):
            skill_name = command[len(self.SKILL_PREFIX) :]
            if skill_name:
                self._activate_skill(skill_name)
            else:
                self.console.print("[red]Usage: /skill/skill-name[/red]")
            return False

        if cmd in ("/exit", "/quit"):
            self.console.print("[dim]Goodbye![/dim]")
            return True

        elif cmd == "/compact":
            from bourbon.session.types import CompactTrigger
            result = self.agent.session.maybe_compact(trigger=CompactTrigger.MANUAL)
            if result and result.success:
                self.console.print(
                    f"[dim]Context compressed: {result.archived_count} messages archived.[/dim]"
                )
            else:
                self.console.print("[dim]Context compressed.[/dim]")

        elif cmd == "/tasks":
            todos = self.agent.get_todos()
            self.console.print(todos)

        elif cmd == "/skills":
            skills = self.agent.skills.available_skills
            if skills:
                self.console.print("[bold]Available skills:[/bold]")
                for name in sorted(skills):
                    skill = self.agent.skills.get_skill(name)
                    if skill:
                        self.console.print(f"  • [bold]{name}[/bold]: {skill.description}")
            else:
                self.console.print("[dim]No skills available.[/dim]")

        elif cmd == "/mcp":
            self._print_mcp_status()

        elif cmd == "/clear":
            self.agent.clear_history()
            self.console.print("[dim]Conversation history cleared.[/dim]")

        elif cmd == "/help":
            self._print_help()

        else:
            self.console.print(f"[red]Unknown command: {command}[/red]")
            self.console.print("Type /help for available commands.")

        return False

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
