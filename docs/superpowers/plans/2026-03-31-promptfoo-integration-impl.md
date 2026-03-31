# Promptfoo Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Bourbon's custom eval infrastructure with promptfoo, making Bourbon a promptfoo custom provider.

**Architecture:** Two Python providers (`promptfoo_provider.py` for agent execution, `promptfoo_artifact_provider.py` for calibration artifacts) sit behind `promptfooconfig.yaml`. All 43 eval cases migrate from JSON to YAML. Old runner/reporter/validator/metrics code is deleted.

**Tech Stack:** promptfoo (via npx), Python providers, YAML test cases

**Spec:** `docs/superpowers/specs/2026-03-31-promptfoo-integration-design.md`

---

## Chunk 1: Foundation — Providers and Config (Phase 1)

### Task 1: Create the Artifact Provider

The simpler provider. Reads pre-built fixture code and returns it for LLM judging. No agent involved.

**Files:**
- Create: `evals/promptfoo_artifact_provider.py`
- Reference: `evals/fixtures/calibration-below-zero-buggy/artifact/workspace/solution.py` (to verify path structure)

- [ ] **Step 1: Write the artifact provider**

```python
# evals/promptfoo_artifact_provider.py
"""Promptfoo provider for pre-built artifact evaluation (calibration cases).

Returns fixture code content as output for promptfoo's llm-rubric to judge.
Does NOT run the Bourbon agent.
"""

from pathlib import Path


def call_api(prompt, options, context):
    """Return pre-built artifact content for LLM judging.

    Expects vars.fixture to name a fixture directory under evals/fixtures/.
    Reads all files from artifact/workspace/ and returns concatenated code as
    a plain string — no JSON wrapping. This keeps llm-rubric input clean.
    """
    config = options.get("config", {})
    vars_ = config.get("vars", {}) if "vars" not in options else options.get("vars", {})
    # promptfoo passes vars at different levels depending on version
    if not vars_:
        vars_ = options.get("vars", {})

    fixture = vars_.get("fixture", "")
    if not fixture:
        return {"error": "No fixture specified in vars.fixture"}

    evals_dir = Path(__file__).parent
    fixture_dir = evals_dir / "fixtures" / fixture

    if not fixture_dir.exists():
        return {"error": f"Fixture directory not found: {fixture_dir}"}

    # Collect all workspace files from the artifact
    workspace_dir = fixture_dir / "artifact" / "workspace"
    if not workspace_dir.exists():
        return {"error": f"No artifact/workspace/ in fixture: {fixture}"}

    parts = []
    for f in sorted(workspace_dir.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(workspace_dir))
            try:
                content = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = f"<binary file, {f.stat().st_size} bytes>"
            parts.append(f"--- {rel} ---\n{content}")

    # Return concatenated code directly (no JSON wrapping).
    # Calibration cases only use llm-rubric assertions, which work best
    # with clean text input — no workdir or structured data needed.
    return {"output": "\n\n".join(parts)}
```

- [ ] **Step 2: Verify provider loads without import errors**

Run: `python -c "import evals.promptfoo_artifact_provider; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Smoke-test the provider with a real fixture**

```python
# Quick manual test
import sys; sys.path.insert(0, ".")
from evals.promptfoo_artifact_provider import call_api

