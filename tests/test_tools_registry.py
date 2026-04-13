"""Tests for tool registration system.

This test ensures tools are properly registered when imported.
This is a critical test - without it, tools won't be available to the agent.
"""

from pathlib import Path

from bourbon import tools
from bourbon.tools import RiskLevel, Tool, ToolContext, ToolRegistry


class TestToolRegistration:
    """Test that tools are properly registered."""

    def test_tools_are_registered(self):
        """CRITICAL: Tools must be registered.

        This test ensures the lazy import mechanism works.
        Without this, agent will have 0 tools available.
        """
        # Call definitions() - this should trigger tool registration
        defs = tools.definitions()

        # Verify tools are registered
        assert len(defs) > 0, "No tools registered! Lazy import may be broken."
        assert len(defs) >= 6, f"Expected at least 6 tools, got {len(defs)}"

        # Verify expected tools exist
        tool_names = {d["name"] for d in defs}
        expected_tools = {
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Grep",
            "AstGrep",
            "Skill",
            "SkillResource",
        }

        for expected in expected_tools:
            assert expected in tool_names, f"Expected tool '{expected}' not registered"

    def test_handler_returns_correct_function(self):
        """Test that handler() returns the correct function."""
        # Ensure tools are registered first
        tools.definitions()

        bash = tools.handler("Bash")
        assert bash is not None, "bash handler not found"
        bash_alias = tools.handler("bash")
        assert bash_alias is not None, "bash alias handler not found"

        # Unknown handler
        unknown = tools.handler("nonexistent_tool")
        assert unknown is None

    def test_alias_lookup_via_global_functions(self):
        """Legacy tool names should still resolve via aliases."""
        tools.definitions()
        assert tools.handler("bash") is not None
        assert tools.handler("read_file") is not None
        assert tools.handler("rg_search") is not None
        assert tools.get_tool_with_metadata("edit_file") is not None

    def test_tool_definitions_format(self):
        """Test that tool definitions have correct format for LLM APIs."""
        defs = tools.definitions()

        for tool_def in defs:
            # Required fields
            assert "name" in tool_def, f"Tool missing 'name': {tool_def}"
            assert "description" in tool_def, f"Tool {tool_def['name']} missing 'description'"
            assert "input_schema" in tool_def, f"Tool {tool_def['name']} missing 'input_schema'"

            # Validate schema structure
            schema = tool_def["input_schema"]
            assert schema.get("type") == "object", (
                f"Tool {tool_def['name']} schema type should be 'object'"
            )
            assert "properties" in schema, f"Tool {tool_def['name']} schema missing 'properties'"

    def test_all_tools_have_handlers(self):
        """Test that every registered tool has a working handler."""
        defs = tools.definitions()

        for tool_def in defs:
            name = tool_def["name"]
            handler = tools.handler(name)
            assert handler is not None, f"Tool '{name}' has no handler!"
            assert callable(handler), f"Handler for '{name}' is not callable!"

    def test_registry_is_singleton(self):
        """Test that get_registry returns the same instance."""
        reg1 = tools.get_registry()
        reg2 = tools.get_registry()
        assert reg1 is reg2, "Registry should be a singleton"

    def test_tool_count_consistency(self):
        """Default definitions should include only always-loaded tools."""
        registry = tools.get_registry()

        # Trigger registration
        defs = tools.definitions()

        always_loaded = [tool for tool in registry.list_tools() if tool.always_load]
        assert len(defs) == len(always_loaded), "Default definitions should exclude deferred tools"

    def test_handler_is_callable(self):
        """Test that returned handlers can be called."""
        bash = tools.handler("Bash")
        assert bash is not None

        import inspect

        sig = inspect.signature(bash)
        params = list(sig.parameters.keys())
        assert "command" in params, "bash handler should accept 'command' parameter"

    def test_required_capabilities_metadata(self):
        """Tool metadata should expose declared required capabilities."""
        assert tools.get_tool_with_metadata("Bash").required_capabilities == ["exec"]
        assert tools.get_tool_with_metadata("Read").required_capabilities == ["file_read"]
        assert tools.get_tool_with_metadata("Write").required_capabilities == ["file_write"]
        assert tools.get_tool_with_metadata("Edit").required_capabilities == ["file_write"]
        assert tools.get_tool_with_metadata("Grep").required_capabilities == ["file_read"]
        assert tools.get_tool_with_metadata("AstGrep").required_capabilities == ["file_read"]
        assert tools.get_tool_with_metadata("Skill").required_capabilities == ["skill"]


class TestToolContext:
    def test_tool_context_fields(self):
        ctx = ToolContext(workdir=Path("/tmp"))
        assert ctx.workdir == Path("/tmp")
        assert ctx.agent is None
        assert ctx.skill_manager is None
        assert ctx.on_tools_discovered is None

    def test_tool_context_with_callbacks(self):
        discovered = set()
        ctx = ToolContext(
            workdir=Path("/tmp"),
            on_tools_discovered=discovered.update,
        )
        ctx.on_tools_discovered({"WebFetch"})
        assert "WebFetch" in discovered


class TestToolConstraints:
    def test_should_defer_true_with_always_load_true_raises(self):
        """should_defer=True implies always_load=False; combining them is a misconfiguration."""

        def dummy(*, ctx: ToolContext) -> str:
            return "ok"

        import pytest

        with pytest.raises(ValueError, match="should_defer"):
            Tool(
                name="BadTool",
                description="bad",
                input_schema={"type": "object", "properties": {}},
                handler=dummy,
                should_defer=True,
                always_load=True,
            )

    def test_should_defer_false_with_always_load_true_is_valid(self):
        """Normal tools with always_load=True are fine."""

        def dummy(*, ctx: ToolContext) -> str:
            return "ok"

        t = Tool(
            name="NormalTool",
            description="normal",
            input_schema={"type": "object", "properties": {}},
            handler=dummy,
            should_defer=False,
            always_load=True,
        )
        assert t.always_load is True

    def test_should_defer_true_with_always_load_false_is_valid(self):
        """Deferred tools with always_load=False are the intended pattern."""

        def dummy(*, ctx: ToolContext) -> str:
            return "ok"

        t = Tool(
            name="DeferredTool",
            description="deferred",
            input_schema={"type": "object", "properties": {}},
            handler=dummy,
            should_defer=True,
            always_load=False,
        )
        assert t.should_defer is True
        assert t.always_load is False


class TestToolNewFields:
    def test_tool_has_new_fields_with_defaults(self):
        def dummy_handler(*, ctx: ToolContext) -> str:
            return "ok"

        t = Tool(
            name="TestTool",
            description="test",
            input_schema={"type": "object", "properties": {}},
            handler=dummy_handler,
        )
        assert t.aliases == []
        assert t.always_load is True
        assert t.should_defer is False
        assert t.is_concurrency_safe is False
        assert t.is_read_only is False
        assert t.is_destructive is False
        assert t.search_hint is None

    def test_tool_is_destructive_drives_risk_patterns(self):
        """is_destructive=True + HIGH risk -> risk_patterns auto-populated."""

        def dummy(*, ctx: ToolContext) -> str:
            return "ok"

        t = Tool(
            name="DangerTool",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=dummy,
            risk_level=RiskLevel.HIGH,
            is_destructive=True,
        )
        assert len(t.risk_patterns) > 0
        assert "rm " in t.risk_patterns

    def test_tool_is_high_risk_operation_uses_is_destructive(self):
        def dummy(*, ctx: ToolContext) -> str:
            return "ok"

        t = Tool(
            name="BashLike",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=dummy,
            risk_level=RiskLevel.HIGH,
            is_destructive=True,
        )
        assert t.is_high_risk_operation({"command": "rm -rf /tmp/foo"}) is True
        assert t.is_high_risk_operation({"command": "echo hello"}) is False


