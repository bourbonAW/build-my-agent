"""Tests for data analysis tools"""

import json

from bourbon.tools.data import csv_analyze, json_query


def test_csv_analyze_summary(tmp_path):
    """Test CSV summary statistics"""
    # Create test CSV
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("name,value\nA,10\nB,20\nC,30")

    result = csv_analyze(str(csv_file), operations=["summary"])
    assert result["success"] is True
    assert result["row_count"] == 3
    assert "value" in result["stats"]
    assert result["stats"]["value"]["mean"] == 20.0


def test_csv_analyze_file_not_found():
    """Test handling missing file"""
    result = csv_analyze("nonexistent.csv")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_json_query_simple(tmp_path):
    """Test JSON query"""
    json_file = tmp_path / "test.json"
    data = {"users": [{"name": "Alice"}, {"name": "Bob"}]}
    json_file.write_text(json.dumps(data))

    result = json_query(str(json_file), query="users.0.name")
    assert result["success"] is True
    assert result["data"] == "Alice"


def test_json_query_no_query(tmp_path):
    """Test JSON without query returns full data"""
    json_file = tmp_path / "test.json"
    data = {"key": "value"}
    json_file.write_text(json.dumps(data))

    result = json_query(str(json_file))
    assert result["success"] is True
    assert result["data"] == data
