"""Tests for bourbon.memory.store — sanitize_project_key."""

from __future__ import annotations

from pathlib import Path

from bourbon.memory.store import sanitize_project_key


def test_sanitize_simple_path():
    key = sanitize_project_key(Path("/home/user/projects/bourbon"))
    # Should be slug + 8-char hash suffix
    assert key.startswith("home-user-projects-bourbon-")
    assert len(key.split("-")[-1]) == 8  # sha256 hex prefix


def test_sanitize_truncates_long_slug():
    long_path = Path("/" + "a" * 200)
    key = sanitize_project_key(long_path)
    # slug (before hash) should be <= 64 chars, total = slug + "-" + 8
    slug_part = key.rsplit("-", 1)[0]
    assert len(slug_part) <= 64


def test_sanitize_removes_non_ascii():
    key = sanitize_project_key(Path("/home/用户/project"))
    assert "用" not in key
    assert "户" not in key


def test_sanitize_same_path_same_key():
    p = Path("/home/user/myrepo")
    assert sanitize_project_key(p) == sanitize_project_key(p)


def test_sanitize_different_paths_different_keys():
    k1 = sanitize_project_key(Path("/home/user/repo1"))
    k2 = sanitize_project_key(Path("/home/user/repo2"))
    assert k1 != k2
