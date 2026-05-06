"""Tests for MemoryConfig in bourbon.config."""

from __future__ import annotations

from bourbon.config import Config, MemoryConfig


def test_memory_config_defaults():
    cfg = MemoryConfig()
    assert cfg.enabled is True
    assert cfg.storage_dir == "~/.bourbon/projects"
    assert cfg.recall_limit == 8
    assert cfg.memory_md_token_limit == 1200
    assert cfg.user_md_token_limit == 600


def test_config_from_dict_memory_minimal_fields() -> None:
    cfg = Config.from_dict(
        {
            "memory": {
                "enabled": False,
                "storage_dir": "/tmp/memory",
                "recall_limit": 3,
                "memory_md_token_limit": 500,
                "user_md_token_limit": 250,
            }
        }
    )

    assert cfg.memory.enabled is False
    assert cfg.memory.storage_dir == "/tmp/memory"
    assert cfg.memory.recall_limit == 3
    assert cfg.memory.memory_md_token_limit == 500
    assert cfg.memory.user_md_token_limit == 250


def test_config_from_dict_no_memory():
    cfg = Config.from_dict({})
    assert cfg.memory.enabled is True


def test_config_to_dict_memory_minimal_fields() -> None:
    cfg = Config()
    data = cfg.to_dict()

    assert data["memory"] == {
        "enabled": True,
        "storage_dir": "~/.bourbon/projects",
        "recall_limit": 8,
        "memory_md_token_limit": 1200,
        "user_md_token_limit": 600,
    }
