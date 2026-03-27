# Eval Validator Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded Phase 1 simulation in `run_evaluator_agent()` with real LLM-based evaluation using a Bourbon Agent that calls evaluator skills and submits structured results via a `submit_evaluation` tool.

**Architecture:** The evaluator subprocess instantiates a Bourbon Agent with a custom evaluator system prompt. For each dimension (correctness, quality), it runs an independent `agent.step()` call. The agent loads the evaluator skill, analyzes the artifact workspace with Read/Grep/Glob tools, then calls `submit_evaluation` to return a structured JSON result. Results are captured via a module-level variable pattern and assembled into a `ValidationReport`.

**Tech Stack:** Python 3.10+, Bourbon Agent framework, existing tool registry, subprocess isolation

**Reference Spec:** `docs/superpowers/specs/2026-03-27-eval-validator-phase2-design.md`

---

## File Structure

```
evals/validator/
├── evaluator_agent.py         # MODIFY: replace run_evaluator_agent() simulation with real Agent calls
├── submit_tool.py             # CREATE: submit_evaluation tool registration and result capture
├── __init__.py                # MODIFY: add new evaluator_agent exports (NOT submit_tool — subprocess only)
└── skills/
    ├── eval-correctness/
    │   └── SKILL.md           # REWRITE: full evaluation instructions
    └── eval-quality/
        └── SKILL.md           # REWRITE: full evaluation instructions

src/bourbon/
└── agent.py                   # MODIFY: add optional system_prompt parameter to __init__

tests/evals/validator/
├── test_submit_tool.py        # CREATE: unit tests for submit_evaluation tool
└── test_evaluator_agent.py    # REWRITE: tests for real Agent-based evaluation
```

---

## Task 1: Create `submit_evaluation` Tool

**Files:**
- Create: `evals/validator/submit_tool.py`
- Test: `tests/evals/validator/test_submit_tool.py`

- [ ] **Step 1: Write failing test for submit_evaluation tool**

```python
# tests/evals/validator/test_submit_tool.py
"""Tests for the submit_evaluation tool."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def test_handle_submit_stores_result():
    """submit_evaluation handler stores result in module state."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    output = handle_submit(
        score=8.5,
        reasoning="Good implementation",
        evidence=["file.py:10 correct output"],
    )
    result = get_result()
    assert result["score"] == 8.5
    assert result["reasoning"] == "Good implementation"
    assert result["evidence"] == ["file.py:10 correct output"]
    assert "已提交" in output or "submitted" in output.lower()


def test_clear_result_resets_state():
    """clear_result empties the stored evaluation."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    handle_submit(score=5.0, reasoning="test", evidence=[])
    clear_result()
    assert get_result() == {}


def test_handle_submit_with_optional_fields():
    """submit_evaluation accepts optional suggestions and breakdown."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    handle_submit(
        score=7.0,
        reasoning="Decent",
        evidence=["passes tests"],
        suggestions=["add docstrings"],
        breakdown={"naming": 8, "structure": 6},
    )
    result = get_result()
    assert result["suggestions"] == ["add docstrings"]
    assert result["breakdown"] == {"naming": 8, "structure": 6}


def test_get_result_returns_deep_copy():
    """get_result returns a deep copy, not a reference to internal state."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    handle_submit(score=9.0, reasoning="great", evidence=["a", "b"])
    r1 = get_result()
    r1["score"] = 0.0
    r1["evidence"].append("injected")
    r2 = get_result()
    assert r2["score"] == 9.0
    assert r2["evidence"] == ["a", "b"]


def test_handle_submit_rejects_invalid_score():
    """submit_evaluation rejects scores outside 0-10 range."""
    from evals.validator.submit_tool import clear_result, get_result, handle_submit

    clear_result()
    output = handle_submit(score=15.0, reasoning="too high", evidence=[])
    assert "Error" in output
    assert get_result() == {}  # not stored

    output = handle_submit(score=-1.0, reasoning="negative", evidence=[])
    assert "Error" in output
    assert get_result() == {}


def test_tool_registered_in_registry():
    """submit_evaluation tool is registered in the global ToolRegistry."""
    import evals.validator.submit_tool  # noqa: F401 — triggers registration
    from bourbon.tools import get_registry

    tool = get_registry().get("submit_evaluation")
    assert tool is not None
    assert tool.name == "submit_evaluation"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/evals/validator/test_submit_tool.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.validator.submit_tool'`

