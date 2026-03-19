"""Tests for base tools."""

import os
import tempfile
from pathlib import Path

import pytest

from bourbon.tools.base import (
    edit_file,
    read_file,
    run_bash,
    safe_path,
    write_file,
)


class TestSafePath:
    """Test path safety."""

    def test_valid_relative_path(self):
        """Test valid relative path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            result = safe_path("src/main.py", workdir)
            assert result == workdir / "src" / "main.py"

    def test_path_escapes_workspace(self):
        """Test path escaping workspace is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            with pytest.raises(ValueError, match="escapes workspace"):
                safe_path("../outside.txt", workdir)

    def test_absolute_path(self):
        """Test absolute path is handled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            # Absolute path within workspace should work
            result = safe_path(f"{tmpdir}/file.txt", workdir)
            assert result == workdir / "file.txt"


class TestRunBash:
    """Test bash tool."""

    def test_simple_command(self):
        """Test simple echo command."""
        result = run_bash("echo hello")
        assert "hello" in result

    def test_blocked_dangerous_command(self):
        """Test dangerous commands are blocked."""
        result = run_bash("sudo ls")
        assert "blocked" in result.lower()

        result = run_bash("rm -rf /")
        assert "blocked" in result.lower()

    def test_timeout(self):
        """Test command timeout."""
        result = run_bash("sleep 10", timeout=1)
        assert "Timeout" in result


class TestReadFile:
    """Test read_file tool."""

    def test_read_existing_file(self):
        """Test reading an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")

            result = read_file(str(test_file), workdir=Path(tmpdir))
            assert "Hello, World!" in result

    def test_read_nonexistent_file(self):
        """Test reading non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = read_file("nonexistent.txt", workdir=Path(tmpdir))
            assert "Error" in result

    def test_read_with_limit(self):
        """Test reading with line limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("\n".join(f"Line {i}" for i in range(100)))

            result = read_file(str(test_file), limit=10, workdir=Path(tmpdir))
            assert "Line 0" in result
            assert "Line 9" in result
            assert "more" in result


class TestWriteFile:
    """Test write_file tool."""

    def test_write_new_file(self):
        """Test writing a new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_file("test.txt", "Hello!", workdir=Path(tmpdir))

            assert "Wrote" in result
            assert (Path(tmpdir) / "test.txt").read_text() == "Hello!"

    def test_create_directories(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = write_file("a/b/c/test.txt", "Hello!", workdir=Path(tmpdir))

            assert "Wrote" in result
            assert (Path(tmpdir) / "a" / "b" / "c" / "test.txt").exists()

    def test_overwrite_existing(self):
        """Test overwriting existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Old content")

            result = write_file("test.txt", "New content", workdir=Path(tmpdir))

            assert "Wrote" in result
            assert test_file.read_text() == "New content"


class TestEditFile:
    """Test edit_file tool."""

    def test_simple_replace(self):
        """Test simple text replacement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")

            result = edit_file("test.txt", "World", "Bourbon", workdir=Path(tmpdir))

            assert "Edited" in result
            assert test_file.read_text() == "Hello, Bourbon!"

    def test_text_not_found(self):
        """Test when old_text is not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")

            result = edit_file("test.txt", "Missing", "Replacement", workdir=Path(tmpdir))

            assert "Error" in result
            assert "not found" in result

    def test_edit_nonexistent_file(self):
        """Test editing non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = edit_file("nonexistent.txt", "old", "new", workdir=Path(tmpdir))
            assert "Error" in result

    def test_only_first_occurrence(self):
        """Test that only first occurrence is replaced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("foo bar foo")

            result = edit_file("test.txt", "foo", "baz", workdir=Path(tmpdir))

            assert test_file.read_text() == "baz bar foo"
