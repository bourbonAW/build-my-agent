"""Integration tests for Stage B MVP"""
import pytest
import tempfile
from pathlib import Path


@pytest.mark.integration
def test_mixed_workflow_csv_analysis():
    """Test: CSV → Analysis → Report workflow"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test CSV
        csv_file = Path(tmpdir) / "sales.csv"
        csv_file.write_text("product,revenue\nA,100\nB,200\nC,300")
        
        # Step 1: Analyze CSV
        from bourbon.tools.data import csv_analyze
        analysis = csv_analyze(str(csv_file), ["summary"])
        assert analysis["success"]
        assert analysis["row_count"] == 3
        
        # Step 2: Generate report from analysis
        from jinja2 import Template
        template = Template("""
# Sales Analysis Report

Total Revenue: ${{ total }}
Average: ${{ avg }}
""")
        
        stats = analysis["stats"]["revenue"]
        total = stats["mean"] * 3  # mean * count
        report = template.render(total=total, avg=stats["mean"])
        
        assert "Sales Analysis Report" in report
        assert "600" in str(total)  # Total revenue


@pytest.mark.integration
def test_json_query_workflow():
    """Test: JSON → Query → Result workflow"""
    import json
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test JSON
        json_file = Path(tmpdir) / "data.json"
        data = {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}
        json_file.write_text(json.dumps(data))
        
        # Query JSON
        from bourbon.tools.data import json_query
        result = json_query(str(json_file), query="users.0.name")
        
        assert result["success"]
        assert result["data"] == "Alice"


@pytest.mark.integration
def test_web_fetch_structure():
    """Test web fetch returns correct structure"""
    from bourbon.tools.web import fetch_url
    import asyncio
    
    # Test with invalid URL (no network call needed)
    result = asyncio.run(fetch_url("not-a-url"))
    
    assert result["success"] is False
    assert "error" in result
    assert "url" in result


@pytest.mark.integration
def test_document_tools_structure():
    """Test document tools handle missing files"""
    from bourbon.tools.documents import pdf_to_text, docx_to_markdown
    
    pdf_result = pdf_to_text("nonexistent.pdf")
    assert pdf_result["success"] is False
    
    docx_result = docx_to_markdown("nonexistent.docx")
    assert docx_result["success"] is False
