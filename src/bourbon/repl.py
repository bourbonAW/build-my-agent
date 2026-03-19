"""REPL interface for Bourbon."""

import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from bourbon.agent import Agent, AgentError
from bourbon.config import Config, ConfigManager


class REPL:
    """Read-Eval-Print Loop for Bourbon."""

    # REPL commands
    COMMANDS = {
        "/exit": "Exit the REPL",
        "/quit": "Exit the REPL",
        "/compact": "Manually compress context",
        "/tasks": "Show todo list",
        "/skills": "List available skills",
        "/clear": "Clear conversation history",
        "/help": "Show help message",
    }

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

        # Initialize prompt session with history
        history_file = Path.home() / ".bourbon" / "history" / "bourbon_history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        self.session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            enable_history_search=True,
        )

        # Style for prompt
        self.style = Style.from_dict({
            "prompt": "#5F9EA0 bold",  # Cadet blue
        })

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
        self._print_banner()

        while True:
            try:
                # Get user input
                user_input = self.session.prompt(
                    "🥃 bourbon >> ",
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

    def _process_input(self, user_input: str) -> None:
        """Process user input through agent.

        Args:
            user_input: User's message
        """
        # Show thinking status
        self.console.print("[dim]Thinking...[/dim]")
        
        try:
            response = self.agent.step(user_input)
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
            return

        # Print response
        self.console.print()  # Blank line before response
        self._print_response(response)

    def _print_response(self, response: str) -> None:
        """Print agent response with formatting.

        Args:
            response: Response text
        """
        # Check if response contains code blocks
        if "```" in response:
            # Print as markdown
            self.console.print(Markdown(response))
        else:
            # Print plain text
            self.console.print(response)

    def _handle_command(self, command: str) -> bool:
        """Handle REPL command.

        Args:
            command: Command string

        Returns:
            True if REPL should exit
        """
        cmd = command.lower()

        if cmd in ("/exit", "/quit"):
            self.console.print("[dim]Goodbye![/dim]")
            return True

        elif cmd == "/compact":
            self.agent._manual_compact()
            self.console.print("[dim]Context compressed.[/dim]")

        elif cmd == "/tasks":
            todos = self.agent.get_todos()
            self.console.print(todos)

        elif cmd == "/skills":
            skills = self.agent.skills.list_skills()
            if skills:
                self.console.print("[bold]Available skills:[/bold]")
                for skill in skills:
                    self.console.print(f"  • {skill.name}: {skill.description}")
            else:
                self.console.print("[dim]No skills loaded.[/dim]")

        elif cmd == "/clear":
            self.agent.clear_history()
            self.console.print("[dim]Conversation history cleared.[/dim]")

        elif cmd == "/help":
            self._print_help()

        else:
            self.console.print(f"[red]Unknown command: {command}[/red]")
            self.console.print("Type /help for available commands.")

        return False

    def _print_banner(self) -> None:
        """Print welcome banner."""
        banner = """[bold #D4A373]
🥃 Bourbon - Code Specialist Agent
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
        self.console.print()
        self.console.print("All other input is sent to the AI agent.")