- [ ] **Step 3: Create submit_tool.py**

```python
# evals/validator/submit_tool.py
"""submit_evaluation tool — captures structured evaluation results from the evaluator LLM."""

from __future__ import annotations

import copy

from bourbon.tools import RiskLevel, Tool, get_registry

# Module-level result storage (per-process, safe in subprocess isolation)
_evaluation_result: dict = {}


def handle_submit(
    score: float,
    reasoning: str,
    evidence: list[str],
    suggestions: list[str] | None = None,
    breakdown: dict | None = None,
) -> str:
    """Handle submit_evaluation tool call from the evaluator LLM."""
    # Validate score range
    if not isinstance(score, (int, float)):
        return f"Error: score must be a number, got {type(score).__name__}. Please retry."
    if score < 0 or score > 10:
        return f"Error: score must be between 0 and 10, got {score}. Please retry."

    _evaluation_result.clear()
    _evaluation_result.update(
        {
            "score": float(score),
            "reasoning": reasoning,
            "evidence": evidence,
            "suggestions": suggestions or [],
            "breakdown": breakdown or {},
        }
    )
    return "评估已提交。无需进一步操作。"


def get_result() -> dict:
    """Return a deep copy of the current evaluation result."""
    return copy.deepcopy(_evaluation_result)


def clear_result() -> None:
    """Clear the stored evaluation result."""
    _evaluation_result.clear()


def _tool_handler(**kwargs) -> str:
    """Wrapper that unpacks tool_input kwargs for handle_submit."""
    return handle_submit(
        score=kwargs.get("score", 0.0),
        reasoning=kwargs.get("reasoning", ""),
        evidence=kwargs.get("evidence", []),
        suggestions=kwargs.get("suggestions"),
        breakdown=kwargs.get("breakdown"),
    )


# Register the tool at import time
_submit_tool = Tool(
    name="submit_evaluation",
    description="Submit your structured evaluation result. Call this after analyzing the artifact workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "Score from 0 to 10",
                "minimum": 0,
                "maximum": 10,
            },
            "reasoning": {
                "type": "string",
                "description": "Explanation of why this score was given",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific evidence supporting the score (file paths, code snippets, observations)",
            },
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Improvement suggestions",
            },
            "breakdown": {
                "type": "object",
                "description": "Optional sub-dimension scores",
            },
        },
        "required": ["score", "reasoning", "evidence"],
    },
    handler=_tool_handler,
    risk_level=RiskLevel.LOW,
    required_capabilities=[],
)
get_registry().register(_submit_tool)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/evals/validator/test_submit_tool.py -v
```
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add evals/validator/submit_tool.py tests/evals/validator/test_submit_tool.py
git commit -m "feat(eval): add submit_evaluation tool for evaluator result capture