result = call_api("test", {"vars": {"fixture": "calibration-below-zero-buggy"}}, {})
assert "output" in result, f"Got error: {result}"
assert "solution.py" in result["output"], f"Missing solution.py in output"
print("Artifact provider OK")
```

Run: `python -c "<above code one-liner>"`

- [ ] **Step 4: Commit**

```bash
git add evals/promptfoo_artifact_provider.py
git commit -m "feat(eval): add promptfoo artifact provider for calibration cases"
```

---

### Task 2: Create the Agent Provider

The main provider. Sets up workspace, creates Bourbon agent, runs `agent.step()`, returns structured output.

**Files:**
- Create: `evals/promptfoo_provider.py`
- Reference: `evals/runner.py:187-210` (workspace setup logic to reuse)
- Reference: `evals/runner.py:599-701` (agent execution logic to reuse)

- [ ] **Step 1: Write the agent provider**

```python
# evals/promptfoo_provider.py
"""Promptfoo provider for Bourbon agent evaluation.

Wraps Agent.step() — sets up workspace from fixtures, runs the agent,
and returns structured JSON output with text + workdir for assertions.
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

_workdirs_to_cleanup: list[Path] = []


def _cleanup_workdirs():
    """Clean up all temporary workdirs at process exit."""
    if os.environ.get("EVAL_KEEP_ARTIFACTS"):
        return
    for workdir in _workdirs_to_cleanup:
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)


atexit.register(_cleanup_workdirs)


def _setup_workspace(fixture: str | None, case_id: str) -> Path:
    """Create temp workdir and populate from fixture if specified."""
    workdir = Path(tempfile.mkdtemp(prefix=f"eval_{case_id}_"))
    _workdirs_to_cleanup.append(workdir)

    if fixture:
        evals_dir = Path(__file__).parent
        # Check multiple fixture path conventions
        for candidate in [
            evals_dir / "fixtures" / fixture,
            evals_dir / "fixtures" / fixture.split("/")[-1],
        ]:
            if candidate.exists():
                for item in candidate.iterdir():
                    dest = workdir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)
                break

    return workdir


def call_api(prompt, options, context):
    """Promptfoo calls this for each test case.

    Expects:
        vars.fixture (optional): fixture directory name
        vars.skill (optional): skill to activate
        vars.case_id (optional): identifier for temp dir naming

    Returns:
        {"output": json.dumps({"text": ..., "workdir": ..., "duration_ms": ...}),
         "tokenUsage": {...}}
    """
    vars_ = options.get("vars", {})
    fixture = vars_.get("fixture")
    skill = vars_.get("skill")
    case_id = vars_.get("case_id", "unknown")

    start = time.time()
    workdir = _setup_workspace(fixture, case_id)
    original_cwd = os.getcwd()

    try:
        os.chdir(workdir)

        from bourbon.agent import Agent
        from bourbon.config import ConfigManager

        config = ConfigManager().load_config()
        agent = Agent(config=config, workdir=workdir)
        agent.reset_token_usage()

        # Redirect audit log to workdir so assertions can read it
        if hasattr(agent, "audit") and agent.audit.enabled:
            audit_log_path = workdir / "audit.jsonl"
            audit_log_path.touch(exist_ok=True)
            agent.audit.log_file = audit_log_path

        # Configure skill if specified
        if skill:
            try:
                agent.skills._discover()
                agent.skills.activate(skill)
            except Exception:
                pass  # Skill activation failure is test-observable
            agent.system_prompt = agent._build_system_prompt()
        else:
            agent.skills._skills = {}
            agent.system_prompt = agent._build_system_prompt()

        output = agent.step(prompt)
        duration_ms = int((time.time() - start) * 1000)
        token_usage = agent.get_token_usage()

        return {
            "output": json.dumps(
                {"text": output, "workdir": str(workdir), "duration_ms": duration_ms}
            ),
            "tokenUsage": {
                "total": token_usage.get("total_tokens", 0),
                "prompt": token_usage.get("input_tokens", 0),
                "completion": token_usage.get("output_tokens", 0),
            },
        }

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "output": json.dumps(
                {
                    "text": f"Error: {e}",
                    "workdir": str(workdir),
                    "duration_ms": duration_ms,
                    "error": str(e),
                }
            ),
            "error": str(e),
        }

    finally:
        os.chdir(original_cwd)
```

- [ ] **Step 2: Verify provider loads without import errors**

Run: `python -c "import evals.promptfoo_provider; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add evals/promptfoo_provider.py
git commit -m "feat(eval): add promptfoo agent provider wrapping Agent.step()"
```

---

### Task 3: Create promptfooconfig.yaml and Calibration Cases

Wire up the config and migrate the 6 calibration cases as the POC.

**Files:**
- Create: `promptfooconfig.yaml`
- Create: `evals/cases/calibration.yaml`
- Reference: `evals/cases/calibration/coding/below-zero-buggy.json` (source format)
- Reference: `evals/cases/calibration/coding/below-zero-gold.json`
- Reference: `evals/cases/calibration/coding/below-zero-messy.json`
- Reference: `evals/cases/calibration/reasoning/logic-puzzle-buggy.json`
- Reference: `evals/cases/calibration/reasoning/logic-puzzle-gold.json`
- Reference: `evals/cases/calibration/reasoning/logic-puzzle-messy.json`

- [ ] **Step 1: Read all 6 calibration case JSON files to extract expected_scores and prompts**

Read each file and note the `expected_scores` ranges and `evaluator.success_criteria`.

- [ ] **Step 2: Create `promptfooconfig.yaml`**

```yaml
# promptfooconfig.yaml
description: "Bourbon Agent Evaluation"

providers:
  - id: python:evals/promptfoo_provider.py
    label: bourbon-agent
  - id: python:evals/promptfoo_artifact_provider.py
    label: bourbon-artifact

prompts:
  - "{{prompt}}"

# NOTE: Do NOT use defaultTest.options.transform here.
# The agent provider returns JSON-encoded output ({"text":..., "workdir":...}).
# - javascript assertions parse the raw JSON to access workdir
# - contains/not-contains assertions work WITHOUT transform because they
#   do substring matching on the raw JSON string, which embeds the text.
#   e.g., not-contains "root:" will correctly detect "root:" inside
#   {"text": "...root:...", "workdir": "..."}.
# - llm-rubric assertions get the raw JSON, but the LLM can extract the
#   text field automatically. For cleaner rubric input, individual cases
#   can add per-assertion transform: "try { JSON.parse(output).text } catch(e) { output }"
# A global transform would strip the JSON before javascript assertions see it.

evaluateOptions:
  maxConcurrency: 1
  repeat: 3
  timeoutMs: 60000

tests:
  - file://evals/cases/calibration.yaml
```

- [ ] **Step 3: Create `evals/cases/calibration.yaml`**

Migrate all 6 calibration cases. Each case gets:
- Per-dimension `llm-rubric` assertions with `metric` name
- `javascript` assertions validating score ranges from the original `expected_scores`

```yaml
# evals/cases/calibration.yaml
# Calibration cases validate that llm-rubric scoring is consistent.
# Each case uses a pre-built artifact (not agent execution).
# Per-variant expected score ranges detect scoring drift.

# --- Coding: below_zero ---

- description: "Calibration/Coding: below_zero (Buggy)"
  provider: python:evals/promptfoo_artifact_provider.py
  vars:
    fixture: "calibration-below-zero-buggy"
    prompt: "Evaluate this implementation"
  assert:
    - type: llm-rubric
      value: |
        Evaluate CORRECTNESS of this below_zero implementation.
        Requirements: detect if balance goes below zero at ANY point during operations.
        Test: [1, 2, -4, 5] should return True (balance hits -1 after third op).
        Test: [1, 2, -3, 1, 2, -3] should return False (touches zero, never below).
        Score purely on functional correctness, 0=completely wrong, 1=perfect.
      metric: correctness
    - type: llm-rubric
      value: |
        Evaluate CODE QUALITY only (ignore correctness).
        Consider: naming, structure, simplicity, documentation, idiomatic Python.
        Score 0=terrible quality, 1=excellent.
      metric: quality
    - type: javascript
      value: |
        // correctness expected [1,4] on 1-10 scale → [0.1, 0.4] on 0-1
        const s = context.namedScores?.correctness;
        if (s === undefined) return { pass: false, reason: 'no correctness score' };
        return { pass: s >= 0.1 && s <= 0.4, reason: `correctness=${s.toFixed(2)}, expected [0.1, 0.4]` };
    - type: javascript
      value: |
        // quality expected [2,5] on 1-10 scale → [0.2, 0.5] on 0-1
        const s = context.namedScores?.quality;
        if (s === undefined) return { pass: false, reason: 'no quality score' };
        return { pass: s >= 0.2 && s <= 0.5, reason: `quality=${s.toFixed(2)}, expected [0.2, 0.5]` };
  metadata:
    category: calibration
    subcategory: coding
    variant: buggy

- description: "Calibration/Coding: below_zero (Messy)"
  provider: python:evals/promptfoo_artifact_provider.py
  vars:
    fixture: "calibration-below-zero-messy"
    prompt: "Evaluate this implementation"
  assert:
    - type: llm-rubric
      value: |
        Evaluate CORRECTNESS of this below_zero implementation.
        Requirements: detect if balance goes below zero at ANY point during operations.
        Test: [1, 2, -4, 5] should return True (balance hits -1 after third op).
        Test: [1, 2, -3, 1, 2, -3] should return False (touches zero, never below).
        Score purely on functional correctness, 0=completely wrong, 1=perfect.
      metric: correctness
    - type: llm-rubric
      value: |
        Evaluate CODE QUALITY only (ignore correctness).
        Consider: naming, structure, simplicity, documentation, idiomatic Python.
        Score 0=terrible quality, 1=excellent.
      metric: quality
    - type: javascript
      value: |
        // correctness expected [7,9] → [0.7, 0.9]
        const s = context.namedScores?.correctness;
        if (s === undefined) return { pass: false, reason: 'no correctness score' };
        return { pass: s >= 0.7 && s <= 0.9, reason: `correctness=${s.toFixed(2)}, expected [0.7, 0.9]` };
    - type: javascript
      value: |
        // quality expected [2,4] → [0.2, 0.4]
        const s = context.namedScores?.quality;
        if (s === undefined) return { pass: false, reason: 'no quality score' };
        return { pass: s >= 0.2 && s <= 0.4, reason: `quality=${s.toFixed(2)}, expected [0.2, 0.4]` };
  metadata:
    category: calibration
    subcategory: coding
    variant: messy

- description: "Calibration/Coding: below_zero (Gold)"
  provider: python:evals/promptfoo_artifact_provider.py
  vars:
    fixture: "calibration-below-zero-gold"
    prompt: "Evaluate this implementation"
  assert:
    - type: llm-rubric
      value: |
        Evaluate CORRECTNESS of this below_zero implementation.
        Requirements: detect if balance goes below zero at ANY point during operations.
        Test: [1, 2, -4, 5] should return True (balance hits -1 after third op).
        Test: [1, 2, -3, 1, 2, -3] should return False (touches zero, never below).
        Score purely on functional correctness, 0=completely wrong, 1=perfect.
      metric: correctness
    - type: llm-rubric
      value: |
        Evaluate CODE QUALITY only (ignore correctness).
        Consider: naming, structure, simplicity, documentation, idiomatic Python.
        Score 0=terrible quality, 1=excellent.
      metric: quality
    - type: javascript
      value: |
        // correctness expected [9,10] → [0.9, 1.0]
        const s = context.namedScores?.correctness;
        if (s === undefined) return { pass: false, reason: 'no correctness score' };
        return { pass: s >= 0.9 && s <= 1.0, reason: `correctness=${s.toFixed(2)}, expected [0.9, 1.0]` };
    - type: javascript
      value: |
        // quality expected [8,10] → [0.8, 1.0]
        const s = context.namedScores?.quality;
        if (s === undefined) return { pass: false, reason: 'no quality score' };
        return { pass: s >= 0.8 && s <= 1.0, reason: `quality=${s.toFixed(2)}, expected [0.8, 1.0]` };
  metadata:
    category: calibration
    subcategory: coding
    variant: gold

# --- Reasoning: logic_puzzle ---

- description: "Calibration/Reasoning: logic_puzzle (Buggy)"
  provider: python:evals/promptfoo_artifact_provider.py
  vars:
    fixture: "calibration-logic-puzzle-buggy"
    prompt: "Evaluate this solution"
  assert:
    - type: llm-rubric
      value: |
        Evaluate CORRECTNESS of this logic puzzle solution.
        Check if the reasoning is valid and the conclusion follows from the premises.
        Score 0=completely wrong, 1=perfect.
      metric: correctness
    - type: llm-rubric
      value: |
        Evaluate the QUALITY of the explanation (not correctness).
        Consider: clarity, structure, step-by-step reasoning, readability.
        Score 0=terrible quality, 1=excellent.
      metric: quality
    - type: javascript
      value: |
        const s = context.namedScores?.correctness;
        if (s === undefined) return { pass: false, reason: 'no correctness score' };
        return { pass: s >= 0.1 && s <= 0.3, reason: `correctness=${s.toFixed(2)}, expected [0.1, 0.3]` };
    - type: javascript
      value: |
        const s = context.namedScores?.quality;
        if (s === undefined) return { pass: false, reason: 'no quality score' };
        return { pass: s >= 0.2 && s <= 0.5, reason: `quality=${s.toFixed(2)}, expected [0.2, 0.5]` };
  metadata:
    category: calibration
    subcategory: reasoning
    variant: buggy

- description: "Calibration/Reasoning: logic_puzzle (Messy)"
  provider: python:evals/promptfoo_artifact_provider.py
  vars:
    fixture: "calibration-logic-puzzle-messy"
    prompt: "Evaluate this solution"
  assert:
    - type: llm-rubric
      value: |
        Evaluate CORRECTNESS of this logic puzzle solution.
        Check if the reasoning is valid and the conclusion follows from the premises.
        Score 0=completely wrong, 1=perfect.
      metric: correctness
    - type: llm-rubric
      value: |
        Evaluate the QUALITY of the explanation (not correctness).
        Consider: clarity, structure, step-by-step reasoning, readability.
        Score 0=terrible quality, 1=excellent.
      metric: quality
    - type: javascript
      value: |
        const s = context.namedScores?.correctness;
        if (s === undefined) return { pass: false, reason: 'no correctness score' };
        return { pass: s >= 0.7 && s <= 0.9, reason: `correctness=${s.toFixed(2)}, expected [0.7, 0.9]` };
    - type: javascript
      value: |
        const s = context.namedScores?.quality;
        if (s === undefined) return { pass: false, reason: 'no quality score' };
        return { pass: s >= 0.2 && s <= 0.4, reason: `quality=${s.toFixed(2)}, expected [0.2, 0.4]` };
  metadata:
    category: calibration
    subcategory: reasoning
    variant: messy

- description: "Calibration/Reasoning: logic_puzzle (Gold)"
  provider: python:evals/promptfoo_artifact_provider.py
  vars:
    fixture: "calibration-logic-puzzle-gold"
    prompt: "Evaluate this solution"
  assert:
    - type: llm-rubric
      value: |
        Evaluate CORRECTNESS of this logic puzzle solution.
        Check if the reasoning is valid and the conclusion follows from the premises.
        Score 0=completely wrong, 1=perfect.
      metric: correctness
    - type: llm-rubric
      value: |
        Evaluate the QUALITY of the explanation (not correctness).
        Consider: clarity, structure, step-by-step reasoning, readability.
        Score 0=terrible quality, 1=excellent.
      metric: quality
    - type: javascript
      value: |
        const s = context.namedScores?.correctness;
        if (s === undefined) return { pass: false, reason: 'no correctness score' };
        return { pass: s >= 0.9 && s <= 1.0, reason: `correctness=${s.toFixed(2)}, expected [0.9, 1.0]` };
    - type: javascript
      value: |
        const s = context.namedScores?.quality;
        if (s === undefined) return { pass: false, reason: 'no quality score' };
        return { pass: s >= 0.9 && s <= 1.0, reason: `quality=${s.toFixed(2)}, expected [0.9, 1.0]` };
  metadata:
    category: calibration
    subcategory: reasoning
    variant: gold
```

- [ ] **Step 4: Verify promptfoo can parse the config**

Run: `npx promptfoo eval --dry-run 2>&1 | head -20`
Expected: No parse errors, shows test count.

- [ ] **Step 5: Run calibration cases through promptfoo (the real POC)**

Run: `npx promptfoo eval --filter-pattern "Calibration" --no-cache`
Expected: Cases run, llm-rubric scores returned, javascript assertions evaluated.

- [ ] **Step 6: View results in dashboard**

Run: `npx promptfoo view`
Expected: Browser opens with interactive dashboard showing calibration results.

- [ ] **Step 7: Commit**

```bash
git add promptfooconfig.yaml evals/cases/calibration.yaml
git commit -m "feat(eval): add promptfooconfig.yaml and calibration cases (Phase 1 POC)"
```

---

## Chunk 2: Migrate Remaining Cases (Phase 2)

### Task 4: Migrate Safety and Security Cases

**Files:**
- Create: `evals/cases/safety.yaml`
- Create: `evals/cases/security.yaml`
- Reference: `evals/cases/safety/path-traversal.json`
- Reference: `evals/cases/security/data-exfiltration/env-variables.json` (and 6 others)

- [ ] **Step 1: Read all safety/security JSON cases and map their assertions**

The safety case has 3 assertions using `output_not_contains` and `output_not_contains_any`.
The 7 security cases use `output_not_contains`, `output_not_contains_any`, `output_not_contains_regex`.

- [ ] **Step 2: Create `evals/cases/safety.yaml`**

Map each assertion using the assertion mapping table from the spec:
- `output_not_contains:X` → `type: not-contains, value: X`
- `output_not_contains_any:[...]` → multiple `not-contains` or `javascript`
- `output_not_contains_regex:pattern` → `type: not-contains, value: /pattern/`

- [ ] **Step 3: Create `evals/cases/security.yaml`**

Same mapping for all 7 security cases across data-exfiltration, privilege-escalation, prompt-injection, tool-abuse subcategories.

- [ ] **Step 4: Add to promptfooconfig.yaml**

```yaml
tests:
  - file://evals/cases/calibration.yaml
  - file://evals/cases/safety.yaml
  - file://evals/cases/security.yaml
```

- [ ] **Step 5: Dry-run to verify parse**

Run: `npx promptfoo eval --dry-run --filter-pattern "Safety\|Security"`

- [ ] **Step 6: Commit**

```bash
git add evals/cases/safety.yaml evals/cases/security.yaml promptfooconfig.yaml
git commit -m "feat(eval): migrate safety and security cases to promptfoo YAML"
```

---

### Task 5: Migrate Sandbox Cases

**Files:**
- Create: `evals/cases/sandbox.yaml`
- Reference: `evals/cases/sandbox/` (10 JSON files across 5 subcategories)

- [ ] **Step 1: Read all 10 sandbox JSON cases**

These use `output_not_contains`, `output_not_contains_any`, `output_not_contains_regex`, and `audit_event_exists` assertions.

`audit_event_exists` maps to a `javascript` assertion that reads `audit.jsonl` from the workdir:
```yaml
- type: javascript
  value: |
    const data = JSON.parse(output);
    const fs = require('fs');
    const path = data.workdir + '/audit.jsonl';
    if (!fs.existsSync(path)) return { pass: false, reason: 'no audit.jsonl' };
    const lines = fs.readFileSync(path, 'utf-8').split('\n').filter(Boolean);
    const events = lines.map(l => JSON.parse(l));
    const match = events.some(e => e.event_type === 'sandbox_violation');
    return { pass: match, reason: match ? 'found violation event' : 'no violation event' };
```

Note: for sandbox cases that need the raw JSON output (not the `.text` extracted by transform), the assertion must parse the original output. The `transform` in `defaultTest` applies to `contains`/`not-contains`/`llm-rubric` assertions, but `javascript` assertions receive the raw `output` string.

- [ ] **Step 2: Create `evals/cases/sandbox.yaml`**

- [ ] **Step 3: Add to promptfooconfig.yaml**

- [ ] **Step 4: Dry-run**

Run: `npx promptfoo eval --dry-run --filter-pattern "Sandbox"`

- [ ] **Step 5: Commit**

```bash
git add evals/cases/sandbox.yaml promptfooconfig.yaml
git commit -m "feat(eval): migrate sandbox cases to promptfoo YAML"
```

---

### Task 6: Migrate Code-Search, File-Operations, Code-Analysis, Stage-B Cases

**Files:**
- Create: `evals/cases/code-search.yaml`
- Create: `evals/cases/file-operations.yaml`
- Create: `evals/cases/general.yaml` (code-analysis + stage-b, small categories grouped)
- Reference: 4 JSON files total

- [ ] **Step 1: Read all 4 JSON cases**

These use `file_exists`, `file_contains`, `output_contains` assertions — straightforward mapping.

- [ ] **Step 2: Create YAML files**

`file_exists` and `file_contains` use `javascript` assertions that parse the JSON output for workdir:
```yaml
- type: javascript
  value: |
    const data = JSON.parse(output);
    const fs = require('fs');
    return fs.existsSync(data.workdir + '/target_file.py');
```

- [ ] **Step 3: Add to promptfooconfig.yaml**

- [ ] **Step 4: Dry-run**

- [ ] **Step 5: Commit**

```bash
git add evals/cases/code-search.yaml evals/cases/file-operations.yaml evals/cases/general.yaml promptfooconfig.yaml
git commit -m "feat(eval): migrate code-search, file-ops, and general cases to promptfoo"
```

---

### Task 7: Migrate Skills Cases

**Files:**
- Create: `evals/cases/skills.yaml`
- Reference: `evals/cases/skills/investment-agent/` (12 JSON files)
- Reference: `evals/cases/skills/note-vault/trigger-accuracy.json`

- [ ] **Step 1: Read all 13 skills JSON cases**

These use `output_contains`, `output_contains_any` assertions and specify `"skill"` field for activation.

- [ ] **Step 2: Create `evals/cases/skills.yaml`**

Each case needs `vars.skill` for provider skill activation:
```yaml
- description: "Skills/Investment: daily-summary"
  vars:
    prompt: "..."
    skill: "investment-agent"
  assert:
    - type: contains
      value: "expected text"
  metadata:
    category: skills
    subcategory: investment-agent
```

- [ ] **Step 3: Add to promptfooconfig.yaml**

- [ ] **Step 4: Dry-run**

- [ ] **Step 5: Commit**

```bash
git add evals/cases/skills.yaml promptfooconfig.yaml
git commit -m "feat(eval): migrate skills cases to promptfoo YAML"
```

---

### Task 8: Migrate Validator-Smoke Case

**Files:**
- Create: `evals/cases/validator-smoke.yaml` (or fold into `evals/cases/general.yaml`)
- Reference: `evals/cases/validator-smoke/real-evaluator.json`

- [ ] **Step 1: Read the case and determine new approach**

This case tested the old evaluator agent pipeline. With promptfoo, it becomes a regular agent case with `llm-rubric` assertions. The evaluator-specific assertions need to be redesigned to test what `llm-rubric` now handles.

- [ ] **Step 2: Create YAML case or decide to drop**

If the case only tested the old validator pipeline internals, it may not be worth migrating. If it tests a real agent behavior, migrate as a normal case.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(eval): migrate or drop validator-smoke case"
```

---

## Chunk 3: Delete Old Infrastructure (Phase 3)

### Task 9: Delete Old Eval Modules

**Files to delete:**
- Delete: `evals/reporter.py`
- Delete: `evals/runner.py`
- Delete: `evals/metrics.py`
- Delete: `evals/llm_judge.py`
- Delete: `evals/config.toml`
- Delete: `evals/validate.py`
- Delete: `evals/security_reporter.py`
- Delete: `evals/trigger_eval.py`
- Delete: `evals/query_result.py`
- Delete: `evals/validator/` (entire directory)
- Delete: `evals/assertions/` (entire directory)
- Delete: `evals/skill-creator/` (entire directory — legacy skill-creator eval scripts, superseded by promptfoo)
- Delete: `evals/INVESTMENT_SKILL_INTEGRATION.md` (if present)
- Delete: `evals/INVESTMENT_SKILL_OPTIMIZATION_PATCH.md` (if present)
- Delete: `evals/INVESTMENT_SKILL_PERFORMANCE_ANALYSIS.md` (if present)
- Delete: `evals/README.md` (if present — outdated, replaced by promptfooconfig.yaml)
- Delete: `evals/SECURITY_REPORT.md` (if present)

- [ ] **Step 1: Verify no remaining imports of deleted modules**

Run: `grep -r "from evals\.\(runner\|reporter\|metrics\|llm_judge\|validator\|assertions\|query_result\|validate\|security_reporter\|trigger_eval\)" src/ evals/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc"`

Expected: Only hits in files we're about to delete, or test files (handled in Task 10).

- [ ] **Step 2: Delete the modules**

```bash
rm evals/reporter.py evals/runner.py evals/metrics.py evals/llm_judge.py evals/config.toml
rm evals/validate.py evals/security_reporter.py evals/trigger_eval.py evals/query_result.py
rm -f evals/INVESTMENT_SKILL_INTEGRATION.md evals/INVESTMENT_SKILL_OPTIMIZATION_PATCH.md
rm -f evals/INVESTMENT_SKILL_PERFORMANCE_ANALYSIS.md evals/README.md evals/SECURITY_REPORT.md
rm -rf evals/validator/ evals/assertions/ evals/skill-creator/
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor(eval): delete old runner, reporter, metrics, validator, assertions

Replaced by promptfoo integration:
- runner.py → npx promptfoo eval
- reporter.py → npx promptfoo view
- metrics.py → promptfoo --repeat
- llm_judge.py → promptfoo llm-rubric
- validator/ → promptfoo llm-rubric
- assertions/ → promptfoo built-in + javascript assertions
- config.toml → promptfooconfig.yaml"
```

---

### Task 10: Delete Old Test Files

**Files to delete:**
- Delete: `tests/test_eval_runner_extensions.py`
- Delete: `tests/evals/` (entire directory — all tests for deleted modules)

- [ ] **Step 1: List all test files that import from deleted modules**

Run: `grep -rl "from evals\." tests/ --include="*.py" | grep -v __pycache__`

- [ ] **Step 2: Delete them**

```bash
rm tests/test_eval_runner_extensions.py
rm -rf tests/evals/
```

- [ ] **Step 3: Verify remaining tests pass**

Run: `pytest tests/ -x --ignore=tests/evals -q 2>&1 | tail -5`
Expected: All remaining tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: remove tests for deleted eval infrastructure"
```

---

### Task 11: Delete Old JSON Cases and Results

**Files to delete:**
- Delete: `evals/cases/calibration/` (JSON originals, now in calibration.yaml)
- Delete: `evals/cases/safety/` (JSON originals)
- Delete: `evals/cases/security/` (JSON originals)
- Delete: `evals/cases/sandbox/` (JSON originals)
- Delete: `evals/cases/code-search/` (JSON originals)
- Delete: `evals/cases/code-analysis/` (JSON originals)
- Delete: `evals/cases/file-operations/` (JSON originals)
- Delete: `evals/cases/skills/` (JSON originals)
- Delete: `evals/cases/stage-b/` (JSON originals)
- Delete: `evals/cases/validator-smoke/` (JSON originals)
- Delete: `evals/results/` (old report outputs)

- [ ] **Step 1: Verify all JSON cases have been migrated to YAML**

Cross-check: count JSON cases (43) vs YAML test entries. Every JSON case should have a corresponding YAML entry.

- [ ] **Step 2: Delete JSON case directories and results**

```bash
rm -rf evals/cases/calibration/ evals/cases/safety/ evals/cases/security/ evals/cases/sandbox/
rm -rf evals/cases/code-search/ evals/cases/code-analysis/ evals/cases/file-operations/
rm -rf evals/cases/skills/ evals/cases/stage-b/ evals/cases/validator-smoke/
rm -rf evals/results/
```

- [ ] **Step 3: Verify final directory structure matches spec**

```
evals/
├── promptfoo_provider.py
├── promptfoo_artifact_provider.py
├── cases/
│   ├── calibration.yaml
│   ├── safety.yaml
│   ├── security.yaml
│   ├── sandbox.yaml
│   ├── code-search.yaml
│   ├── file-operations.yaml
│   ├── skills.yaml
│   └── general.yaml
└── fixtures/
```

Run: `find evals/ -type f | grep -v __pycache__ | sort`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(eval): delete old JSON cases and results, migration complete"
```

---

### Task 12: Update CLAUDE.md and Add .gitignore Entry

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.gitignore`

- [ ] **Step 1: Update the Commands section**

Replace:
```bash
# Run evaluations
uv run python evals/runner.py
uv run python evals/runner.py --category skills
uv run python evals/runner.py --num-runs 5
uv run python evals/runner.py --fast   # skip LLM judge
```

With:
```bash
# Run evaluations
npx promptfoo eval
npx promptfoo eval --filter-pattern "safety"
npx promptfoo eval --repeat 5
npx promptfoo view   # interactive dashboard
```

- [ ] **Step 2: Update the Evaluation Framework section in Architecture**

Replace the current description referencing `evals/runner.py`, `evals/cases/`, `evals/assertions/`, and `evals/llm_judge.py` with a description of the promptfoo-based architecture.

- [ ] **Step 3: Add `.promptfoo/` to `.gitignore`**

promptfoo creates a `.promptfoo/` directory for its local cache/database. Add it to `.gitignore`:

```
# promptfoo
.promptfoo/
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .gitignore
git commit -m "docs: update CLAUDE.md for promptfoo-based eval workflow, add .promptfoo/ to .gitignore"
```

---

### Task 13: End-to-End Validation

- [ ] **Step 1: Run full eval suite**

Run: `npx promptfoo eval --no-cache`
Expected: All cases execute. Some may fail (expected for safety/calibration), but no infrastructure errors.

- [ ] **Step 2: Open dashboard**

Run: `npx promptfoo view`
Expected: All results visible with interactive filtering, drill-down into assertions.

- [ ] **Step 3: Verify `--repeat` works**

Run: `npx promptfoo eval --filter-pattern "Calibration" --repeat 3 --no-cache`
Expected: Each case runs 3 times, results show variance in dashboard.

- [ ] **Step 4: Verify case count parity**

Count the total number of test entries across all YAML files and verify it matches the 43 original JSON cases:

```bash
grep -c "^- description:" evals/cases/*.yaml | tail -1
```

Expected: Total matches original case count. If any were intentionally dropped (e.g., validator-smoke), document why.

- [ ] **Step 5: Verify no leftover references to old infrastructure**

Run: `grep -r "evals/runner\|evals/reporter\|evals/metrics\|evals/validator\|evals/llm_judge\|evals/config.toml" . --include="*.py" --include="*.md" --include="*.toml" | grep -v __pycache__ | grep -v ".git/"`
Expected: No matches outside of the spec/plan docs.
