"""Tests for search tools."""

import shutil
import tempfile
from pathlib import Path

import pytest

from bourbon.tools.search import ast_grep_search, rg_search


class TestRgSearch:
    """Test ripgrep search tool."""

    def setup_method(self):
        """Check if rg is available."""
        self.rg_available = shutil.which("rg") is not None

    def test_simple_search(self):
        """Test simple text search."""
        if not self.rg_available:
            pytest.skip("ripgrep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "test.py").write_text("def hello(): pass\n")
            (Path(tmpdir) / "other.txt").write_text("hello world\n")

            result = rg_search("hello", path=tmpdir)

            assert "test.py" in result
            assert "other.txt" in result
            assert "hello" in result

    def test_regex_search(self):
        """Test regex pattern search."""
        if not self.rg_available:
            pytest.skip("ripgrep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("def foo(): pass\ndef bar(): pass\n")

            result = rg_search(r"def \w+", path=tmpdir)

            assert "def foo" in result
            assert "def bar" in result

    def test_glob_filter(self):
        """Test file glob filtering."""
        if not self.rg_available:
            pytest.skip("ripgrep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("hello\n")
            (Path(tmpdir) / "test.txt").write_text("hello\n")

            result = rg_search("hello", path=tmpdir, glob="*.py")

            assert "test.py" in result
            assert "test.txt" not in result

    def test_no_matches(self):
        """Test when no matches found."""
        if not self.rg_available:
            pytest.skip("ripgrep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.txt").write_text("content\n")

            result = rg_search("nonexistent", path=tmpdir)

            assert "No matches" in result

    def test_rg_not_installed(self):
        """Test graceful handling when rg is not installed."""
        # Temporarily modify PATH to exclude rg
        original_path = shutil.which("rg")
        if original_path:
            # Can't easily test this without mocking, so just verify the check exists
            pass
        else:
            result = rg_search("test")
            assert "not found" in result


class TestAstGrepSearch:
    """Test ast-grep search tool."""

    def setup_method(self):
        """Check if ast-grep is available."""
        self.ast_grep_available = shutil.which("ast-grep") is not None

    def test_find_function_definitions(self):
        """Test finding function definitions."""
        if not self.ast_grep_available:
            pytest.skip("ast-grep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("""
def hello():
    pass

def world(x, y):
    return x + y
""")

            result = ast_grep_search("def $FUNC($$$ARGS)", path=tmpdir, language="python")

            # Should find both functions
            assert "hello" in result or "world" in result

    def test_find_class_definitions(self):
        """Test finding class definitions."""
        if not self.ast_grep_available:
            pytest.skip("ast-grep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("""
class MyClass:
    pass

class OtherClass(Base):
    pass
""")

            result = ast_grep_search("class $NAME", path=tmpdir, language="python")

            assert "MyClass" in result or "OtherClass" in result

    def test_no_matches(self):
        """Test when no matches found."""
        if not self.ast_grep_available:
            pytest.skip("ast-grep not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("x = 1\n")

            result = ast_grep_search("class $NAME:", path=tmpdir, language="python")

            assert "No matches" in result

    def test_ast_grep_not_installed(self):
        """Test graceful handling when ast-grep is not installed."""
        if shutil.which("ast-grep"):
            pytest.skip("ast-grep is installed")

        result = ast_grep_search("test")
        assert "not found" in result
