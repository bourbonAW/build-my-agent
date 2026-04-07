"""CLI entry point for Bourbon."""

import argparse
import sys
from pathlib import Path
from uuid import UUID

from rich.console import Console
from rich.prompt import Prompt

from bourbon import __version__
from bourbon.config import ConfigManager
from bourbon.repl import REPL


def init_config() -> None:
    """Initialize Bourbon configuration interactively."""
    console = Console()
    console.print("[bold]🥃 Bourbon Configuration Setup[/bold]\n")

    manager = ConfigManager()

    # Check if already exists
    if manager.get_config_path().exists():
        overwrite = Prompt.ask(
            "Configuration already exists. Overwrite?",
            choices=["y", "n"],
            default="n",
        )
        if overwrite != "y":
            console.print("[dim]Setup cancelled.[/dim]")
            return

    # Get API keys
    console.print("[bold]LLM Provider Configuration[/bold]\n")

    # Anthropic
    anthropic_key = Prompt.ask(
        "Anthropic API key (press Enter to skip)",
        password=True,
    )

    # OpenAI
    openai_key = Prompt.ask(
        "OpenAI API key (press Enter to skip)",
        password=True,
    )

    # Create config
    manager.create_default_config(
        anthropic_key=anthropic_key,
        openai_key=openai_key,
    )

    config_path = manager.get_config_path()
    console.print(f"\n[green]Configuration saved to:[/green] {config_path}")

    if anthropic_key:
        console.print("[green]✓[/green] Anthropic configured")
    if openai_key:
        console.print("[green]✓[/green] OpenAI configured")

    if not anthropic_key and not openai_key:
        console.print("[yellow]⚠ No API keys configured.[/yellow]")
        console.print("Run [bold]bourbon --init[/bold] again to add keys.")


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        prog="bourbon",
        description="🥃 Bourbon - A general-purpose agent platform",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize configuration",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Working directory (default: current directory)",
    )
    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--session-id",
        type=UUID,
        default=None,
        help="Resume a specific session by UUID",
    )
    session_group.add_argument(
        "--resume-last",
        action="store_true",
        help="Resume the most recent session for this workdir",
    )

    args = parser.parse_args()

    if args.version:
        print(f"Bourbon {__version__}")
        return 0

    if args.init:
        init_config()
        return 0

    # Run REPL
    manager = ConfigManager()

    try:
        config = manager.load_config()
    except FileNotFoundError as e:
        console = Console()
        console.print(f"[red]Error: {e}[/red]")
        console.print("\nRun [bold]bourbon --init[/bold] to create a configuration.")
        return 1

    repl = REPL(
        config,
        workdir=args.workdir,
        session_id=args.session_id,
        resume_last=args.resume_last,
    )
    repl.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
