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


def test_memory_cue_config_defaults() -> None:
    cfg = Config()

    assert cfg.memory.cue_enabled is False
    assert cfg.memory.cue_record_generation is True
    assert cfg.memory.cue_query_interpretation is False
    assert cfg.memory.cue_query_cache_size == 512
    assert cfg.memory.cue_generation_timeout_ms == 1500
    assert cfg.memory.cue_record_generation_mode == "sync"
    assert cfg.memory.cue_persist_failed_metadata is True


def test_config_from_dict_memory_cues() -> None:
    cfg = Config.from_dict(
        {
            "memory": {
                "cue_enabled": True,
                "cue_record_generation": False,
                "cue_query_interpretation": True,
                "cue_query_cache_size": 17,
                "cue_generation_timeout_ms": 750,
                "cue_record_generation_mode": "deferred",
                "cue_persist_failed_metadata": False,
            }
        }
    )

    assert cfg.memory.cue_enabled is True
    assert cfg.memory.cue_record_generation is False
    assert cfg.memory.cue_query_interpretation is True
    assert cfg.memory.cue_query_cache_size == 17
    assert cfg.memory.cue_generation_timeout_ms == 750
    assert cfg.memory.cue_record_generation_mode == "deferred"
    assert cfg.memory.cue_persist_failed_metadata is False


def test_config_to_dict_memory_cues() -> None:
    cfg = Config()
    cfg.memory.cue_enabled = True
    data = cfg.to_dict()

    assert data["memory"]["cue_enabled"] is True
    assert data["memory"]["cue_record_generation"] is True
    assert data["memory"]["cue_query_interpretation"] is False
    assert data["memory"]["cue_query_cache_size"] == 512
    assert data["memory"]["cue_generation_timeout_ms"] == 1500
