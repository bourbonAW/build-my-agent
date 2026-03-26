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


class TestAuditEventExistsAssertion:
    def _make_runner(self) -> EvalRunner:
        runner = EvalRunner.__new__(EvalRunner)
        runner.fast_mode = True
        runner.num_runs = 1
        runner.timeout = 60
        runner.bourbon_config = None
        runner.case_results = []
        return runner

    def test_audit_event_found_passes(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        audit_file.write_text(
            json.dumps({"event_type": "sandbox_violation", "tool_name": "bash"}) + "\n"
        )
        case = {
            "id": "test-case",
            "assertions": [{
                "id": "check-violation",
                "description": "violation recorded",
                "check": "audit_event_exists:event_type=sandbox_violation",
            }],
        }
        runner = self._make_runner()
        results = runner._execute_assertions(case, output="", workdir=tmp_path)
        assert results[0]["passed"] is True

    def test_audit_event_not_found_fails(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        audit_file.write_text(
            json.dumps({"event_type": "tool_call", "tool_name": "bash"}) + "\n"
        )
        case = {
            "id": "test-case",
            "assertions": [{
                "id": "check-violation",
                "description": "violation recorded",
                "check": "audit_event_exists:event_type=sandbox_violation",
            }],
        }
        runner = self._make_runner()
        results = runner._execute_assertions(case, output="", workdir=tmp_path)
        assert results[0]["passed"] is False

    def test_audit_multi_criteria_match(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        audit_file.write_text(
            json.dumps({"event_type": "policy_decision", "decision": "deny", "tool_name": "bash"}) + "\n"
        )
        case = {
            "id": "test-case",
            "assertions": [{
                "id": "check-deny",
                "description": "policy deny recorded",
                "check": "audit_event_exists:event_type=policy_decision,decision=deny",
            }],
        }
        runner = self._make_runner()
        results = runner._execute_assertions(case, output="", workdir=tmp_path)
        assert results[0]["passed"] is True

    def test_audit_multi_criteria_partial_fails(self, tmp_path: Path) -> None:
        """Matching event_type but wrong decision should fail."""
        audit_file = tmp_path / "audit.jsonl"
        audit_file.write_text(
            json.dumps({"event_type": "policy_decision", "decision": "allow", "tool_name": "bash"}) + "\n"
        )
        case = {
            "id": "test-case",
            "assertions": [{
                "id": "check-deny",
                "description": "policy deny recorded",
                "check": "audit_event_exists:event_type=policy_decision,decision=deny",
            }],
        }
        runner = self._make_runner()
        results = runner._execute_assertions(case, output="", workdir=tmp_path)
        assert results[0]["passed"] is False

    def test_no_audit_file_gives_false(self, tmp_path: Path) -> None:
        """No audit.jsonl means no events — assertion should fail (not error)."""
        case = {
            "id": "test-case",
            "assertions": [{
                "id": "check-violation",
                "description": "violation recorded",
                "check": "audit_event_exists:event_type=sandbox_violation",
            }],
        }
        runner = self._make_runner()
        results = runner._execute_assertions(case, output="", workdir=tmp_path)
        assert results[0]["passed"] is False

    def test_malformed_jsonl_line_is_skipped(self, tmp_path: Path) -> None:
        audit_file = tmp_path / "audit.jsonl"
        audit_file.write_text(
            "not-json\n" +
            json.dumps({"event_type": "sandbox_violation", "tool_name": "bash"}) + "\n"
        )
        case = {
            "id": "test-case",
            "assertions": [{
                "id": "check-violation",
                "description": "violation recorded",
                "check": "audit_event_exists:event_type=sandbox_violation",
            }],
        }
        runner = self._make_runner()
        results = runner._execute_assertions(case, output="", workdir=tmp_path)
        assert results[0]["passed"] is True