class TestToolRegistryAliases:
    def setup_method(self):
        """Each test gets an isolated registry to avoid global pollution."""
        self.registry = ToolRegistry()

    def _make_tool(self, name: str, aliases: list[str] | None = None) -> Tool:
        def handler(*, ctx: ToolContext) -> str:
            return f"called {name}"

        return Tool(
            name=name,
            description="test",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
            aliases=aliases or [],
        )

    def test_alias_lookup_via_resolve(self):
        tool = self._make_tool("NewName", aliases=["old_name"])
        self.registry.register(tool)
        assert self.registry._resolve("NewName") is tool
        assert self.registry._resolve("old_name") is tool
        assert self.registry._resolve("nonexistent") is None

    def test_get_is_alias_aware(self):
        tool = self._make_tool("Read", aliases=["read_file"])
        self.registry.register(tool)
        assert self.registry.get("read_file") is tool

    def test_get_handler_is_alias_aware(self):
        tool = self._make_tool("Bash", aliases=["bash"])
        self.registry.register(tool)
        h = self.registry.get_handler("bash")
        assert h is not None

    def test_call_injects_ctx(self):
        called_with = {}

        def handler(command: str, *, ctx: ToolContext) -> str:
            called_with["ctx"] = ctx
            called_with["command"] = command
            return "done"

        tool = Tool(
            name="Bash",
            description="d",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
            aliases=["bash"],
        )
        self.registry.register(tool)
        ctx = ToolContext(workdir=Path("/tmp"))
        result = self.registry.call("bash", {"command": "echo hi"}, ctx)
        assert result == "done"
        assert called_with["ctx"] is ctx
        assert called_with["command"] == "echo hi"

    def test_call_unknown_tool_returns_error(self):
        ctx = ToolContext(workdir=Path("/tmp"))
        result = self.registry.call("nonexistent", {}, ctx)
        assert "Unknown tool" in result

    def test_get_tool_definitions_filters_always_load(self):
        core = self._make_tool("CoreTool")
        core.always_load = True
        deferred = self._make_tool("DeferredTool")
        deferred.always_load = False
        deferred.should_defer = True
        self.registry.register(core)
        self.registry.register(deferred)

        defs = self.registry.get_tool_definitions()
        names = {d["name"] for d in defs}
        assert "CoreTool" in names
        assert "DeferredTool" not in names

    def test_get_tool_definitions_includes_discovered(self):
        core = self._make_tool("CoreTool")
        deferred = self._make_tool("DeferredTool")
        deferred.always_load = False
        deferred.should_defer = True
        self.registry.register(core)
        self.registry.register(deferred)

        defs = self.registry.get_tool_definitions(discovered={"DeferredTool"})
        names = {d["name"] for d in defs}
        assert "DeferredTool" in names


class TestBaseToolsRenamed:
    def test_new_names_in_definitions(self):
        defs = tools.definitions()
        names = {d["name"] for d in defs}
        assert "Bash" in names
        assert "Read" in names
        assert "Write" in names
        assert "Edit" in names
        assert "TodoWrite" not in names  # V1 disabled; Task V2 is the active system

    def test_read_handler_uses_ctx_workdir(self, tmp_path):
        ctx = ToolContext(workdir=tmp_path)
        (tmp_path / "test.txt").write_text("hello")
        result = tools.get_registry().call("Read", {"path": "test.txt"}, ctx)
        assert "hello" in result

    def test_bash_is_destructive(self):
        tool = tools.get_tool_with_metadata("Bash")
        assert tool is not None
        assert tool.is_destructive is True
        assert tool.risk_level.value == "high"

    def test_read_is_read_only(self):
        tool = tools.get_tool_with_metadata("Read")
        assert tool is not None
        assert tool.is_read_only is True
        assert tool.is_concurrency_safe is True

    def test_write_edit_not_read_only(self):
        write_tool = tools.get_tool_with_metadata("Write")
        edit_tool = tools.get_tool_with_metadata("Edit")
        assert write_tool is not None
        assert edit_tool is not None
        assert write_tool.is_read_only is False
        assert edit_tool.is_read_only is False


class TestSearchToolsRenamed:
    def test_grep_glob_registered(self):
        defs = tools.definitions()
        names = {d["name"] for d in defs}
        assert "Grep" in names
        assert "AstGrep" in names
        assert "Glob" in names

    def test_glob_finds_files(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        ctx = ToolContext(workdir=tmp_path)
        result = tools.get_registry().call("Glob", {"pattern": "*.py"}, ctx)
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_glob_truncates_at_100(self, tmp_path):
        for i in range(110):
            (tmp_path / f"f{i}.py").write_text("")
        ctx = ToolContext(workdir=tmp_path)
        result = tools.get_registry().call("Glob", {"pattern": "*.py"}, ctx)
        assert "truncated" in result.lower() or "100" in result

    def test_grep_is_read_only_and_concurrency_safe(self):
        tool = tools.get_tool_with_metadata("Grep")
        assert tool is not None
        assert tool.is_read_only is True
        assert tool.is_concurrency_safe is True


class TestSkillToolRenamed:
    def test_skill_skillresource_registered(self):
        defs = tools.definitions()
        names = {d["name"] for d in defs}
        assert "Skill" in names
        assert "SkillResource" in names

    def test_skill_is_not_read_only(self):
        tool = tools.get_tool_with_metadata("Skill")
        assert tool is not None
        assert tool.is_read_only is False

    def test_skill_uses_ctx_skill_manager_when_provided(self, tmp_path):
        from unittest.mock import MagicMock

        mock_manager = MagicMock()
        mock_manager.is_activated.return_value = False
        mock_manager.activate.return_value = "mocked skill content"
        ctx = ToolContext(workdir=tmp_path, skill_manager=mock_manager)
        result = tools.get_registry().call("Skill", {"name": "nonexistent-skill"}, ctx)
        mock_manager.activate.assert_called_once_with("nonexistent-skill", args="")
        assert "mocked skill content" in result