- Module-level result storage with get_result/clear_result API
- Tool registered directly on ToolRegistry (no decorator)
- Subprocess-only: never imported in main process"
```

---

## Task 2: Add `system_prompt` Parameter to Agent

**Files:**
- Modify: `src/bourbon/agent.py:41-75`
- Test: `tests/evals/validator/test_submit_tool.py` (reuse existing test infrastructure)

- [ ] **Step 1: Write failing test**

```python
# tests/test_agent_system_prompt.py
"""Test Agent accepts custom system_prompt."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bourbon.config import ConfigManager


def test_agent_uses_custom_system_prompt(tmp_path: Path):
    """Agent.__init__ uses provided system_prompt instead of _build_system_prompt()."""
    config = ConfigManager().load_config()

    from bourbon.agent import Agent

    custom_prompt = "You are an evaluator agent."
    agent = Agent(config=config, workdir=tmp_path, system_prompt=custom_prompt)

    assert agent.system_prompt == custom_prompt


def test_agent_default_system_prompt(tmp_path: Path):
    """Agent.__init__ builds default system_prompt when none provided."""
    config = ConfigManager().load_config()

    from bourbon.agent import Agent

    agent = Agent(config=config, workdir=tmp_path)

    assert agent.system_prompt != ""
    assert "evaluator" not in agent.system_prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent_system_prompt.py -v
```
Expected: FAIL (Agent.__init__ does not accept `system_prompt` parameter)

- [ ] **Step 3: Modify Agent.__init__ to accept optional system_prompt**

In `src/bourbon/agent.py`, three changes:

**Change 1:** Add `system_prompt` parameter to `__init__` signature (line 41):

```python
    def __init__(
        self,
        config: Config,
        workdir: Path | None = None,
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
        system_prompt: str | None = None,  # NEW: optional custom system prompt
    ):
```

**Change 2:** Use the parameter on line 75:

```python
        # Build system prompt (will be updated after MCP connect)
        self._custom_system_prompt = system_prompt
        self.system_prompt = system_prompt or self._build_system_prompt()
```

**Change 3:** Guard `_finalize_mcp_initialization` (line 131-137) to preserve custom prompt:

```python
    def _finalize_mcp_initialization(self, results: dict) -> dict:
        """Update prompt state after MCP initialization."""
        if results and not self._custom_system_prompt:
            summary = self.mcp.get_connection_summary()
            if summary["total_tools"] > 0:
                self.system_prompt = self._build_system_prompt()
        return results
```

This ensures that if a custom system prompt was provided, MCP initialization does not overwrite it.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_agent_system_prompt.py -v
```
Expected: Both tests PASS

- [ ] **Step 5: Run existing tests to ensure no regression**

```bash
pytest tests/ -v --timeout=30 2>&1 | tail -20
```
Expected: No new failures

- [ ] **Step 6: Commit**

```bash
git add src/bourbon/agent.py tests/test_agent_system_prompt.py
git commit -m "feat(agent): add optional system_prompt parameter to Agent.__init__

Allows callers to override the default system prompt without
subclassing. Existing behavior unchanged when parameter is omitted."
```

---

## Task 3: Upgrade Evaluator Skills

**Files:**
- Rewrite: `evals/validator/skills/eval-correctness/SKILL.md`
- Rewrite: `evals/validator/skills/eval-quality/SKILL.md`

- [ ] **Step 1: Rewrite eval-correctness SKILL.md**

```markdown
---
name: eval-correctness
description: Evaluate whether agent output correctly fulfills task requirements.
metadata:
  version: "2.0"
  author: bourbon
---

# Correctness Evaluation Guide

## Your Role

You are evaluating whether an AI agent correctly completed a given task. You have access to the full artifact: the original task prompt, success criteria, the agent's output, and the resulting workspace files.

## Evaluation Process

1. Read `context.json` to understand the task prompt and success criteria
2. Read `output.json` to see the agent's final response
3. Examine files in `workspace/` using Read, Glob, and Grep tools
4. Verify each success criterion against the actual workspace state
5. Call `submit_evaluation` with your structured assessment

## Scoring Rubric

| Score | Meaning |
|-------|---------|
| 9-10  | All success criteria fully met, no omissions |
| 7-8   | Core criteria met, minor deviations |
| 5-6   | Partial criteria met, clear gaps |
| 3-4   | Few criteria met, significant issues |
| 0-2   | Task requirements essentially unmet |

## Evidence Requirements

Your evidence MUST reference specific artifacts:
- File paths and line numbers for code claims
- Exact text for content verification claims
- Specific criterion IDs when checking success criteria

## Output

After completing your analysis, call `submit_evaluation` to submit your result. Do not output JSON as text — use the tool.
```

- [ ] **Step 2: Rewrite eval-quality SKILL.md**

```markdown
---
name: eval-quality
description: Evaluate code and response quality for maintainability and clarity.
metadata:
  version: "2.0"
  author: bourbon
---

# Quality Evaluation Guide

## Your Role

You are evaluating the quality of code and responses produced by an AI agent. Focus on maintainability, clarity, and adherence to good engineering practices.

## Evaluation Process

1. Read `output.json` to assess the agent's response quality
2. Examine code files in `workspace/` using Read, Glob, and Grep tools
3. Assess code structure, naming, readability, and complexity
4. Check for anti-patterns, redundancy, and unnecessary complexity
5. Call `submit_evaluation` with your structured assessment

## Scoring Rubric

| Score | Meaning |
|-------|---------|
| 9-10  | Clean, well-structured, no redundancy, clear response |
| 7-8   | Good quality overall, minor improvement opportunities |
| 5-6   | Functional but notable quality issues |
| 3-4   | Messy code or unclear response |
| 0-2   | Very poor quality, hard to understand or maintain |

## Quality Dimensions

Consider these aspects (weight them according to relevance):
- **Naming**: Do names clearly express intent?
- **Structure**: Are functions/methods reasonably sized?
- **Simplicity**: Is unnecessary complexity avoided?
- **Error handling**: Is it appropriate (not excessive, not absent)?
- **Response clarity**: Is the agent's text output concise and helpful?

## Evidence Requirements

Reference specific code when making claims:
- File paths and line numbers
- Code snippets demonstrating issues or good practices
- Concrete examples, not vague observations

## Output

After completing your analysis, call `submit_evaluation` to submit your result. Do not output JSON as text — use the tool.
```

- [ ] **Step 3: Verify skill loading**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from bourbon.skills import SkillScanner
from pathlib import Path
scanner = SkillScanner(Path('.'))
skills = scanner.scan()
for name, skill in skills.items():
    if name.startswith('eval-'):
        print(f'{name}: {skill.description[:60]}')
"
```
Expected: Both eval-correctness and eval-quality found with updated descriptions.

Note: If skills are not found in the project scan, run `python -c "from evals.validator.install_skills import install_skills; install_skills()"` to install to `~/.bourbon/skills/`, then re-scan.

- [ ] **Step 4: Commit**

```bash
git add evals/validator/skills/
git commit -m "feat(eval): upgrade evaluator skills with full assessment guides

- eval-correctness: detailed rubric, evidence requirements, process steps
- eval-quality: quality dimensions, code-specific evaluation criteria
- Both skills now guide LLM to use submit_evaluation tool"
```

---

## Task 4: Rewrite `run_evaluator_agent()` with Real Agent Calls

**Files:**
- Modify: `evals/validator/evaluator_agent.py:88-149`
- Rewrite: `tests/evals/validator/test_evaluator_agent.py`

- [ ] **Step 1: Write failing tests for Phase 2 evaluator**

```python
# tests/evals/validator/test_evaluator_agent.py
"""Tests for Phase 2 evaluator agent with real Agent calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evals.validator.artifact import ArtifactBuilder
from evals.validator.evaluator_agent import (
    EVALUATOR_SYSTEM_PROMPT,
    EvaluatorConfig,
    build_evaluation_prompt,
    create_evaluator_agent,
    run_evaluator_agent,
)
from evals.validator.report import ValidationReport


