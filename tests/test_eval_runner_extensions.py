"""Unit tests for runner.py extensions (subcategory filter, audit_event_exists)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.runner import EvalRunner


def _write_case(path: Path, case_id: str, category: str, subcategory: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": case_id,
        "name": f"Test {case_id}",
        "category": category,
        "subcategory": subcategory,
        "prompt": "test",
        "assertions": [],
    }))


class TestLoadCasesSubcategory:
    def test_load_all_when_no_filter(self, tmp_path: Path) -> None:
        _write_case(tmp_path / "sandbox/exfil/a.json", "a", "sandbox", "exfiltration")
        _write_case(tmp_path / "security/priv/b.json", "b", "security", "privilege-escalation")

        runner = EvalRunner.__new__(EvalRunner)
        runner.fast_mode = True
        runner.num_runs = 1
        runner.timeout = 60
        runner.bourbon_config = None
        runner.case_results = []

        cases = runner.load_cases(cases_dir=tmp_path)

        assert len(cases) == 2

    def test_load_by_category(self, tmp_path: Path) -> None:
        _write_case(tmp_path / "sandbox/exfil/a.json", "a", "sandbox", "exfiltration")
        _write_case(tmp_path / "security/priv/b.json", "b", "security", "privilege-escalation")

        runner = EvalRunner.__new__(EvalRunner)
        runner.fast_mode = True
        runner.num_runs = 1
        runner.timeout = 60
        runner.bourbon_config = None
        runner.case_results = []

        cases = runner.load_cases(category="sandbox", cases_dir=tmp_path)

        assert len(cases) == 1
        assert cases[0]["id"] == "a"

    def test_load_by_category_and_subcategory(self, tmp_path: Path) -> None:
        _write_case(tmp_path / "sandbox/exfil/a.json", "a", "sandbox", "exfiltration")
        _write_case(tmp_path / "sandbox/path/b.json", "b", "sandbox", "path-traversal")

        runner = EvalRunner.__new__(EvalRunner)
        runner.fast_mode = True
        runner.num_runs = 1
        runner.timeout = 60
        runner.bourbon_config = None
        runner.case_results = []

        cases = runner.load_cases(category="sandbox/exfiltration", cases_dir=tmp_path)

        assert len(cases) == 1
        assert cases[0]["id"] == "a"

    def test_subcategory_does_not_match_other_subcategory(self, tmp_path: Path) -> None:
        _write_case(tmp_path / "sandbox/exfil/a.json", "a", "sandbox", "exfiltration")
        _write_case(tmp_path / "sandbox/path/b.json", "b", "sandbox", "path-traversal")

        runner = EvalRunner.__new__(EvalRunner)
        runner.fast_mode = True
        runner.num_runs = 1
        runner.timeout = 60
        runner.bourbon_config = None
        runner.case_results = []

        cases = runner.load_cases(category="sandbox/path-traversal", cases_dir=tmp_path)

        assert len(cases) == 1
        assert cases[0]["id"] == "b"
