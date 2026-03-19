"""Core agent loop for Bourbon."""

from pathlib import Path

from bourbon.compression import ContextCompressor
from bourbon.config import Config
from bourbon.llm import LLMClient, LLMError, create_client
from bourbon.skills import SkillLoader
from bourbon.todos import TodoManager
from bourbon.tools import definitions, handler


class AgentError(Exception):
    """Agent execution error."""

    pass


class Agent:
    """Bourbon agent."""

    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
    ):
        """Initialize agent.

        Args:
            config: Bourbon configuration
            workdir: Working directory (default: current directory)
        """
        self.config = config
        self.workdir = workdir or Path.cwd()

        # Initialize components
        self.todos = TodoManager()
        self.skills = SkillLoader()
        self.compressor = ContextCompressor(
            token_threshold=config.ui.token_threshold,
        )

        # Initialize LLM client
        try:
            self.llm = create_client(config)
        except LLMError as e:
            raise AgentError(f"Failed to initialize LLM: {e}") from e

        # Build system prompt
        self.system_prompt = self._build_system_prompt()

        # Message history
        self.messages: list[dict] = []

        # Track rounds without todo update for nagging
        self._rounds_without_todo = 0

        # Maximum tool execution rounds to prevent infinite loops
        self._max_tool_rounds = 10

    def _build_system_prompt(self) -> str:
        """Build system prompt with skills and instructions."""
        lines = [
            f"You are Bourbon, a coding assistant at {self.workdir}.",
            "",
            "Use the available tools to help the user with their coding tasks.",
            "When working on multi-step tasks, use TodoWrite to track progress.",
            "For complex operations, consider using rg_search or ast_grep_search to understand the codebase.",
            "",
            "Available skills (load with load_skill):",
            self.skills.descriptions(),
        ]
        return "\n".join(lines)

    def step(self, user_input: str) -> str:
        """Process one user input and return assistant response.

        Args:
            user_input: User's message

        Returns:
            Assistant's response text
        """
        # Add user message
        self.messages.append({"role": "user", "content": user_input})

        # Pre-process: micro-compact
        self.compressor.microcompact(self.messages)

        # Check if we need full compression
        if self.compressor.should_compact(self.messages):
            self._auto_compact()

        # Call LLM
        try:
            response = self.llm.chat(
                messages=self.messages,
                tools=definitions(),
                system=self.system_prompt,
                max_tokens=8000,
            )
        except LLMError as e:
            error_msg = f"LLM Error: {e}"
            self.messages.append({"role": "assistant", "content": error_msg})
            return error_msg

        # Add assistant response to history
        self.messages.append({"role": "assistant", "content": response["content"]})

        # Check if we need to execute tools
        if response["stop_reason"] == "tool_use":
            return self._execute_tools(response["content"])

        # Extract text response
        text_parts = [
            block["text"] for block in response["content"] if block.get("type") == "text"
        ]
        return "".join(text_parts)

    def _execute_tools(self, content: list[dict], depth: int = 0) -> str:
        """Execute tool calls from LLM response.

        Args:
            content: Response content blocks
            depth: Current recursion depth

        Returns:
            Assistant response after tool execution
        """
        if depth >= self._max_tool_rounds:
            return "[Reached maximum tool execution rounds. Stopping to prevent infinite loop.]"
        results = []
        used_todo = False
        manual_compact = False

        for block in content:
            if block.get("type") != "tool_use":
                continue

            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            tool_id = block.get("id", "")

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
            elif tool_name == "load_skill":
                skill_name = tool_input.get("name", "")
                output = self.skills.load(skill_name)
            else:
                # Execute regular tool
                tool_handler = handler(tool_name)
                if tool_handler:
                    try:
                        output = tool_handler(**tool_input)
                    except Exception as e:
                        # IMPORTANT: Do not auto-fallback or bypass
                        # Report error clearly and let the loop handle it
                        output = f"Error executing {tool_name}: {e}"
                else:
                    output = f"Unknown tool: {tool_name}"

            results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": str(output)[:50000],  # Truncate large outputs
            })

        # Todo nag: remind if todos exist but not being updated
        self._rounds_without_todo = 0 if used_todo else self._rounds_without_todo + 1
        if self.todos.has_open_items() and self._rounds_without_todo >= 3:
            results.insert(0, {
                "type": "text",
                "text": "<reminder>You have open todos. Consider updating them.</reminder>",
            })

        # Add results to history
        self.messages.append({"role": "user", "content": results})

        # Handle manual compact
        if manual_compact:
            self._manual_compact()

        # Continue the loop - get next response
        return self._continue_after_tools(depth=depth)

    def _continue_after_tools(self, depth: int = 0) -> str:
        """Continue conversation after tool execution.

        Args:
            depth: Current recursion depth (to prevent infinite loops)

        Returns:
            Final assistant response
        """
        if depth >= self._max_tool_rounds:
            return "[Reached maximum tool execution rounds. Stopping to prevent infinite loop.]"

        try:
            response = self.llm.chat(
                messages=self.messages,
                tools=definitions(),
                system=self.system_prompt,
                max_tokens=8000,
            )
        except LLMError as e:
            error_msg = f"LLM Error: {e}"
            self.messages.append({"role": "assistant", "content": error_msg})
            return error_msg

        self.messages.append({"role": "assistant", "content": response["content"]})

        if response["stop_reason"] == "tool_use":
            return self._execute_tools(response["content"], depth=depth + 1)

        text_parts = [
            block["text"] for block in response["content"] if block.get("type") == "text"
        ]
        return "".join(text_parts)

    def _auto_compact(self) -> None:
        """Perform automatic context compression."""
        self.messages = self.compressor.compact(self.messages)

    def _manual_compact(self) -> None:
        """Perform manual context compression (triggered by tool)."""
        self._auto_compact()

    def get_todos(self) -> str:
        """Get current todo list."""
        return self.todos.render()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages = []
