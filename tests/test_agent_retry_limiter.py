"""Tests for _execute_regular_tool consecutive-failure limiter."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from bourbon.agent import Agent
from bourbon.config import Config


def _make_stub() -> Agent:
    """Minimal Agent stub via __new__ for retry-limiter tests."""
    agent = object.__new__(Agent)
    agent.workdir = Path("/tmp")
    agent._max_tool_consecutive_failures = 3
    agent.active_permission_request = None

    # Access controller: always allow
    ac = MagicMock()
    ac.evaluate.return_value = MagicMock(action=None)
    # Make action != DENY and != NEED_APPROVAL
    from bourbon.access_control.policy import PolicyAction
    ac.evaluate.return_value.action = PolicyAction.ALLOW
    agent.access_controller = ac

    # Sandbox: disabled
    agent.sandbox = MagicMock()
    agent.sandbox.enabled = False

    # Audit
    agent.audit = MagicMock()

    # Required by _make_tool_context()
    agent.skills = MagicMock()
    agent._discovered_tools = set()

    return agent


class TestRetryLimiterAttributeSafety:
    """Bug 3: __new__ stubs must not raise AttributeError."""

    def test_no_attribute_error_when_failures_dict_missing(self):
        """_execute_regular_tool must not raise AttributeError on uninitialized stubs."""
        agent = _make_stub()
        # Deliberately do NOT set _tool_consecutive_failures — this is the bug condition

        with patch("bourbon.agent.get_tool_with_metadata", return_value=None), \
             patch("bourbon.agent.get_registry") as mock_reg:
            mock_reg.return_value.call.return_value = "ok"
            agent._record_policy_decision = MagicMock()
            # Must not raise AttributeError
            result = agent._execute_regular_tool("Read", {"path": "/tmp/x"}, skip_policy_check=True)
        assert "AttributeError" not in result


class TestRetryLimiterRecovery:
    """Bug 1: tools must be recoverable after hitting the failure limit."""

    def test_tool_unblocked_after_limit_response(self):
        """After the block message is returned the counter resets so the tool can retry."""
        agent = _make_stub()
        agent._tool_consecutive_failures = {"Read": 3}

        with patch("bourbon.agent.get_tool_with_metadata", return_value=None), \
             patch("bourbon.agent.get_registry") as mock_reg:
            mock_reg.return_value.call.return_value = "file content"
            agent._record_policy_decision = MagicMock()

            # First call: hits the limit, returns block message
            result1 = agent._execute_regular_tool("Read", {}, skip_policy_check=True)
            assert "failed" in result1.lower() or "consecutive" in result1.lower()

            # Second call: counter must have been reset; tool should run again
            result2 = agent._execute_regular_tool("Read", {}, skip_policy_check=True)
            assert result2 == "file content"

    def test_counter_resets_on_exception_path_success(self):
        """Counter resets to zero after a successful tool call."""
        agent = _make_stub()
        agent._tool_consecutive_failures = {"Bash": 2}

        with patch("bourbon.agent.get_tool_with_metadata", return_value=None), \
             patch("bourbon.agent.get_registry") as mock_reg:
            mock_reg.return_value.call.return_value = "done"
            agent._record_policy_decision = MagicMock()

            agent._execute_regular_tool("Bash", {}, skip_policy_check=True)
            assert agent._tool_consecutive_failures.get("Bash", 0) == 0


class TestRetryLimiterFailureDetection:
    """Bug 2: failure detection must not be based on output text."""

    def test_output_starting_with_Error_does_not_increment_counter(self):
        """Successful tool call whose output starts with 'Error' must not count as failure."""
        agent = _make_stub()
        agent._tool_consecutive_failures = {}

        with patch("bourbon.agent.get_tool_with_metadata", return_value=None), \
             patch("bourbon.agent.get_registry") as mock_reg:
            # Tool runs fine, returns a log line that starts with "Error"
            mock_reg.return_value.call.return_value = "Error: no matches found (this is normal)"
            agent._record_policy_decision = MagicMock()

            agent._execute_regular_tool("Grep", {"pattern": "foo"}, skip_policy_check=True)

            # Counter must NOT have been incremented
            assert agent._tool_consecutive_failures.get("Grep", 0) == 0

    def test_exception_increments_counter(self):
        """An exception during tool execution increments the failure counter."""
        agent = _make_stub()
        agent._tool_consecutive_failures = {}

        with patch("bourbon.agent.get_tool_with_metadata", return_value=None), \
             patch("bourbon.agent.get_registry") as mock_reg:
            mock_reg.return_value.call.side_effect = RuntimeError("disk full")
            agent._record_policy_decision = MagicMock()

            result = agent._execute_regular_tool("Write", {}, skip_policy_check=True)

            assert agent._tool_consecutive_failures.get("Write", 0) == 1
            assert "Error" in result

    def test_three_exceptions_trigger_block(self):
        """After 3 consecutive exceptions the block message is returned."""
        agent = _make_stub()
        agent._tool_consecutive_failures = {"Write": 3}

        with patch("bourbon.agent.get_tool_with_metadata", return_value=None), \
             patch("bourbon.agent.get_registry"):
            agent._record_policy_decision = MagicMock()

            result = agent._execute_regular_tool("Write", {}, skip_policy_check=True)

        assert "consecutive" in result.lower() or "failed" in result.lower()
