> **⚠️ SUPERSEDED (lean revision 2026-06-24).** Do not implement. The redaction
> pipeline is deferred — see `specs/2026-06-22-flywheel-engine-design.md` §8
> (add-back trigger: traces exposed beyond the single trusted maintainer). The
> live plan set is `00-index`, `01-sdk`, `02-control-plane` only.

# Flywheel 03 — Redaction + Evidence Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the mandatory redaction pipeline that sits between Langfuse raw traces and every consumer (UI display and L3 LLM analysis). Implement `RedactionService` (versioned policies, fail-closed), `EvidenceReader` (Langfuse fetch → redact → policy decision), redaction analytics (redacted/blocked counts, coverage, over-block review), and the State Store records that pin which policy version produced each evidence view.

**Architecture:** `flywheel/api/redaction.py` holds the transforms + enforcement; `flywheel/engine/reader.py` is the only path L3 uses to read evidence. Raw payloads never leave the reader without passing through redaction. Synchronous. Redaction failures fail closed (return `blocked`, never raw).

**Tech Stack:** Python 3.13, pydantic v2, httpx (Langfuse read), pytest.

## Global Constraints

(See `2026-06-23-flywheel-00-index.md`.) Most relevant here:
- **Redaction fails closed.** L3 analyzer/proposer must never receive raw trace payloads. `blocked` evidence is hidden from UI and excluded from LLM analysis.
- State Store records which redaction policy and version produced each evidence view.
- `redacted` evidence may be used by UI and LLM analysis with redaction metadata attached.
- If redaction coverage is too low, analysis produces `needs_more_data` but must not bypass redaction.
- `RedactionState = Literal["raw", "redacted", "blocked"]` (defined in `sdk.schema`, plan 01).

---

## File Structure

- Create: `flywheel/api/redaction.py` — `RedactionPolicy`, `RedactionService`, `RedactionReport`
- Create: `flywheel/engine/__init__.py`
- Create: `flywheel/engine/reader.py` — `EvidenceReader` (Langfuse fetch + redact + decision)
- Modify: `flywheel/api/server.py` — add `GET /api/redaction/reports`, `GET /api/evidence/{path}`, `GET /api/traces/{path}`
- Test: `flywheel/tests/api/test_redaction.py`, `flywheel/tests/engine/test_reader.py`, and a server test for the reports route

**Interfaces consumed from earlier plans:**
- `RedactionState` from `sdk.schema` (plan 01).
- `JsonRecordStore` from `api.store`, `create_app` from `api.server` (plan 02).

---

## Task 1: RedactionPolicy + RedactionService (fail-closed transforms)

**Files:**
- Create: `flywheel/api/redaction.py`
- Test: `flywheel/tests/api/test_redaction.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class RedactionPolicy` with `version: str`, `secret_patterns: tuple[str, ...]` (regexes), `path_patterns: tuple[str, ...]`, `block_keys: tuple[str, ...]` (field names whose presence blocks the whole evidence item), `min_coverage: float` (0–1; below this → `blocked`).
  - `DEFAULT_POLICY: RedactionPolicy` covering credentials, filesystem paths, sandbox policy keys (Engine §10 lists credentials/paths/user data/sandbox policy).
  - `@dataclass class RedactionResult` with `state: RedactionState`, `payload: dict | None` (None when `blocked`), `policy_version: str`, `redacted_field_count: int`, `blocked_evidence: bool`, `coverage: float`.
  - `class RedactionService(policy: RedactionPolicy)`:
    - `redact(evidence: dict) -> RedactionResult`. Walks the dict; replaces secret/path matches with `"<redacted>"`; if any `block_keys` field is present at any nesting depth inside dicts/lists → `state="blocked"`, `payload=None`; if computed coverage `< policy.min_coverage` → `blocked`; any exception during redaction → fail closed `blocked`.
    - `coverage` = `1 - (suspected_sensitive_remaining / suspected_sensitive_total)`; with no sensitive content, coverage = `1.0`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_redaction.py
from api.redaction import RedactionService, RedactionPolicy, DEFAULT_POLICY


