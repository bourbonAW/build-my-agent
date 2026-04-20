"""Tests for MemoryConfig in bourbon.config."""

from __future__ import annotations

from bourbon.config import Config, MemoryConfig


def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.enabled is True
    assert cfg.storage_dir == "~/.bourbon/projects"
    assert cfg.auto_flush_on_compact is True
    assert cfg.auto_extract is False
    assert cfg.recall_limit == 8
    assert cfg.recall_transcript_session_limit == 10
    assert cfg.memory_md_token_limit == 1200
    assert cfg.user_md_token_limit == 600
    assert cfg.core_block_token_limit == 1200


def test_config_from_dict_memory():
    cfg = Config.from_dict({"memory": {"enabled": False, "recall_limit": 5}})
    assert cfg.memory.enabled is False
    assert cfg.memory.recall_limit == 5


def test_config_from_dict_no_memory():
    cfg = Config.from_dict({})
    assert cfg.memory.enabled is True


def test_config_to_dict_memory():
    cfg = Config()
    d = cfg.to_dict()
    assert "memory" in d
    assert d["memory"]["enabled"] is True
    assert d["memory"]["recall_limit"] == 8
