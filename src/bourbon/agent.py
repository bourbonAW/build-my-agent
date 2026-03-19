"""Core agent loop for Bourbon."""

from pathlib import Path
from typing import Callable

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
        self._max_tool_rounds = 5

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
            "Available skills (load with load_skill):",
            self.skills.descriptions(),
        ]
        return "\n".join(lines)

    def step(self, user_input: str) -> str:
        """Process one user input and return assistant response."""
        # Add user message
        self.messages.append({"role": "user", "content": user_input})

        # Pre-process: micro-compact
        self.compressor.microcompact(self.messages)

        # Check if we need full compression
        if self.compressor.should_compact(self.messages):
            self._auto_compact()

        # Run the conversation loop
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

            # Check if response contains tool calls
            has_tool_calls = response["stop_reason"] == "tool_use"

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
            tool_results = self._execute_tools(response["content"])
            
            # Add tool results to history
            self.messages.append({"role": "user", "content": tool_results})
            
            tool_round += 1

        return "[Reached maximum tool execution rounds. Providing final response based on what was learned.]"

    def _execute_tools(self, content: list[dict]) -> list[dict]:
        """Execute tool calls from LLM response.

        Args:
            content: Response content blocks

        Returns:
            List of tool results
        """
        results = []
        used_todo = False
        manual_compact = False

        for block in content:
            if block.get("type") != "tool_use":
                continue

            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            tool_id = block.get("id", "")

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
