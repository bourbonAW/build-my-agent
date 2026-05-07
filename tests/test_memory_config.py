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
    assert cfg.semantic.enabled is True
    assert cfg.semantic.provider == "fastembed"
    assert cfg.semantic.model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert cfg.semantic.top_k == 16
    assert cfg.semantic.min_similarity == 0.25


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
    assert cfg.memory.semantic.enabled is True


def test_config_from_dict_memory_semantic_fields() -> None:
    cfg = Config.from_dict(
        {
            "memory": {
                "semantic": {
                    "enabled": False,
                    "provider": "fastembed",
                    "model": "custom/model",
                    "top_k": 4,
                    "min_similarity": 0.4,
                }
            }
        }
    )

    assert cfg.memory.semantic.enabled is False
    assert cfg.memory.semantic.provider == "fastembed"
    assert cfg.memory.semantic.model == "custom/model"
    assert cfg.memory.semantic.top_k == 4
    assert cfg.memory.semantic.min_similarity == 0.4


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
        "semantic": {
            "enabled": True,
            "provider": "fastembed",
            "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "top_k": 16,
            "min_similarity": 0.25,
        },
    }