def test_redacts_secret_values():
    svc = RedactionService(DEFAULT_POLICY)
    result = svc.redact({"text": "token sk-ABCDEF0123456789 used"})
    assert result.state == "redacted"
    assert "sk-ABCDEF0123456789" not in str(result.payload)
    assert "<redacted>" in str(result.payload)
    assert result.redacted_field_count >= 1


def test_clean_evidence_is_redacted_state_full_coverage():
    svc = RedactionService(DEFAULT_POLICY)
    result = svc.redact({"text": "the agent read a file and answered"})
    assert result.state == "redacted"
    assert result.coverage == 1.0
    assert result.redacted_field_count == 0


def test_block_key_blocks_whole_item():
    policy = RedactionPolicy(version="t1", secret_patterns=(), path_patterns=(),
                             block_keys=("sandbox_policy",), min_coverage=0.5)
    svc = RedactionService(policy)
    result = svc.redact({"text": "ok", "sandbox_policy": {"deny": ["/etc"]}})
    assert result.state == "blocked"
    assert result.payload is None
    assert result.blocked_evidence is True


def test_nested_block_key_blocks_whole_item():
    svc = RedactionService(DEFAULT_POLICY)
    result = svc.redact({
        "spans": [
            {"name": "tool", "attributes": {"raw_env": {"OPENAI_API_KEY": "sk-hidden"}}}
        ]
    })
    assert result.state == "blocked"
    assert result.payload is None


def test_redaction_failure_fails_closed():
    policy = RedactionPolicy(version="bad", secret_patterns=("(",),  # invalid regex
                             path_patterns=(), block_keys=(), min_coverage=0.0)
    svc = RedactionService(policy)
    result = svc.redact({"text": "anything"})
    assert result.state == "blocked"
    assert result.payload is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_redaction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.redaction'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/api/redaction.py
"""Mandatory redaction pipeline (Engine §10). Fails closed: never emit raw on error."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sdk.schema import RedactionState

_REDACTED = "<redacted>"


@dataclass(frozen=True)
class RedactionPolicy:
    version: str
    secret_patterns: tuple[str, ...]
    path_patterns: tuple[str, ...]
    block_keys: tuple[str, ...]
    min_coverage: float


DEFAULT_POLICY = RedactionPolicy(
    version="2026-06-23.1",
    secret_patterns=(
        r"sk-[A-Za-z0-9]{8,}",            # API keys
        r"AKIA[0-9A-Z]{16}",              # AWS access key
        r"Bearer\s+[A-Za-z0-9._\-]+",     # bearer tokens
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ),
    path_patterns=(
        r"/(?:home|Users)/[^\s\"']+",     # user home paths
        r"/etc/[^\s\"']+",
    ),
    block_keys=("sandbox_policy", "credentials", "raw_env"),
    min_coverage=0.8,
)


@dataclass
class RedactionResult:
    state: RedactionState
    payload: dict | None
    policy_version: str
    redacted_field_count: int = 0
    blocked_evidence: bool = False
    coverage: float = 1.0


class RedactionService:
    def __init__(self, policy: RedactionPolicy):
        self._policy = policy

    def _blocked(self) -> RedactionResult:
        return RedactionResult(state="blocked", payload=None,
                               policy_version=self._policy.version,
                               blocked_evidence=True, coverage=0.0)

    def redact(self, evidence: dict) -> RedactionResult:
        try:
            # block-key short circuit at any depth. Nested credentials/raw_env/
            # sandbox_policy inside spans still block the whole evidence item.
            def has_block_key(value: object) -> bool:
                if isinstance(value, dict):
                    if any(k in self._policy.block_keys for k in value):
                        return True
                    return any(has_block_key(v) for v in value.values())
                if isinstance(value, list):
                    return any(has_block_key(v) for v in value)
                return False

            if has_block_key(evidence):
                return self._blocked()
            patterns = [re.compile(p) for p in
                        (*self._policy.secret_patterns, *self._policy.path_patterns)]
            redacted_count = 0
            suspected_total = 0
            suspected_remaining = 0

            def scrub(value: object) -> object:
                nonlocal redacted_count, suspected_total, suspected_remaining
                if isinstance(value, str):
                    out = value
                    for pat in patterns:
                        matches = pat.findall(out)
                        if matches:
                            suspected_total += len(matches)
                            redacted_count += len(matches)
                            out = pat.sub(_REDACTED, out)
                    # anything still matching after sub is a coverage miss
                    for pat in patterns:
                        suspected_remaining += len(pat.findall(out))
                    return out
                if isinstance(value, dict):
                    return {k: scrub(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [scrub(v) for v in value]
                return value

            scrubbed = scrub(evidence)
            assert isinstance(scrubbed, dict)
            coverage = 1.0 if suspected_total == 0 else \
                1.0 - (suspected_remaining / suspected_total)
            if coverage < self._policy.min_coverage:
                return self._blocked()
            return RedactionResult(
                state="redacted", payload=scrubbed,
                policy_version=self._policy.version,
                redacted_field_count=redacted_count, coverage=coverage,
            )
        except Exception:
            # fail closed — never leak raw on any error
            return self._blocked()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_redaction.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/redaction.py flywheel/tests/api/test_redaction.py
git commit -m "feat(api): fail-closed redaction service with versioned policies"
```

---

## Task 2: RedactionReport persistence + analytics

**Files:**
- Modify: `flywheel/api/redaction.py` (append `RedactionAnalytics`)
- Test: `flywheel/tests/api/test_redaction_analytics.py`

**Interfaces:**
- Consumes: `JsonRecordStore` (plan 02), `RedactionResult`.
- Produces:
  - `class RedactionAnalytics(store: JsonRecordStore)`:
    - `record(*, project, eval_run_id, results: list[RedactionResult], missing_trace_ids: list[str] | None = None) -> dict` — aggregates a list of `RedactionResult` into a report row in collection `"redaction_reports"` with fields: `project`, `eval_run_id`, `redacted_field_count`, `blocked_evidence_count`, `missing_trace_count`, `missing_trace_ids`, `evidence_coverage` (mean coverage over non-blocked; materially reduced by missing/blocked evidence for analysis readiness), `over_block_review_count` (starts 0), `policy_version`. Returns the stored row.
    - `mark_over_block(*, project, report_id) -> dict` — increments `over_block_review_count` (humans flagging evidence as too redacted to diagnose, Engine §10).
    - `list(project) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_redaction_analytics.py
from api.store import JsonRecordStore
from api.redaction import RedactionAnalytics, RedactionResult


def _results():
    return [
        RedactionResult(state="redacted", payload={}, policy_version="v1",
                        redacted_field_count=2, coverage=1.0),
        RedactionResult(state="redacted", payload={}, policy_version="v1",
                        redacted_field_count=1, coverage=0.9),
        RedactionResult(state="blocked", payload=None, policy_version="v1",
                        blocked_evidence=True, coverage=0.0),
    ]


def test_record_aggregates(tmp_path):
    an = RedactionAnalytics(JsonRecordStore(root=tmp_path))
    row = an.record(project="bourbon", eval_run_id="run1", results=_results())
    assert row["redacted_field_count"] == 3
    assert row["blocked_evidence_count"] == 1
    assert row["missing_trace_count"] == 0
    assert abs(row["evidence_coverage"] - 0.95) < 1e-9  # mean of 1.0 and 0.9
    assert row["over_block_review_count"] == 0
    assert row["policy_version"] == "v1"


def test_mark_over_block_increments(tmp_path):
    an = RedactionAnalytics(JsonRecordStore(root=tmp_path))
    row = an.record(project="bourbon", eval_run_id="run1", results=_results())
    updated = an.mark_over_block(project="bourbon", report_id=row["id"])
    assert updated["over_block_review_count"] == 1


def test_record_tracks_missing_traces(tmp_path):
    an = RedactionAnalytics(JsonRecordStore(root=tmp_path))
    row = an.record(project="bourbon", eval_run_id="run1", results=_results(),
                    missing_trace_ids=["trace_missing"])
    assert row["missing_trace_count"] == 1
    assert row["missing_trace_ids"] == ["trace_missing"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_redaction_analytics.py -v`
Expected: FAIL with `ImportError: cannot import name 'RedactionAnalytics'`.

- [ ] **Step 3: Append implementation to `redaction.py`**

```python
# flywheel/api/redaction.py  (append)
import uuid

from .store import JsonRecordStore


class RedactionAnalytics:
    def __init__(self, store: JsonRecordStore):
        self._store = store

    def record(self, *, project: str, eval_run_id: str,
               results: list[RedactionResult],
               missing_trace_ids: list[str] | None = None) -> dict:
        non_blocked = [r for r in results if r.state != "blocked"]
        coverage = (sum(r.coverage for r in non_blocked) / len(non_blocked)
                    if non_blocked else 0.0)
        policy_version = results[0].policy_version if results else "unknown"
        missing = missing_trace_ids or []
        report_id = f"redrep_{uuid.uuid4().hex[:12]}"
        return self._store.put("redaction_reports", report_id, {
            "project": project,
            "eval_run_id": eval_run_id,
            "redacted_field_count": sum(r.redacted_field_count for r in results),
            "blocked_evidence_count": sum(1 for r in results if r.state == "blocked"),
            "missing_trace_count": len(missing),
            "missing_trace_ids": missing,
            "evidence_coverage": coverage,
            "over_block_review_count": 0,
            "policy_version": policy_version,
        })

    def mark_over_block(self, *, project: str, report_id: str) -> dict:
        row = self._store.get("redaction_reports", report_id)
        if row is None:
            raise ValueError(f"unknown redaction report {report_id}")
        row["over_block_review_count"] = row.get("over_block_review_count", 0) + 1
        return self._store.put("redaction_reports", report_id, row)

    def list(self, project: str) -> list[dict]:
        return self._store.list("redaction_reports", project=project)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_redaction_analytics.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/api/redaction.py flywheel/tests/api/test_redaction_analytics.py
git commit -m "feat(api): redaction analytics with over-block review tracking"
```

---

## Task 3: EvidenceReader — the only L3 path to evidence

**Files:**
- Create: `flywheel/engine/__init__.py`
- Create: `flywheel/engine/reader.py`
- Test: `flywheel/tests/engine/test_reader.py`, `flywheel/tests/engine/__init__.py`

**Interfaces:**
- Consumes: `RedactionService`, `RedactionResult` (`api.redaction`).
- Produces:
  - `class EvidenceUnavailable(RuntimeError)`.
  - `class EvidenceReader(langfuse_url: str, langfuse_secret: str, redactor: RedactionService, client: httpx.Client | None)`:
    - `fetch_trace(trace_id: str) -> RedactionResult` — GETs `{langfuse_url}/api/public/traces/{trace_id}`, passes the raw JSON through `redactor.redact()`, returns the `RedactionResult`. If Langfuse 404 → raise `EvidenceUnavailable` (so UI can mark "trace missing", UI §13). On Langfuse 5xx → `EvidenceUnavailable`.
    - `fetch_redacted_failed_evidence(trace_ids: list[str]) -> tuple[list[dict], list[RedactionResult], list[str]]` — returns only `redacted` payloads (drops `blocked`), plus the full result list for analytics, plus `missing_trace_ids` for traces that Langfuse cannot return. **Raw payloads are never returned** — only `result.payload` for `redacted` items.
    - Missing traces are not silently discarded: UI can keep the evidence ref visible and mark it unavailable (UI §13), and analysis can produce `needs_more_data` when missing or blocked evidence materially reduces coverage.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/engine/test_reader.py
import httpx
import respx
import pytest
from api.redaction import RedactionService, DEFAULT_POLICY
from engine.reader import EvidenceReader, EvidenceUnavailable


def _reader():
    return EvidenceReader(langfuse_url="http://lf", langfuse_secret="sec",
                          redactor=RedactionService(DEFAULT_POLICY))


@respx.mock
def test_fetch_trace_returns_redacted_result():
    respx.get("http://lf/api/public/traces/t1").mock(
        return_value=httpx.Response(200, json={"output": "token sk-ABCDEF0123456789"})
    )
    result = _reader().fetch_trace("t1")
    assert result.state == "redacted"
    assert "sk-ABCDEF0123456789" not in str(result.payload)


@respx.mock
def test_missing_trace_raises_unavailable():
    respx.get("http://lf/api/public/traces/t1").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(EvidenceUnavailable):
        _reader().fetch_trace("t1")


@respx.mock
def test_failed_evidence_drops_blocked_items():
    respx.get("http://lf/api/public/traces/clean").mock(
        return_value=httpx.Response(200, json={"output": "fine"})
    )
    respx.get("http://lf/api/public/traces/secret").mock(
        return_value=httpx.Response(200, json={"sandbox_policy": {"deny": ["/etc"]}})
    )
    payloads, results, missing = _reader().fetch_redacted_failed_evidence(["clean", "secret"])
    assert len(payloads) == 1          # blocked item dropped from payloads
    assert len(results) == 2           # but counted in results for analytics
    assert missing == []
    assert any(r.state == "blocked" for r in results)


@respx.mock
def test_failed_evidence_returns_missing_trace_ids():
    respx.get("http://lf/api/public/traces/clean").mock(
        return_value=httpx.Response(200, json={"output": "fine"})
    )
    respx.get("http://lf/api/public/traces/missing").mock(
        return_value=httpx.Response(404)
    )
    payloads, results, missing = _reader().fetch_redacted_failed_evidence(
        ["clean", "missing"])
    assert len(payloads) == 1
    assert len(results) == 1
    assert missing == ["missing"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/engine/test_reader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.reader'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flywheel/engine/__init__.py
"""Flywheel L3 analysis engine."""
```

```python
# flywheel/engine/reader.py
"""EvidenceReader: the only path L3 uses to read evidence. Redaction enforced here."""
from __future__ import annotations

import httpx

from api.redaction import RedactionResult, RedactionService


class EvidenceUnavailable(RuntimeError):
    """Raised when a trace cannot be fetched from Langfuse (missing or error)."""


class EvidenceReader:
    def __init__(self, langfuse_url: str, langfuse_secret: str,
                 redactor: RedactionService, client: httpx.Client | None = None):
        self._url = langfuse_url.rstrip("/")
        self._secret = langfuse_secret
        self._redactor = redactor
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_trace(self, trace_id: str) -> RedactionResult:
        resp = self._client.get(
            f"{self._url}/api/public/traces/{trace_id}",
            headers={"Authorization": f"Bearer {self._secret}"},
        )
        if resp.status_code == 404:
            raise EvidenceUnavailable(f"trace {trace_id} not found in Langfuse")
        if resp.status_code >= 300:
            raise EvidenceUnavailable(
                f"langfuse trace fetch failed {resp.status_code} for {trace_id}")
        return self._redactor.redact(resp.json())

    def fetch_redacted_failed_evidence(
        self, trace_ids: list[str]
    ) -> tuple[list[dict], list[RedactionResult], list[str]]:
        payloads: list[dict] = []
        results: list[RedactionResult] = []
        missing_trace_ids: list[str] = []
        for trace_id in trace_ids:
            try:
                result = self.fetch_trace(trace_id)
            except EvidenceUnavailable:
                missing_trace_ids.append(trace_id)
                continue
            results.append(result)
            if result.state == "redacted" and result.payload is not None:
                payloads.append(result.payload)
        return payloads, results, missing_trace_ids
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/engine/test_reader.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add flywheel/engine/__init__.py flywheel/engine/reader.py flywheel/tests/engine/__init__.py flywheel/tests/engine/test_reader.py
git commit -m "feat(engine): EvidenceReader with enforced redaction, drops blocked items"
```

---

## Task 4: Wire GET /api/redaction/reports into the server

**Files:**
- Modify: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_redaction_route.py`

**Interfaces:**
- Consumes: `RedactionAnalytics`, `create_app` (plan 02).
- Produces:
  - `GET /api/redaction/reports?project=` → `{"reports": [...]}` (UI §10 read endpoint).
  - The app builds a `RedactionAnalytics(store)` during `create_app` and exposes it; a test helper writes a report directly via the analytics instance the app uses. To keep the test simple, expose `app.state.redaction_analytics`.

- [ ] **Step 1: Write the failing test**

```python
# flywheel/tests/api/test_redaction_route.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.server import create_app
from api.auth import Principal
from api.redaction import RedactionResult


def test_redaction_reports_route(tmp_path: Path):
    principal = Principal(actor_id="alice", roles=frozenset({"platform_maintainer"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    analytics = app.state.redaction_analytics
    analytics.record(project="bourbon", eval_run_id="run1", results=[
        RedactionResult(state="redacted", payload={}, policy_version="v1",
                        redacted_field_count=1, coverage=1.0),
    ])
    client = TestClient(app)
    r = client.get("/api/redaction/reports", params={"project": "bourbon"})
    assert r.status_code == 200
    assert len(r.json()["reports"]) == 1
    assert r.json()["reports"][0]["redacted_field_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_redaction_route.py -v`
Expected: FAIL with `AttributeError: ... 'redaction_analytics'` (route/state not yet wired).

- [ ] **Step 3: Modify `server.py`**

Add inside `create_app`, after the other services are built:

```python
# flywheel/api/server.py  (inside create_app, after baselines = ...)
    from .redaction import RedactionAnalytics
    redaction_analytics = RedactionAnalytics(store)
    app.state.redaction_analytics = redaction_analytics
```

Add the route (alongside the other `@app.get` routes):

```python
    @app.get("/api/redaction/reports")
    def list_redaction_reports(project: str):
        return {"reports": redaction_analytics.list(project)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_redaction_route.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/api/server.py flywheel/tests/api/test_redaction_route.py
git commit -m "feat(api): expose GET /api/redaction/reports"
```

---

## Task 5: Wire redacted evidence and trace read endpoints

**Files:**
- Modify: `flywheel/api/server.py`
- Test: `flywheel/tests/api/test_redaction_evidence_routes.py`

**Interfaces:**
- Consumes: `EvidenceReader`, `RedactionService`, `DEFAULT_POLICY`, and the plan-02 `REDACTION_ENABLED` hard gate.
- Produces:
  - `GET /api/evidence/{path:path}`
  - `GET /api/traces/{path:path}`
- Both routes keep returning 503 while `REDACTION_ENABLED` is unset. When enabled, they fetch only through `EvidenceReader.fetch_redacted_failed_evidence()`. They never return Langfuse raw payloads. Missing or blocked evidence is represented as an unavailable marker with no payload, so UI can keep the evidence reference visible without exposing unsafe content.

- [ ] **Step 1: Write the failing route tests**

```python
# flywheel/tests/api/test_redaction_evidence_routes.py
from pathlib import Path
from fastapi.testclient import TestClient
from api.auth import Principal
from api.redaction import RedactionResult
from api.server import create_app


class FakeEvidenceReader:
    def __init__(self, *, mode: str):
        self.mode = mode

    def fetch_redacted_failed_evidence(self, trace_ids):
        trace_id = trace_ids[0]
        if self.mode == "missing":
            return [], [], [trace_id]
        if self.mode == "blocked":
            return [], [RedactionResult(state="blocked", payload=None,
                policy_version="v1", redacted_field_count=0, coverage=0.0,
                blocked_evidence=True)], []
        return [{"trace_id": trace_id, "content": "safe",
                 "credentials": "[REDACTED]"}], [
            RedactionResult(state="redacted", payload={"trace_id": trace_id,
                "content": "safe", "credentials": "[REDACTED]"},
                policy_version="v1", redacted_field_count=1, coverage=1.0)
        ], []


def _client(tmp_path: Path, monkeypatch, *, enabled: bool, mode: str = "redacted"):
    if enabled:
        monkeypatch.setenv("REDACTION_ENABLED", "1")
    else:
        monkeypatch.delenv("REDACTION_ENABLED", raising=False)
    principal = Principal(actor_id="alice", roles=frozenset({"harness_owner"}))
    app = create_app(root=tmp_path, principal_resolver=lambda request: principal)
    app.state.evidence_reader = FakeEvidenceReader(mode=mode)
    return TestClient(app)


def test_evidence_and_trace_routes_stay_503_until_redaction_enabled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, enabled=False)
    assert client.get("/api/evidence/t1").status_code == 503
    assert client.get("/api/traces/t1").status_code == 503


def test_evidence_route_returns_only_redacted_payload(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, enabled=True)
    r = client.get("/api/evidence/t1")
    assert r.status_code == 200
    assert r.json()["payload"]["credentials"] == "[REDACTED]"
    assert "raw" not in r.text.lower()


def test_blocked_and_missing_evidence_return_unavailable_markers(tmp_path, monkeypatch):
    blocked = _client(tmp_path, monkeypatch, enabled=True, mode="blocked").get("/api/traces/t1")
    assert blocked.json()["unavailable"] is True
    assert blocked.json()["payload"] is None
    assert blocked.json()["redaction_state"] == "blocked"

    missing = _client(tmp_path, monkeypatch, enabled=True, mode="missing").get("/api/evidence/t2")
    assert missing.json()["unavailable"] is True
    assert missing.json()["reason"] == "missing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd flywheel && pytest tests/api/test_redaction_evidence_routes.py -v`
Expected: FAIL because plan 02 still returns 501 after the redaction gate is enabled.

- [ ] **Step 3: Replace the plan-02 evidence guard with redacted read handlers**

Keep the guard in the route handler so tests can inject `app.state.evidence_reader`
without requiring Langfuse credentials. Only instantiate the default reader after
the gate passes:

```python
# flywheel/api/server.py  (inside create_app, replacing the plan-02 evidence guard handlers)
    import os
    from .redaction import DEFAULT_POLICY, RedactionService
    from engine.reader import EvidenceReader

    def _evidence_reader():
        injected = getattr(app.state, "evidence_reader", None)
        if injected is not None:
            return injected
        return EvidenceReader(langfuse_url=os.environ["LANGFUSE_URL"],
                              langfuse_secret=os.environ["LANGFUSE_SECRET"],
                              redactor=RedactionService(DEFAULT_POLICY))

    def _redacted_evidence_response(path: str):
        if os.getenv("REDACTION_ENABLED", "") == "":
            return _json(503, {"detail": "evidence endpoints require redaction pipeline (plan 03); set REDACTION_ENABLED after wiring RedactionService"})
        payloads, results, missing_trace_ids = (
            _evidence_reader().fetch_redacted_failed_evidence([path])
        )
        if path in missing_trace_ids:
            return {"trace_id": path, "payload": None, "unavailable": True,
                    "reason": "missing", "redaction_state": "unavailable"}
        blocked = next((r for r in results
                        if r.state == "blocked" or r.blocked_evidence), None)
        if blocked is not None:
            return {"trace_id": path, "payload": None, "unavailable": True,
                    "reason": "redaction_blocked",
                    "redaction_state": "blocked"}
        return {"trace_id": path, "payload": payloads[0] if payloads else None,
                "unavailable": False, "redaction_state": "redacted"}

    @app.get("/api/evidence/{path:path}")
    def get_evidence(path: str):
        return _redacted_evidence_response(path)

    @app.get("/api/traces/{path:path}")
    def get_trace(path: str):
        return _redacted_evidence_response(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd flywheel && pytest tests/api/test_redaction_evidence_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite + lint + types, then commit**

```bash
cd flywheel && pytest -q && ruff check api engine sdk tests && mypy api engine sdk
git add flywheel/api/server.py flywheel/tests/api/test_redaction_evidence_routes.py
git commit -m "feat(api): serve redacted evidence and traces"
```

---

## Self-Review

- **Spec coverage (Engine §10, UI §13):** `RedactionService` is a mandatory pipeline step with versioned policy, recursive block-key scanning, fail-closed on exception and on low coverage (§10). `RedactionAnalytics` records redacted/blocked counts, missing trace count/ids, coverage, over-block review, policy version (§10 "each analysis report must include..."). `EvidenceReader` guarantees L3 never gets raw payloads and drops `blocked` items (§10 fail-closed + UI §13 "Redaction blocked → block analysis/proposal use"). Missing traces are returned as `missing_trace_ids` so UI can keep evidence refs visible and analysis can return `needs_more_data` instead of silently ignoring coverage loss. `/api/evidence/{path}` and `/api/traces/{path}` preserve the `REDACTION_ENABLED` 503 hard gate and serve only redacted payloads or unavailable markers.
- **Placeholder scan:** no TBD/TODO; every code step shows complete code.
- **Type consistency:** `RedactionState` reused from `sdk.schema` (plan 01). `RedactionResult` fields consumed identically by analytics and the reader. `JsonRecordStore`/`create_app` signatures match plan 02. The `redaction_reports` collection name and row shape match the UI §10 `GET /api/redaction/reports` consumer (plan 08).