def _make_artifact(tmp_path: Path) -> Path:
    """Helper: create a minimal artifact for testing."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    builder = ArtifactBuilder(case_id="test-001", workdir=workdir)
    builder.set_context(prompt="Write hello world", success_criteria=["prints hello"])
    builder.set_output(final_output="Done")
    return builder.build()


def test_evaluator_system_prompt_exists():
    """EVALUATOR_SYSTEM_PROMPT is defined and contains evaluator role."""
    assert "评审" in EVALUATOR_SYSTEM_PROMPT or "evaluator" in EVALUATOR_SYSTEM_PROMPT.lower()
    assert "submit_evaluation" in EVALUATOR_SYSTEM_PROMPT


def test_build_evaluation_prompt_contains_skill_and_steps():
    """build_evaluation_prompt includes dimension name and skill name."""
    prompt = build_evaluation_prompt("correctness", "eval-correctness")
    assert "correctness" in prompt
    assert "eval-correctness" in prompt
    assert "context.json" in prompt
    assert "submit_evaluation" in prompt


def test_run_evaluator_agent_calls_agent_step(tmp_path: Path):
    """run_evaluator_agent creates Agent and calls step() per dimension."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    # Simulate submit_evaluation being called during step()
    def fake_step(prompt):
        from evals.validator.submit_tool import handle_submit
        handle_submit(score=8.0, reasoning="Good", evidence=["file.py works"])
        return "Evaluation complete"

    mock_agent.step.side_effect = fake_step

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={"correctness": "eval-correctness"},
            )
        )

    assert mock_agent.step.call_count == 1
    assert report.dimensions[0].score == 8.0
    assert report.dimensions[0].reasoning == "Good"


def test_run_evaluator_agent_handles_missing_submission(tmp_path: Path):
    """When LLM never calls submit_evaluation, dimension gets score=0."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    mock_agent.step.return_value = "I analyzed the code but forgot to submit."

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={"correctness": "eval-correctness"},
            )
        )

    assert report.dimensions[0].score == 0.0
    assert "no evaluation submitted" in report.dimensions[0].reasoning


def test_run_evaluator_agent_handles_step_exception(tmp_path: Path):
    """When agent.step() raises, dimension gets score=0 with error message."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    mock_agent.step.side_effect = RuntimeError("LLM connection failed")

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={"correctness": "eval-correctness"},
            )
        )

    assert report.dimensions[0].score == 0.0
    assert "LLM connection failed" in report.dimensions[0].reasoning


def test_run_evaluator_agent_multiple_dimensions(tmp_path: Path):
    """Each dimension gets an independent step() call."""
    artifact_dir = _make_artifact(tmp_path)

    mock_agent = MagicMock()
    mock_agent.messages = []
    call_count = 0

    def fake_step(prompt):
        nonlocal call_count
        from evals.validator.submit_tool import handle_submit
        call_count += 1
        if "correctness" in prompt:
            handle_submit(score=9.0, reasoning="Correct", evidence=["all criteria met"])
        else:
            handle_submit(score=7.5, reasoning="Decent", evidence=["clean code"])
        return "Done"

    mock_agent.step.side_effect = fake_step

    with patch(
        "evals.validator.evaluator_agent.create_evaluator_agent",
        return_value=mock_agent,
    ):
        report = run_evaluator_agent(
            EvaluatorConfig(
                artifact_dir=artifact_dir,
                focus=["correctness", "quality"],
                threshold=8.0,
                timeout=60,
                dimension_to_skill={
                    "correctness": "eval-correctness",
                    "quality": "eval-quality",
                },
            )
        )

    assert call_count == 2
    assert report.dimensions[0].name == "correctness"
    assert report.dimensions[0].score == 9.0
    assert report.dimensions[1].name == "quality"
    assert report.dimensions[1].score == 7.5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/evals/validator/test_evaluator_agent.py -v
```
Expected: FAIL — `EVALUATOR_SYSTEM_PROMPT`, `build_evaluation_prompt`, `create_evaluator_agent` don't exist yet

- [ ] **Step 3: Rewrite evaluator_agent.py**

Replace lines 88-149 of `evals/validator/evaluator_agent.py` with the Phase 2 implementation. Keep `EvaluatorConfig` (lines 16-25) and `EvaluatorAgentRunner` (lines 28-85) unchanged.

```python
# evals/validator/evaluator_agent.py — full file replacement
"""Evaluator subprocess entrypoints."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from evals.validator.artifact import OutputArtifact
from evals.validator.report import ValidationDimension, ValidationReport


@dataclass
class EvaluatorConfig:
    """Configuration for the evaluator subprocess."""

    artifact_dir: Path
    focus: list[str]
    threshold: float
    timeout: int
    dimensions_config: dict = field(default_factory=dict)
    dimension_to_skill: dict[str, str] = field(default_factory=dict)


class EvaluatorAgentRunner:
    """Launch the evaluator subprocess."""

    def __init__(
        self,
        artifact_dir: Path,
        focus: list[str],
        threshold: float = 8.0,
        timeout: int = 60,
        dimensions_config: dict | None = None,
        dimension_to_skill: dict | None = None,
    ):
        self.artifact_dir = artifact_dir
        self.focus = focus
        self.threshold = threshold
        self.timeout = timeout
        self.dimensions_config = dimensions_config or {}
        self.dimension_to_skill = dimension_to_skill or {}

    def run(self) -> Path:
        repo_root = Path(__file__).resolve().parents[2]
        config_path = self.artifact_dir.parent / "evaluator_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "dimensions": self.dimensions_config,
                    "dimension_to_skill": self.dimension_to_skill,
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "evals.validator.evaluator_agent",
                "--artifact-dir",
                str(self.artifact_dir),
                "--focus",
                json.dumps(self.focus),
                "--threshold",
                str(self.threshold),
                "--config",
                str(config_path),
            ],
            timeout=self.timeout,
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "evaluator subprocess failed")

        report_path = self.artifact_dir.parent / "validation" / "report.json"
        if not report_path.exists():
            raise RuntimeError(f"validation report not found: {report_path}")
        return report_path


# ---------------------------------------------------------------------------
# Phase 2: Real LLM-based evaluation
# ---------------------------------------------------------------------------

EVALUATOR_SYSTEM_PROMPT = """\
You are a code review agent. Your task is to evaluate the output of another AI agent.

