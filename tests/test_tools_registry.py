"""Tests for tool registration system.

This test ensures tools are properly registered when imported.
This is a critical test - without it, tools won't be available to the agent.
"""

import pytest

from bourbon import tools


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
        expected_tools = {"bash", "read_file", "write_file", "edit_file", "rg_search", "ast_grep_search"}
        
        for expected in expected_tools:
            assert expected in tool_names, f"Expected tool '{expected}' not registered"

    def test_handler_returns_correct_function(self):
        """Test that handler() returns the correct function."""
        # Ensure tools are registered first
        tools.definitions()
        
        # bash handler
        bash = tools.handler("bash")
        assert bash is not None, "bash handler not found"
        
        # Unknown handler
        unknown = tools.handler("nonexistent_tool")
        assert unknown is None

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
            assert schema.get("type") == "object", f"Tool {tool_def['name']} schema type should be 'object'"
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
        """Test that definitions() and list_tools() return consistent counts."""
        registry = tools.get_registry()
        
        # Trigger registration
        defs = tools.definitions()
        
        # Both should return same count
        assert len(defs) == len(registry.list_tools()), "Inconsistent tool counts"

    def test_handler_is_callable(self):
        """Test that returned handlers can be called."""
        # Get bash handler
        bash = tools.handler("bash")
        assert bash is not None
        
        # Should be callable with command argument
        # Note: We don't actually call it to avoid side effects in tests
        import inspect
        sig = inspect.signature(bash)
        params = list(sig.parameters.keys())
        assert "command" in params, "bash handler should accept 'command' parameter"
