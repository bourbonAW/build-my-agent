from pathlib import Path
from unittest.mock import MagicMock, patch

from bourbon.agent import Agent
from bourbon.config import Config
from bourbon.subagent.tools import AGENT_TYPE_CONFIGS, ToolFilter


class FinalTextLLM:
    def chat(self, **kwargs):
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "done"}],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
            },
        }


def _make_agent(tmp_path: Path) -> Agent:
    with (
        patch("bourbon.agent.create_client", return_value=MagicMock()),
        patch("bourbon.agent.Path.home", return_value=tmp_path),
    ):
        return Agent(config=Config(), workdir=tmp_path)


def test_non_streaming_subagent_loop_emits_round_debug_events(tmp_path, monkeypatch):
    events = []

    def fake_debug_log(event, **fields):
        events.append((event, fields))

    monkeypatch.setattr("bourbon.agent.debug_log", fake_debug_log)
    agent = _make_agent(tmp_path)
    agent.llm = FinalTextLLM()
    agent._subagent_agent_def = AGENT_TYPE_CONFIGS["explore"]
    agent._subagent_tool_filter = ToolFilter()

    result = agent._run_conversation_loop()

    assert result == "done"
    event_names = [event for event, _fields in events]
    assert "agent.loop.llm_call.start" in event_names
    assert "agent.loop.llm_call.end" in event_names
    assert "agent.loop.final_response" in event_names
    start_event = events[event_names.index("agent.loop.llm_call.start")]
    assert start_event[1]["is_subagent"] is True
    assert start_event[1]["subagent_type"] == "explore"


def test_subagent_tool_denial_emits_debug_event(tmp_path, monkeypatch):
    events = []

    def fake_debug_log(event, **fields):
        events.append((event, fields))

    monkeypatch.setattr("bourbon.agent.debug_log", fake_debug_log)
    agent = _make_agent(tmp_path)
    agent._subagent_agent_def = AGENT_TYPE_CONFIGS["explore"]
    agent._subagent_tool_filter = ToolFilter()

    denial = agent._subagent_tool_denial("Bash")

    assert denial == "Denied: Tool 'Bash' is not available to explore subagents."
    assert events == [
        (
            "subagent.tool.denied",
            {
                "tool_name": "Bash",
                "agent_type": "explore",
            },
        )
    ]