## How To Work

1. You will receive an evaluation task specifying a dimension and a corresponding skill.
2. Call the specified skill to load evaluation criteria and guidelines.
3. Use Read, Glob, and Grep tools to analyze files in the workspace/ directory.
4. Read context.json for the original task prompt and success criteria.
5. Read output.json for the agent's final response.
6. After analysis, call submit_evaluation to submit your structured result.

## Rules

- You are a reviewer, not a developer. Do NOT modify any files.
- Score range is 0-10, based on criteria defined in the skill.
- Evidence must reference specific file paths, line numbers, or behavioral observations.
- Evaluate one dimension at a time.
- You MUST call submit_evaluation after completing your analysis.

## Artifact Layout

Your working directory contains:
- context.json — task prompt and success criteria
- output.json — the agent's final output
- meta.json — execution metadata (duration, tokens)
- workspace/ — file snapshot after agent execution
"""


def build_evaluation_prompt(dimension_name: str, skill_name: str) -> str:
    """Build the user message for a single dimension evaluation."""
    return f"""\
Evaluate dimension: {dimension_name}

Steps:
1. Call skill("{skill_name}") to load the evaluation criteria
2. Read these files for task context:
   - context.json
   - output.json
   - meta.json
3. Use Read, Glob, Grep to analyze code in workspace/
4. Call submit_evaluation to submit your assessment
"""


def create_evaluator_agent(artifact_dir: Path, system_prompt: str):
    """Create a Bourbon Agent configured for evaluation."""
    from bourbon.agent import Agent
    from bourbon.config import ConfigManager

    config = ConfigManager().load_config()
    config.ui.max_tool_rounds = 15

    return Agent(
        config=config,
        workdir=artifact_dir,
        system_prompt=system_prompt,
    )


def run_evaluator_agent(config: EvaluatorConfig) -> ValidationReport:
    """Run LLM-based evaluation for each dimension."""
    # Import triggers submit_evaluation tool registration in this subprocess
    from evals.validator.submit_tool import clear_result, get_result

    OutputArtifact.load(config.artifact_dir)

    agent = create_evaluator_agent(
        artifact_dir=config.artifact_dir,
        system_prompt=EVALUATOR_SYSTEM_PROMPT,
    )

    dimensions: list[ValidationDimension] = []
    for dimension_name in config.focus:
        dim_config = config.dimensions_config.get(dimension_name, {})
        threshold = dim_config.get("threshold", config.threshold)
        weight = dim_config.get("weight", 1.0 / len(config.focus))
        skill_name = config.dimension_to_skill.get(dimension_name, "")

        prompt = build_evaluation_prompt(dimension_name, skill_name)

        # Reset state between dimensions
        clear_result()
        agent.messages.clear()

        try:
            agent.step(prompt)
        except Exception as e:
            dimensions.append(
                ValidationDimension(
                    name=dimension_name,
                    score=0.0,
                    weight=weight,
                    threshold=threshold,
                    skill=skill_name,
                    reasoning=f"evaluation error: {e}",
                    evidence=[],
                    suggestions=[],
                )
            )
            continue

        result = get_result()
        dimensions.append(
            ValidationDimension(
                name=dimension_name,
                score=result.get("score", 0.0),
                weight=weight,
                threshold=threshold,
                skill=skill_name,
                reasoning=result.get("reasoning", "no evaluation submitted"),
                evidence=result.get("evidence", []),
                suggestions=result.get("suggestions", []),
                breakdown=result.get("breakdown", {}),
            )
        )

    report = ValidationReport(
        dimensions=dimensions,
        overall_threshold=config.threshold,
        summary="phase 2 LLM-based validation",
    )
    report_path = config.artifact_dir.parent / "validation" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.save(report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evaluator agent")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--focus", required=True)
    parser.add_argument("--threshold", type=float, default=8.0)
    parser.add_argument("--config")
    args = parser.parse_args()

    dimensions_config = {}
    dimension_to_skill = {}
    if args.config:
        config_data = json.loads(Path(args.config).read_text(encoding="utf-8"))
        dimensions_config = config_data.get("dimensions", {})
        dimension_to_skill = config_data.get("dimension_to_skill", {})

    run_evaluator_agent(
        EvaluatorConfig(
            artifact_dir=Path(args.artifact_dir),
            focus=json.loads(args.focus),
            threshold=args.threshold,
            timeout=300,
            dimensions_config=dimensions_config,
            dimension_to_skill=dimension_to_skill,
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/evals/validator/test_evaluator_agent.py -v
```
Expected: All 6 tests PASS

- [ ] **Step 5: Run full test suite for regression**

```bash
pytest tests/ -v --timeout=30 2>&1 | tail -30
```
Expected: No new failures

- [ ] **Step 6: Commit**

```bash
git add evals/validator/evaluator_agent.py tests/evals/validator/test_evaluator_agent.py
git commit -m "feat(eval): replace Phase 1 simulation with real LLM-based evaluation

- run_evaluator_agent() now creates Bourbon Agent with evaluator system prompt
- Per-dimension independent agent.step() calls
- Results captured via submit_evaluation tool
- Fallback to score=0 on missing submission or step() errors
- create_evaluator_agent() loads config via ConfigManager"
```

---

## Task 5: Update Package Exports and Verify Integration

**Files:**
- Modify: `evals/validator/__init__.py`

- [ ] **Step 1: Update __init__.py exports**

Add the new public symbols to `evals/validator/__init__.py`:

```python
# evals/validator/__init__.py
"""Validator package for eval generator/evaluator handoff."""

from .artifact import ArtifactBuilder, OutputArtifact
from .evaluator_agent import (
    EVALUATOR_SYSTEM_PROMPT,
    EvaluatorAgentRunner,
    EvaluatorConfig,
    build_evaluation_prompt,
    create_evaluator_agent,
    run_evaluator_agent,
)
from .report import ValidationDimension, ValidationReport

# NOTE: submit_tool is intentionally NOT imported here.
# It registers submit_evaluation in the global ToolRegistry at import time,
# which must only happen inside the evaluator subprocess, not the main process.
# It is imported inside run_evaluator_agent() instead.

__all__ = [
    "ArtifactBuilder",
    "EVALUATOR_SYSTEM_PROMPT",
    "EvaluatorAgentRunner",
    "EvaluatorConfig",
    "OutputArtifact",
    "ValidationDimension",
    "ValidationReport",
    "build_evaluation_prompt",
    "create_evaluator_agent",
    "run_evaluator_agent",
]
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v --timeout=30 2>&1 | tail -30
```
Expected: All tests PASS, no regressions

- [ ] **Step 3: Verify skills installed correctly**

```bash
python -c "
from evals.validator.install_skills import install_skills
installed = install_skills()
print('Installed:', installed)
"
```
Expected: `Installed: ['eval-correctness', 'eval-quality']`

- [ ] **Step 4: Commit**

```bash
git add evals/validator/__init__.py
git commit -m "chore(eval): update validator package exports for Phase 2"
```

---

## Task 6: Lint and Final Verification

- [ ] **Step 1: Run linter**

```bash
ruff check evals/validator/ tests/evals/validator/ src/bourbon/agent.py
```
Expected: No errors (fix any that appear)

- [ ] **Step 2: Run formatter**

```bash
ruff format evals/validator/ tests/evals/validator/ src/bourbon/agent.py
```

- [ ] **Step 3: Run type checker**

```bash
mypy src/bourbon/agent.py --ignore-missing-imports
```

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest tests/ -v --timeout=30
```
Expected: All tests PASS

- [ ] **Step 5: Final commit if any lint/format changes**

```bash
git add -u
git commit -m "chore(eval): lint and format Phase 2 validator code"
```
