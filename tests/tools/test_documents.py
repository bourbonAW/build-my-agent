"""Tests for document processing tools"""
import pytest
from pathlib import Path
from bourbon.tools.documents import pdf_to_text, docx_to_markdown


def test_pdf_to_text_file_not_found():
    """Test handling missing PDF file"""
    result = pdf_to_text("nonexistent.pdf")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_docx_to_markdown_file_not_found():
    """Test handling missing Word file"""
    result = docx_to_markdown("nonexistent.docx")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


# Note: Full tests would require actual PDF/docx files
# These are basic error handling tests
