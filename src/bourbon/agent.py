"""Core agent loop for Bourbon."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from bourbon.compression import ContextCompressor
from bourbon.config import Config
from bourbon.llm import LLMClient, LLMError, create_client
from bourbon.mcp_client import MCPManager
from bourbon.skills import SkillManager
from bourbon.todos import TodoManager
from bourbon.tools import definitions, get_tool_with_metadata, handler, get_registry


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


class Agent:
    """Bourbon agent."""

    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
    ):
        """Initialize agent."""
        self.config = config
        self.workdir = workdir or Path.cwd()
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end

        # Initialize components
        self.todos = TodoManager()
        self.skills = SkillManager(self.workdir)
        self.compressor = ContextCompressor(
            token_threshold=config.ui.token_threshold,
        )

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
        self.system_prompt = self._build_system_prompt()

        # Message history
        self.messages: list[dict] = []

        # Track rounds without todo update for nagging
        self._rounds_without_todo = 0

        # Maximum tool execution rounds to prevent infinite loops
        # Can be configured via config.ui.max_tool_rounds (default: 50)
        self._max_tool_rounds = getattr(config.ui, 'max_tool_rounds', 50)
        
        # Pending confirmation for high-risk operation failures
        self.pending_confirmation: PendingConfirmation | None = None

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
        if results:
            summary = self.mcp.get_connection_summary()
            if summary["total_tools"] > 0:
                self.system_prompt = self._build_system_prompt()
        return results

    def _build_system_prompt(self) -> str:
        """Build system prompt with skills and instructions."""
        lines = [
            f"You are Bourbon, a coding assistant at {self.workdir}.",
            "",
            "Use the available tools to help the user with their coding tasks.",
            "When working on multi-step tasks, use TodoWrite to track progress.",
            "",
            "IMPORTANT: Do not repeat the same actions. If you've already explored the codebase,",
            "analyze what you found and provide a summary. Avoid getting stuck in loops.",
            "",
            "CRITICAL: When you want to use a tool, you MUST use the tool_calls format.",
            "Do not just describe what you plan to do - actually invoke the tools.",
            "",
            self._get_skills_section(),
            "",
            self._get_mcp_section(),
            "",
            "CRITICAL ERROR HANDLING RULES:",
            "1. HIGH RISK operations (software install/uninstall, version changes, system commands, destructive operations):",
            "   - If the operation fails (e.g., version not found, package unavailable), you MUST STOP and ask the user for confirmation",
            "   - NEVER automatically switch versions, install alternatives, or change parameters without user approval",
            "   - Examples: pip install package==wrong_version, apt install nonexistent-package, rm important-files",
            "",
            "2. LOW RISK operations (read_file, search, exploration):",
            "   - If a file is not found, you MAY search for similar files and attempt to read the correct one",
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
        if not hasattr(self, 'mcp'):
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
            f"The following external tools are available from MCP servers:",
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
            '  <function_calls>',
            '    <invoke name="skill">',
            '      <parameter name="name">skill-name</parameter>',
            '    </invoke>',
            '  </function_calls>',
        ]
        return "\n".join(lines)

    def step(self, user_input: str) -> str:
        """Process one user input and return assistant response."""
        # Check if we're resuming from a pending confirmation
        if self.pending_confirmation:
            return self._handle_confirmation_response(user_input)
        
        # Add user message
        self.messages.append({"role": "user", "content": user_input})

        # Pre-process: micro-compact
        self.compressor.microcompact(self.messages)

        # Check if we need full compression
        if self.compressor.should_compact(self.messages):
            self._auto_compact()

        # Run the conversation loop
        return self._run_conversation_loop()
    
    def _handle_confirmation_response(self, user_input: str) -> str:
        """Handle user response to a pending confirmation."""
        confirmation = self.pending_confirmation
        self.pending_confirmation = None
        
        # Add the user's choice to the conversation
        context = (
            f"[Previous high-risk operation failed: {confirmation.tool_name}]\n"
            f"[Error: {confirmation.error_output}]\n"
            f"[User decision: {user_input}]\n"
            f"Please proceed based on the user's decision above."
        )
        self.messages.append({"role": "user", "content": context})
        
        # Continue the conversation
        return self._run_conversation_loop()

    def _run_conversation_loop(self) -> str:
        """Run conversation loop until we get a final response."""
        tool_round = 0

        while tool_round < self._max_tool_rounds:
            # Call LLM
            try:
                response = self.llm.chat(
                    messages=self.messages,
                    tools=definitions(),
                    system=self.system_prompt,
                    max_tokens=64000,
                )
            except LLMError as e:
                error_msg = f"LLM Error: {e}"
                self.messages.append({"role": "assistant", "content": error_msg})
                return error_msg

            # Debug: log response (uncomment for debugging)
            # print(f"[DEBUG] Response stop_reason: {response.get('stop_reason')}")
            # print(f"[DEBUG] Response content blocks: {[b.get('type') for b in response.get('content', [])]}")

            # Check if response contains tool calls
            has_tool_calls = response["stop_reason"] == "tool_use"
            tool_use_blocks = [b for b in response["content"] if b.get("type") == "tool_use"]
            
            if not has_tool_calls and tool_use_blocks:
                # Sometimes stop_reason is not tool_use but we have tool_use blocks
                has_tool_calls = True
                # print(f"[DEBUG] Found {len(tool_use_blocks)} tool_use blocks despite stop_reason")

            # Add assistant response to history
            self.messages.append({"role": "assistant", "content": response["content"]})

            if not has_tool_calls:
                # Extract and return text response
                text_parts = [
                    block["text"]
                    for block in response["content"]
                    if block.get("type") == "text"
                ]
                return "".join(text_parts)

            # Execute tools
            if tool_use_blocks:
                tool_results = self._execute_tools(tool_use_blocks)
                
                # Check if we have a pending confirmation (high-risk error)
                if self.pending_confirmation:
                    # Return confirmation prompt to user
                    return self._format_confirmation_prompt()
                
                # Add tool results to history
                self.messages.append({"role": "user", "content": tool_results})
            else:
                # No actual tool_use blocks found despite stop_reason
                print("[DEBUG] stop_reason was tool_use but no tool_use blocks found!")
                text_parts = [
                    block["text"]
                    for block in response["content"]
                    if block.get("type") == "text"
                ]
                return "".join(text_parts)
            
            tool_round += 1

        return "[Reached maximum tool execution rounds. Providing final response based on what was learned.]"
    
    def _format_confirmation_prompt(self) -> str:
        """Format pending confirmation for display to user."""
        if not self.pending_confirmation:
            return ""
        
        conf = self.pending_confirmation
        lines = [
            "",
            "⚠️  HIGH-RISK OPERATION FAILED",
            "━" * 50,
            f"Operation: {conf.tool_name}",
            f"Input: {conf.tool_input}",
            f"Error: {conf.error_output}",
            "",
            "This is a high-risk operation. Please choose how to proceed:",
            "",
        ]
        for i, option in enumerate(conf.options, 1):
            lines.append(f"  [{i}] {option}")
        lines.append("  [c] Cancel this operation")
        lines.append("")
        lines.append("Enter your choice: ")
        
        return "\n".join(lines)

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
                skill_name = tool_input.get("name", "")
                output = self.skills.load(skill_name)
            else:
                # Execute regular tool
                tool_handler = handler(tool_name)
                tool_metadata = get_tool_with_metadata(tool_name)
                
                if tool_handler:
                    try:
                        output = tool_handler(**tool_input)
                        
                        # Check for high-risk operation failure
                        if (
                            tool_metadata
                            and output.startswith("Error")
                            and tool_metadata.is_high_risk_operation(tool_input)
                        ):
                            # Store pending confirmation and stop tool execution
                            self.pending_confirmation = PendingConfirmation(
                                tool_name=tool_name,
                                tool_input=tool_input,
                                error_output=output,
                                options=self._generate_options(tool_name, tool_input, output),
                            )
                            
                            if self.on_tool_end:
                                self.on_tool_end(tool_name, output)
                            
                            # Return partial results with error marker
                            results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": str(output)[:50000],
                            })
                            return results
                            
                    except Exception as e:
                        output = f"Error executing {tool_name}: {e}"
                else:
                    output = f"Unknown tool: {tool_name}"

            # Notify end of tool execution
            if self.on_tool_end:
                self.on_tool_end(tool_name, output)

            results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": str(output)[:50000],
            })

        # Todo nag
        self._rounds_without_todo = 0 if used_todo else self._rounds_without_todo + 1
        if self.todos.has_open_items() and self._rounds_without_todo >= 3:
            results.insert(0, {
                "type": "text",
                "text": "<reminder>You have open todos. Consider updating them.</reminder>",
            })

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

    def _auto_compact(self) -> None:
        """Perform automatic context compression."""
        self.messages = self.compressor.compact(self.messages)

    def _manual_compact(self) -> None:
        """Perform manual context compression."""
        self._auto_compact()

    def get_todos(self) -> str:
        """Get current todo list."""
        return self.todos.render()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages = []
