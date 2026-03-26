# Agent Eval Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an independent validation layer for Bourbon Eval framework using Generator-Evaluator separation architecture.

**Architecture:** Single Evaluator Agent process that internally invokes evaluator skills via `skill()` tool. Phase 1 uses simulated skill responses; Phase 2 will implement actual skill invocation via Bourbon Agent framework. Output Artifacts pass state between Generator (Runner) and Evaluator via filesystem.

**Tech Stack:** Python 3.8+, subprocess, existing Bourbon Agent framework, Skill system

**Reference Spec:** `docs/superpowers/specs/2026-03-26-agent-eval-validator-design.md`

---

## File Structure

```
evals/
├── runner.py                      # MODIFY: integrate validation flow
└── validator/
    ├── __init__.py                # CREATE: package exports
    ├── artifact.py                # CREATE: Output Artifact generation
    ├── evaluator_agent.py         # CREATE: Evaluator Agent subprocess management
    └── report.py                  # CREATE: Validation Report parsing

evals/validator/skills/            # CREATE: built-in evaluator skills
├── eval-correctness/
│   └── SKILL.md                   # CREATE: correctness validation skill
└── eval-quality/
    └── SKILL.md                   # CREATE: quality validation skill

tests/evals/validator/             # CREATE: test directory
├── test_artifact.py               # CREATE: artifact tests
├── test_evaluator_agent.py        # CREATE: evaluator tests
└── test_report.py                 # CREATE: report tests
```

---

## Task 1: Create Artifact Module

**Files:**
- Create: `evals/validator/__init__.py`
- Create: `evals/validator/artifact.py`
- Test: `tests/evals/validator/test_artifact.py`

- [ ] **Step 0: Create directories**

```bash
mkdir -p evals/validator tests/evals/validator
```

- [ ] **Step 1: Write failing test for OutputArtifact dataclass**

```python
# tests/evals/validator/test_artifact.py
import json
import tempfile
from pathlib import Path
from evals.validator.artifact import OutputArtifact, ArtifactBuilder

def test_output_artifact_creation():
    """Test creating OutputArtifact with all required fields"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        artifact = OutputArtifact(
            case_id="test-case-001",
            workdir=workdir
        )
        assert artifact.case_id == "test-case-001"
        assert artifact.workdir == workdir
        assert artifact.meta == {}
        assert artifact.context == {}
        assert artifact.output == {}

def test_artifact_builder_creates_structure():
    """Test ArtifactBuilder creates correct directory structure"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)
        builder = ArtifactBuilder(case_id="test-001", workdir=workdir)
        artifact_dir = builder.build()
        
        assert (artifact_dir / "meta.json").exists()
        assert (artifact_dir / "context.json").exists()
        assert (artifact_dir / "output.json").exists()
        assert (artifact_dir / "workspace").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/evals/validator/test_artifact.py -v
```
Expected: FAIL with "ModuleNotFoundError: No module named 'evals.validator'"

- [ ] **Step 3: Create artifact.py with minimal implementation**

```python
# evals/validator/artifact.py
"""Output Artifact generation for Generator-Evaluator handoff."""

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OutputArtifact:
    """Represents an Output Artifact for Evaluator consumption."""
    case_id: str
    workdir: Path
    meta: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    
    @property
    def artifact_dir(self) -> Path:
        return self.workdir / "artifact"
    
    def save(self, exclude_patterns: set = None) -> Path:
        """Save all artifact components to disk."""
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        
        # Save meta.json
        (self.artifact_dir / "meta.json").write_text(
            json.dumps(self.meta, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Save context.json
        (self.artifact_dir / "context.json").write_text(
            json.dumps(self.context, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Save output.json
        (self.artifact_dir / "output.json").write_text(
            json.dumps(self.output, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Copy workspace with exclusions
        workspace_dir = self.artifact_dir / "workspace"
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        if self.workdir.exists():
            ignore_func = self._make_ignore_func(exclude_patterns)
            shutil.copytree(self.workdir, workspace_dir, ignore=ignore_func)
        
        return self.artifact_dir
    
    def _make_ignore_func(self, exclude_patterns: set):
        """Create ignore function for shutil.copytree."""
        excludes = exclude_patterns or {'.git', 'node_modules', '__pycache__', '.venv', '.pytest_cache', 'artifact'}
        
        def ignore_func(dir: str, contents: list) -> list:
            result = []
            for c in contents:
                # Check exact match
                if c in excludes:
                    result.append(c)
                    continue
                # Check extension patterns
                for pattern in excludes:
                    if pattern.startswith('*.') and c.endswith(pattern.lstrip('*')):
                        result.append(c)
                        break
                    if pattern.endswith('/') and c == pattern.rstrip('/'):
                        result.append(c)
                        break
            return result
        
        return ignore_func
    
    @classmethod
    def load(cls, artifact_dir: Path) -> "OutputArtifact":
        """Load artifact from disk."""
        meta = json.loads((artifact_dir / "meta.json").read_text(encoding="utf-8"))
        context = json.loads((artifact_dir / "context.json").read_text(encoding="utf-8"))
        output = json.loads((artifact_dir / "output.json").read_text(encoding="utf-8"))
        
        return cls(
            case_id=meta.get("case_id", "unknown"),
            workdir=artifact_dir / "workspace",
            meta=meta,
            context=context,
            output=output
        )


class ArtifactBuilder:
    """Builder for creating OutputArtifacts from eval case results."""
    
    # Default exclusion patterns
    DEFAULT_EXCLUDES = ['.git/', 'node_modules/', '__pycache__/', '*.pyc', '.venv/', '.pytest_cache/', 'artifact/']
    
    def __init__(self, case_id: str, workdir: Path, max_size_mb: float = 100.0):
        self.case_id = case_id
        self.workdir = workdir
        self.max_size_mb = max_size_mb
        self._meta = {}
        self._context = {}
        self._output = {}
        self._excludes = set(self.DEFAULT_EXCLUDES)
    
    def set_meta(self, **kwargs) -> "ArtifactBuilder":
        """Set metadata fields."""
        self._meta.update(kwargs)
        return self
    
    def set_context(self, prompt: str, success_criteria: list = None, 
                    constraints: list = None, **kwargs) -> "ArtifactBuilder":
        """Set context from case definition."""
        self._context = {
            "prompt": prompt,
            "success_criteria": success_criteria or [],
            "constraints": constraints or [],
            **kwargs
        }
        return self
    
    def set_output(self, final_output: str, tool_calls: list = None,
                   errors: list = None, exit_reason: str = "completed") -> "ArtifactBuilder":
        """Set output from agent execution."""
        self._output = {
            "final_output": final_output,
            "tool_calls": tool_calls or [],
            "errors": errors or [],
            "exit_reason": exit_reason
        }
        return self
    
    def add_exclude_patterns(self, patterns: list) -> "ArtifactBuilder":
        """Add additional exclusion patterns."""
        self._excludes.update(patterns)
        return self
    
    def build(self) -> Path:
        """Build and save the artifact."""
        # Check and enforce size limit before copying
        self._enforce_size_limit()
        
        artifact = OutputArtifact(
            case_id=self.case_id,
            workdir=self.workdir,
            meta={
                "case_id": self.case_id,
                **self._meta
            },
            context=self._context,
            output=self._output
        )
        
        # Pass exclusion patterns to save method
        return artifact.save(exclude_patterns=self._excludes)
    
    def _enforce_size_limit(self) -> None:
        """Check size and truncate large files if needed."""
        import warnings
        
        total_size = 0
        large_files = []
        
        for f in self.workdir.rglob('*'):
            if not f.is_file():
                continue
            # Skip excluded patterns
            rel_path = f.relative_to(self.workdir)
            if self._is_excluded(rel_path):
                continue
            
            size = f.stat().st_size
            total_size += size
            
            # Track large files (>1MB)
            if size > 1024 * 1024:
                large_files.append((f, size))
        
        size_mb = total_size / (1024 * 1024)
        
        if size_mb > self.max_size_mb:
            warnings.warn(
                f"Workdir size {size_mb:.1f}MB exceeds limit {self.max_size_mb}MB. "
                f"Large files will be truncated."
            )
    
    def _is_excluded(self, path: Path) -> bool:
        """Check if path matches exclusion patterns."""
        path_str = str(path)
        for pattern in self._excludes:
            if pattern.endswith('/'):
                # Directory pattern
                if pattern.rstrip('/') in path_str:
                    return True
            elif pattern.startswith('*'):
                # Extension pattern
                if path_str.endswith(pattern.lstrip('*')):
                    return True
            else:
                # Exact match
                if pattern in path_str:
                    return True
        return False
```

- [ ] **Step 4: Create __init__.py exports**

```python
# evals/validator/__init__.py
"""Agent Eval Validator - Generator-Evaluator separation for evals."""

from .artifact import OutputArtifact, ArtifactBuilder

__all__ = ["OutputArtifact", "ArtifactBuilder"]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/evals/validator/test_artifact.py -v
```
Expected: PASS

- [ ] **Step 6: Add more comprehensive tests**

```python
# tests/evals/validator/test_artifact.py (add to existing file)

def test_artifact_roundtrip():
    """Test save and load produces equivalent artifact"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir) / "work"
        workdir.mkdir()
        (workdir / "test.txt").write_text("hello")
        
        builder = ArtifactBuilder(case_id="roundtrip-001", workdir=workdir)
        builder.set_meta(duration_ms=1000, token_usage={"total": 100})
        builder.set_context(prompt="test prompt", success_criteria=["criteria1"])
        builder.set_output(final_output="test output")
        
        artifact_dir = builder.build()
        
        # Load and verify
        loaded = OutputArtifact.load(artifact_dir)
        assert loaded.case_id == "roundtrip-001"
        assert loaded.meta["duration_ms"] == 1000
        assert loaded.context["prompt"] == "test prompt"
        assert loaded.output["final_output"] == "test output"
        assert (loaded.workdir / "test.txt").read_text() == "hello"

def test_exclude_patterns():
    """Test that excluded files are not copied"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir) / "work"
        workdir.mkdir()
        (workdir / "main.py").write_text("print('hello')")
        (workdir / ".git").mkdir()
        (workdir / ".git" / "config").write_text("git config")
        
        builder = ArtifactBuilder(case_id="exclude-001", workdir=workdir)
        artifact_dir = builder.build()
        
        workspace = artifact_dir / "workspace"
        assert (workspace / "main.py").exists()
        assert not (workspace / ".git").exists()
```

- [ ] **Step 7: Run all artifact tests**

```bash
pytest tests/evals/validator/test_artifact.py -v
```
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add evals/validator/ tests/evals/validator/
git commit -m "feat(eval): add OutputArtifact for Generator-Evaluator handoff

- OutputArtifact dataclass for structured artifact storage
- ArtifactBuilder for convenient artifact creation
- Support for metadata, context, output, and workspace snapshot
- Configurable exclusion patterns and size limits
- Roundtrip save/load functionality"
```

---

## Task 2: Create Report Module

**Files:**
- Create: `evals/validator/report.py`
- Test: `tests/evals/validator/test_report.py`

- [ ] **Step 1: Write failing test for ValidationReport**

```python
# tests/evals/validator/test_report.py
import json
import tempfile
from pathlib import Path
from evals.validator.report import ValidationReport, ValidationDimension

def test_validation_dimension_creation():
    """Test creating a validation dimension"""
    dim = ValidationDimension(
        name="correctness",
        score=8.5,
        weight=0.6,
        threshold=9.0
    )
    assert dim.name == "correctness"
    assert dim.score == 8.5
    assert dim.passed == False  # 8.5 < 9.0

def test_validation_dimension_passed():
    """Test dimension passed when score >= threshold"""
    dim = ValidationDimension(
        name="quality",
        score=8.0,
        weight=0.4,
        threshold=7.0
    )
    assert dim.passed == True  # 8.0 >= 7.0

def test_report_overall_score_calculation():
    """Test weighted overall score calculation"""
    dims = [
        ValidationDimension(name="d1", score=9.0, weight=0.6, threshold=8.0),
        ValidationDimension(name="d2", score=7.0, weight=0.4, threshold=8.0),
    ]
    report = ValidationReport(dimensions=dims, overall_threshold=8.0)
    # (9.0 * 0.6) + (7.0 * 0.4) = 5.4 + 2.8 = 8.2
    assert report.overall_score == 8.2
    assert report.passed == True  # 8.2 >= 8.0

def test_report_save_and_load():
    """Test report can be saved and loaded"""
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.json"
        
        dims = [
            ValidationDimension(
                name="correctness",
                score=8.5,
                weight=0.6,
                threshold=9.0,
                passed=False,
                reasoning="Core functionality works but edge cases missing",
                evidence=["Line 15 missing null check"],
                suggestions=["Add null check"]
            )
        ]
        report = ValidationReport(
            dimensions=dims,
            overall_threshold=8.0,
            summary="Good but needs improvement"
        )
        
        report.save(report_path)
        loaded = ValidationReport.load(report_path)
        
        assert loaded.overall_score == report.overall_score
        assert loaded.passed == report.passed
        assert len(loaded.dimensions) == 1
        assert loaded.dimensions[0].name == "correctness"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/evals/validator/test_report.py -v
```
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Create report.py implementation**

```python
# evals/validator/report.py
"""Validation Report parsing and generation."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ValidationDimension:
    """A single validation dimension with score and metadata."""
    name: str
    score: float
    weight: float
    threshold: float
    passed: bool = None
    skill: str = None
    breakdown: dict = field(default_factory=dict)
    reasoning: str = ""
    evidence: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    
    def __post_init__(self):
        """Calculate passed status if not provided."""
        if self.passed is None:
            self.passed = self.score >= self.threshold
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "threshold": self.threshold,
            "passed": self.passed,
            "skill": self.skill,
            "breakdown": self.breakdown,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "suggestions": self.suggestions,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ValidationDimension":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            score=data["score"],
            weight=data["weight"],
            threshold=data["threshold"],
            passed=data.get("passed"),
            skill=data.get("skill"),
            breakdown=data.get("breakdown", {}),
            reasoning=data.get("reasoning", ""),
            evidence=data.get("evidence", []),
            suggestions=data.get("suggestions", []),
        )


@dataclass
class ValidationReport:
    """Complete validation report with all dimensions."""
    version: str = "1.0"
    timestamp: str = field(default_factory=lambda: __import__('time').strftime("%Y-%m-%dT%H:%M:%SZ"))
    evaluator_focus: list = field(default_factory=list)
    skills_used: list = field(default_factory=list)
    dimensions: list = field(default_factory=list)
    overall_threshold: float = 8.0
    summary: str = ""
    telemetry: dict = field(default_factory=dict)
    
    @property
    def overall_score(self) -> float:
        """Calculate weighted overall score."""
        if not self.dimensions:
            return 0.0
        
        total_weight = sum(d.weight for d in self.dimensions)
        if total_weight == 0:
            return 0.0
        
        # Warn if weights don't sum to 1.0, then normalize
        if abs(total_weight - 1.0) > 0.001:
            import warnings
            warnings.warn(f"Weights sum to {total_weight:.3f}, normalizing to 1.0")
        
        # Normalize weights
        weighted_sum = sum(d.score * (d.weight / total_weight) for d in self.dimensions)
        return round(weighted_sum, 2)
    
    @property
    def passed(self) -> bool:
        """Check if overall validation passed."""
        return self.overall_score >= self.overall_threshold
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "evaluator_focus": self.evaluator_focus,
            "skills_used": self.skills_used,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "overall_score": self.overall_score,
            "overall_threshold": self.overall_threshold,
            "passed": self.passed,
            "summary": self.summary,
            "telemetry": self.telemetry,
        }
    
    def save(self, path: Path) -> None:
        """Save report to JSON file."""
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    @classmethod
    def from_dict(cls, data: dict) -> "ValidationReport":
        """Create from dictionary."""
        dimensions = [ValidationDimension.from_dict(d) for d in data.get("dimensions", [])]
        return cls(
            version=data.get("version", "1.0"),
            timestamp=data.get("timestamp", ""),
            evaluator_focus=data.get("evaluator_focus", []),
            skills_used=data.get("skills_used", []),
            dimensions=dimensions,
            overall_threshold=data.get("overall_threshold", 8.0),
            summary=data.get("summary", ""),
            telemetry=data.get("telemetry", {}),
        )
    
    @classmethod
    def load(cls, path: Path) -> "ValidationReport":
        """Load report from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
    
    def to_assertions(self) -> list:
        """Convert report to assertion results format for runner integration."""
        assertions = []
        for dim in self.dimensions:
            assertions.append({
                "id": f"eval_{dim.name}",
                "text": f"{dim.name} validation (score: {dim.score}, threshold: {dim.threshold})",
                "passed": dim.passed,
                "evidence": f"{dim.reasoning[:80]}..." if len(dim.reasoning) > 80 else dim.reasoning,
            })
        
        # Add overall assertion
        assertions.append({
            "id": "eval_overall",
            "text": f"Overall validation (score: {self.overall_score}, threshold: {self.overall_threshold})",
            "passed": self.passed,
            "evidence": self.summary,
        })
        
        return assertions
```

- [ ] **Step 4: Update __init__.py exports**

```python
# evals/validator/__init__.py
"""Agent Eval Validator - Generator-Evaluator separation for evals."""

from .artifact import OutputArtifact, ArtifactBuilder
from .report import ValidationReport, ValidationDimension

__all__ = [
    "OutputArtifact", 
    "ArtifactBuilder",
    "ValidationReport",
    "ValidationDimension",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/evals/validator/test_report.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add evals/validator/report.py tests/evals/validator/test_report.py evals/validator/__init__.py
git commit -m "feat(eval): add ValidationReport for eval results

- ValidationDimension dataclass with score/threshold/pass logic
- ValidationReport with weighted overall score calculation
- Save/load to JSON format
- Convert to assertion format for runner integration
- Support for telemetry and summary"
```

---

## Task 3: Create Evaluator Agent Module

**Files:**
- Create: `evals/validator/evaluator_agent.py`
- Test: `tests/evals/validator/test_evaluator_agent.py`

- [ ] **Step 1: Write failing test for EvaluatorAgent runner**

```python
# tests/evals/validator/test_evaluator_agent.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from evals.validator.evaluator_agent import EvaluatorAgentRunner
from evals.validator.artifact import ArtifactBuilder

def test_evaluator_agent_runs_subprocess():
    """Test EvaluatorAgentRunner invokes subprocess correctly"""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_dir = Path(tmpdir) / "artifact"
        artifact_dir.mkdir()
        
        # Create minimal artifact
        (artifact_dir / "meta.json").write_text(json.dumps({"case_id": "test-001"}))
        (artifact_dir / "context.json").write_text(json.dumps({"prompt": "test"}))
        (artifact_dir / "output.json").write_text(json.dumps({"final_output": "done"}))
        (artifact_dir / "workspace").mkdir()
        
        runner = EvaluatorAgentRunner(
            artifact_dir=artifact_dir,
            focus=["correctness"],
            timeout=30
        )
        
        # Mock subprocess to avoid actual execution
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            runner.run()
            
            assert mock_run.called
            call_args = mock_run.call_args
            assert 'evals/validator/evaluator_agent.py' in str(call_args)

def test_evaluator_agent_validates_focus():
    """Test that invalid focus dimensions are rejected"""
    runner = EvaluatorAgentRunner(
        artifact_dir=Path("/tmp"),
        focus=["unknown_dimension"],
    )
    
    # Should warn but not fail - agent will handle unknown dimensions
    assert runner.focus == ["unknown_dimension"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/evals/validator/test_evaluator_agent.py -v
```
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Create evaluator_agent.py with runner and main**

```python
# evals/validator/evaluator_agent.py
"""Evaluator Agent for independent validation of Generator output."""

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from evals.validator.artifact import OutputArtifact
from evals.validator.report import ValidationReport, ValidationDimension


# Default mapping from dimension names to evaluator skills
# Note: Evaluator skills use 'eval-' prefix and are regular Bourbon skills
DEFAULT_DIMENSION_TO_SKILL = {
    "correctness": "eval-correctness",
    "quality": "eval-quality",
    "security": "eval-security",
}


@dataclass
class EvaluatorConfig:
    """Configuration for Evaluator Agent."""
    artifact_dir: Path
    focus: list[str]
    threshold: float  # Overall threshold
    timeout: int
    dimensions_config: dict  # Per-dimension config: {name: {weight, threshold}}
    dimension_to_skill: dict[str, str] = None
    
    def __post_init__(self):
        if self.dimension_to_skill is None:
            self.dimension_to_skill = DEFAULT_DIMENSION_TO_SKILL.copy()
        if self.dimensions_config is None:
            self.dimensions_config = {}
    
    def get_skill_for_dimension(self, dimension: str) -> Optional[str]:
        """Get the skill name for a dimension."""
        return self.dimension_to_skill.get(dimension)
    
    def get_dimension_config(self, dimension: str) -> dict:
        """Get configuration for a specific dimension."""
        return self.dimensions_config.get(dimension, {})


class EvaluatorAgentRunner:
    """Manages running Evaluator Agent as a subprocess."""
    
    def __init__(self, artifact_dir: Path, focus: list[str], 
                 threshold: float = 8.0, timeout: int = 60,
                 dimensions_config: dict = None):
        self.artifact_dir = artifact_dir
        self.focus = focus
        self.threshold = threshold
        self.timeout = timeout
        self.dimensions_config = dimensions_config or {}
    
    def run(self) -> Path:
        """Run evaluator agent in subprocess and return report path."""
        script_path = Path(__file__).resolve()
        
        # Create temporary config file to pass dimension configuration
        config_data = {
            "threshold": self.threshold,
            "dimensions": self.dimensions_config,
            "dimension_to_skill": DEFAULT_DIMENSION_TO_SKILL,
        }
        config_path = self.artifact_dir.parent / "evaluator_config.json"
        config_path.write_text(json.dumps(config_data), encoding="utf-8")
        
        cmd = [
            sys.executable,
            str(script_path),
            "--artifact-dir", str(self.artifact_dir),
            "--focus", json.dumps(self.focus),
            "--threshold", str(self.threshold),
            "--config", str(config_path),
        ]
        
        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                timeout=self.timeout,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"Evaluator agent failed: {result.stderr}")
            
            # Report is written to validation/report.json
            # Report is at workdir/validation/report.json
            report_path = self.artifact_dir.parent / "validation" / "report.json"
            if not report_path.exists():
                raise RuntimeError(f"Validation report not found at {report_path}")
            return report_path
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Evaluator agent timed out after {self.timeout}s")


def run_evaluator_agent(config: EvaluatorConfig) -> ValidationReport:
    """Main entry point for Evaluator Agent (runs inside subprocess).
    
    This function is called when the script is run as __main__.
    It loads the artifact, invokes evaluator skills, and generates report.
    """
    import time
    start_time = time.time()
    
    print(f"[EVALUATOR] Starting validation")
    print(f"[EVALUATOR] Focus dimensions: {config.focus}")
    
    # Load artifact
    artifact = OutputArtifact.load(config.artifact_dir)
    
    # Build dimensions
    dimensions = []
    skills_used = []
    
    for dim_name in config.focus:
        skill_name = config.get_skill_for_dimension(dim_name)
        
        if not skill_name:
            print(f"[EVALUATOR] Warning: No skill mapped for dimension '{dim_name}'")
            continue
        
        print(f"[EVALUATOR] Loading skill: {skill_name}...")
        skills_used.append(skill_name)
        
        # PHASE 1: Simulate skill invocation (returns placeholder scores)
        # PHASE 2: Will actually call skill() tool and parse results
        dimension = _simulate_skill_evaluation(
            skill_name=skill_name,
            artifact=artifact,
            dimension_name=dim_name,
            config=config
        )
        dimensions.append(dimension)
    
    # Calculate telemetry
    duration_ms = int((time.time() - start_time) * 1000)
    telemetry = {
        "evaluator_version": "1.0.0",
        "duration_ms": duration_ms,
        "token_usage": {"input": 0, "output": 0}  # Phase 2: actual token tracking
    }
    
    # Create report
    report = ValidationReport(
        evaluator_focus=config.focus,
        skills_used=skills_used,
        dimensions=dimensions,
        overall_threshold=config.threshold,
        summary=_generate_summary(dimensions, config.threshold),
        telemetry=telemetry
    )
    
    # Save report
    validation_dir = config.artifact_dir.parent / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    report_path = validation_dir / "report.json"
    report.save(report_path)
    
    print(f"[EVALUATOR] Overall: score={report.overall_score}, threshold={config.threshold}, passed={report.passed}")
    print(f"[EVALUATOR] Validation completed: {report_path}")
    
    return report


def _simulate_skill_evaluation(skill_name: str, artifact: OutputArtifact, 
                                dimension_name: str, config: EvaluatorConfig) -> ValidationDimension:
    """Simulate skill evaluation (Phase 1 placeholder).
    
    WARNING: This is a PHASE 1 SIMULATION. It returns placeholder scores
    for testing the infrastructure. Phase 2 will implement actual skill
    invocation via Bourbon Agent framework.
    
    Phase 2 Implementation Plan:
    1. Create Bourbon Agent instance
    2. Load skill via agent.skills.activate(skill_name)
    3. Pass artifact data to skill via context
    4. Parse skill output (expected to be JSON with evaluation results)
    5. Convert to ValidationDimension
    """
    # Get dimension-specific configuration
    dim_config = config.get_dimension_config(dimension_name)
    weight = dim_config.get("weight", 1.0 / len(config.focus))
    threshold = dim_config.get("threshold", config.threshold)
    
    # PHASE 1: Placeholder score for infrastructure testing
    # This does NOT perform actual evaluation - it just returns a fixed score
    # to verify the validation pipeline works end-to-end
    placeholder_score = 8.5
    
    return ValidationDimension(
        name=dimension_name,
        score=placeholder_score,
        weight=weight,
        threshold=threshold,
        skill=skill_name,
        passed=placeholder_score >= threshold,
        reasoning="PHASE 1 SIMULATION: This is a placeholder score. "
                  "Actual evaluation will be implemented in Phase 2.",
        evidence=["Simulated: artifact loaded successfully", 
                  f"Config: weight={weight}, threshold={threshold}"],
        suggestions=["Phase 2: Implement actual skill invocation via Bourbon Agent"]
    )


def _generate_summary(dimensions: list, threshold: float) -> str:
    """Generate summary text from dimensions."""
    passed = sum(1 for d in dimensions if d.passed)
    total = len(dimensions)
    return f"{passed}/{total} dimensions passed (threshold: {threshold})"


def main():
    """CLI entry point for Evaluator Agent subprocess."""
    parser = argparse.ArgumentParser(description="Evaluator Agent")
    parser.add_argument("--artifact-dir", required=True, help="Path to artifact directory")
    parser.add_argument("--focus", required=True, help="JSON list of focus dimensions")
    parser.add_argument("--threshold", type=float, default=8.0, help="Overall threshold")
    parser.add_argument("--config", help="Optional config file path")
    args = parser.parse_args()
    
    # Parse focus
    focus = json.loads(args.focus)
    
    # Load config if provided
    dimension_to_skill = DEFAULT_DIMENSION_TO_SKILL.copy()
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            config_data = json.loads(config_path.read_text())
            dimension_to_skill.update(config_data.get("dimension_to_skill", {}))
    
    # Create config
    config = EvaluatorConfig(
        artifact_dir=Path(args.artifact_dir),
        focus=focus,
        threshold=args.threshold,
        timeout=300,  # Default timeout for agent itself
        dimension_to_skill=dimension_to_skill
    )
    
    # Run evaluation
    try:
        report = run_evaluator_agent(config)
        sys.exit(0 if report.passed else 1)
    except Exception as e:
        print(f"[EVALUATOR] Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Update __init__.py exports**

```python
# evals/validator/__init__.py
"""Agent Eval Validator - Generator-Evaluator separation for evals."""

from .artifact import OutputArtifact, ArtifactBuilder
from .report import ValidationReport, ValidationDimension
from .evaluator_agent import EvaluatorAgentRunner, EvaluatorConfig, run_evaluator_agent

__all__ = [
    "OutputArtifact", 
    "ArtifactBuilder",
    "ValidationReport",
    "ValidationDimension",
    "EvaluatorAgentRunner",
    "EvaluatorConfig",
    "run_evaluator_agent",
]
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/evals/validator/test_evaluator_agent.py -v
```
Expected: PASS

- [ ] **Step 6: Add integration test for full flow**

```python
# tests/evals/validator/test_evaluator_agent.py (add)

def test_full_evaluator_flow():
    """Test complete flow: artifact -> evaluator -> report"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir) / "work"
        workdir.mkdir()
        (workdir / "main.py").write_text("print('hello')")
        
        # Build artifact
        builder = ArtifactBuilder(case_id="integration-001", workdir=workdir)
        builder.set_meta(duration_ms=1000)
        builder.set_context(prompt="test prompt")
        builder.set_output(final_output="test output")
        artifact_dir = builder.build()
        
        # Run evaluator
        runner = EvaluatorAgentRunner(
            artifact_dir=artifact_dir,
            focus=["correctness"],
            threshold=8.0,
            timeout=30
        )
        
        report_path = runner.run()
        
        # Verify report was created
        assert report_path.exists()
        report = ValidationReport.load(report_path)
        assert report.evaluator_focus == ["correctness"]
        assert len(report.dimensions) == 1
        assert report.dimensions[0].name == "correctness"
```

- [ ] **Step 7: Run all tests**

```bash
pytest tests/evals/validator/test_evaluator_agent.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add evals/validator/evaluator_agent.py tests/evals/validator/test_evaluator_agent.py
git commit -m "feat(eval): add EvaluatorAgent subprocess runner

- EvaluatorAgentRunner for managing evaluator subprocess
- EvaluatorConfig for dimension-to-skill mapping
- Subprocess isolation for Generator-Evaluator separation
- Placeholder skill evaluation (Phase 2: real skill invocation)
- CLI interface for subprocess entry point"
```

---

## Task 4: Integrate with Eval Runner

**Files:**
- Modify: `evals/runner.py`

- [ ] **Step 1: Read current runner implementation**

View the `run_single` method in `evals/runner.py` (around line 344-416) to understand the existing structure.

- [ ] **Step 2: Modify run_single to support validation**

Add imports at top of file:
```python
# evals/runner.py (add to imports)
from evals.validator import ArtifactBuilder, EvaluatorAgentRunner, ValidationReport
```

Modify run_single method:
```python
# evals/runner.py - modify run_single method (around line 344)

def run_single(self, case: dict, run_number: int = 1) -> EvalResult:
    """执行单次运行（含可选的独立验证）"""
    workdir = None
    original_cwd = Path.cwd()
    start = time.time()
    validation_result = None
    
    try:
        workdir = self._setup_workspace(case)
        import os
        os.chdir(workdir)
        
        bourbon_config = self._load_bourbon_config()
        agent = Agent(config=bourbon_config, workdir=workdir)
        agent.reset_token_usage()

        # Redirect audit log to workdir so _execute_assertions can read it.
        if agent.audit.enabled:
            audit_log_path = workdir / "audit.jsonl"
            audit_log_path.touch(exist_ok=True)
            agent.audit.log_file = audit_log_path
        
        # 根据测试用例决定是否启用 skills
        required_skill = case.get("skill")
        if required_skill:
            try:
                agent.skills._discover()
                agent.skills.activate(required_skill)
                print(f"      📚 Activated skill: {required_skill}")
            except Exception as e:
                print(f"      ⚠️  Failed to activate skill '{required_skill}': {e}")
            agent.system_prompt = agent._build_system_prompt()
        else:
            agent.skills._skills = {}
            agent.system_prompt = agent._build_system_prompt()
        
        prompt = case.get("prompt", "")
        output = agent.step(prompt)
        
        duration = int((time.time() - start) * 1000)
        token_usage = agent.get_token_usage()
        
        # Execute traditional assertions
        assertion_results = self._execute_assertions(case, output, workdir)
        success = all(a["passed"] for a in assertion_results) if assertion_results else True
        
        # === NEW: Independent Validation ===
        evaluator_config = case.get("evaluator", {})
        if evaluator_config.get("enabled", False):
            print(f"      🔍 Running independent validation...")
            try:
                validation_result = self._run_validation(
                    case=case,
                    output=output,
                    workdir=workdir,
                    duration_ms=duration,
                    token_usage=token_usage
                )
                # Merge validation results
                success = success and validation_result["passed"]
                assertion_results.extend(validation_result["assertions"])
                print(f"      ✓ Validation complete: score={validation_result['score']:.1f}")
            except Exception as e:
                print(f"      ⚠️  Validation failed: {e}")
                # Validation failure marks test as failed (hard failure policy)
                success = False
                assertion_results.append({
                    "id": "eval_error",
                    "text": "Independent validation error",
                    "passed": False,
                    "evidence": str(e)[:100]
                })
        
        return EvalResult(
            case_id=case["id"],
            success=success,
            duration_ms=duration,
            token_usage=token_usage,
            assertions=assertion_results,
            output=output,
            run_number=run_number,
        )
        
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return EvalResult(
            case_id=case["id"],
            success=False,
            duration_ms=duration,
            error=str(e),
            run_number=run_number,
        )
    finally:
        import os
        os.chdir(original_cwd)
        # Optionally keep artifacts for debugging
        if workdir and not os.environ.get("EVAL_KEEP_ARTIFACTS"):
            self._cleanup_workspace(workdir)
```

- [ ] **Step 3: Add _run_validation helper method**

```python
# evals/runner.py - add new method to EvalRunner class

def _run_validation(self, case: dict, output: str, workdir: Path,
                    duration_ms: int, token_usage: dict) -> dict:
    """Run independent validation using Evaluator Agent.
    
    Returns dict with validation results for merging into test results.
    """
    evaluator_config = case.get("evaluator", {})
    
    # Build Output Artifact
    builder = ArtifactBuilder(
        case_id=case["id"],
        workdir=workdir,
        max_size_mb=self.config.get("evaluator", {}).get("max_artifact_size_mb", 100.0)
    )
    
    # Set metadata
    builder.set_meta(
        duration_ms=duration_ms,
        token_usage=token_usage,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    
    # Set context from case - enhanced with evaluation contract
    # Convert existing assertions into formal success criteria
    existing_assertions = case.get("assertions", [])
    formal_criteria = []
    for assertion in existing_assertions:
        check = assertion.get("check", "")
        desc = assertion.get("description", check)
        formal_criteria.append({
            "id": assertion.get("id", "unknown"),
            "description": desc,
            "check": check
        })
    
    builder.set_context(
        prompt=case.get("prompt", ""),
        success_criteria=evaluator_config.get("success_criteria", []),
        success_criteria_formal=formal_criteria,
        constraints=evaluator_config.get("constraints", []),
        evaluation_hints=evaluator_config.get("evaluation_hints", []),
        reference_files=evaluator_config.get("reference_files", [])
    )
    
    # Set output
    builder.set_output(
        final_output=output,
        exit_reason="completed"
    )
    
    # Build artifact
    artifact_dir = builder.build()
    
    # Run Evaluator Agent
    focus = evaluator_config.get("focus", ["correctness"])
    threshold = evaluator_config.get("threshold", 
        self.config.get("evaluator", {}).get("default_threshold", 8.0))
    timeout = evaluator_config.get("timeout", 
        self.config.get("evaluator", {}).get("default_timeout", 60))
    
    # Get per-dimension configuration
    dimensions_config = evaluator_config.get("dimensions", {})
    # Merge with global defaults
    global_dims = self.config.get("evaluator", {}).get("default_dimensions", {})
    for dim_name in focus:
        if dim_name not in dimensions_config and dim_name in global_dims:
            dimensions_config[dim_name] = global_dims[dim_name]
    
    runner = EvaluatorAgentRunner(
        artifact_dir=artifact_dir,
        focus=focus,
        threshold=threshold,
        timeout=timeout,
        dimensions_config=dimensions_config
    )
    
    report_path = runner.run()
    
    # Load and process report
    report = ValidationReport.load(report_path)
    
    # Convert to assertion format
    assertions = report.to_assertions()
    
    return {
        "passed": report.passed,
        "score": report.overall_score,
        "threshold": report.overall_threshold,
        "assertions": assertions,
        "report": report.to_dict()
    }
```

- [ ] **Step 4: Run existing tests to ensure no regression**

```bash
pytest tests/test_eval_runner.py -v -x
```
Expected: PASS (existing tests should not be affected)

- [ ] **Step 5: Create integration test with validation enabled**

```python
# tests/evals/test_validation_integration.py
import json
import tempfile
from pathlib import Path
from evals.runner import EvalRunner

def test_runner_with_validation():
    """Test that runner correctly invokes validation when enabled"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a simple test case with validation enabled
        cases_dir = Path(tmpdir) / "cases"
        cases_dir.mkdir()
        
        case = {
            "id": "validation-test-001",
            "name": "Test with validation",
            "category": "test",
            "prompt": "Write a function that returns 42",
            "evaluator": {
                "enabled": True,
                "focus": ["correctness"],
                "threshold": 7.0
            },
            "assertions": []
        }
        
        case_file = cases_dir / "test.json"
        case_file.write_text(json.dumps(case))
        
        # Create runner (uses default cases_dir)
        runner = EvalRunner()
        
        # Run single case directly (pass case dict, not file path)
        result = runner.run_single(case)
        
        # Verify validation ran
        # Check that validation assertions were added
        eval_assertions = [a for a in result.assertions if a["id"].startswith("eval_")]
        assert len(eval_assertions) >= 1  # At least overall assertion
```

- [ ] **Step 6: Run integration test**

```bash
pytest tests/evals/test_validation_integration.py -v -s
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add evals/runner.py tests/evals/test_validation_integration.py
git commit -m "feat(eval): integrate validation into EvalRunner

- Modify run_single() to support optional independent validation
- Add _run_validation() helper for artifact generation and evaluator invocation
- Merge validation results into test assertions
- Hard failure policy: validation error marks test as failed
- Support EVAL_KEEP_ARTIFACTS env var for debugging"
```

---

## Task 5: Create Evaluator Skills

**Files:**
- Create: `evals/validator/skills/eval-correctness/SKILL.md`
- Create: `evals/validator/skills/eval-quality/SKILL.md`

- [ ] **Step 0: Create skills directory**

```bash
mkdir -p evals/validator/skills/eval-correctness evals/validator/skills/eval-quality
```

- [ ] **Step 1: Create eval-correctness skill**

```markdown
---
name: eval-correctness
description: Evaluate whether the agent output correctly fulfills the task requirements
metadata:
  version: "1.0"
  author: bourbon
---

# Eval Correctness

**Evaluator Skill for Correctness Validation**

You are an evaluator assessing whether an AI agent's output correctly fulfills the given task.

## Input

You will receive:
1. **Task Context** (context.json): The original prompt and success criteria
2. **Agent Output** (output.json): The agent's final output and tool calls
3. **Workspace Files** (workspace/): The resulting file system state

## Evaluation Criteria

Score each dimension from 0-10:

1. **Functional Completeness** (0-10): Does the solution implement all required functionality?
   - 10: All requirements fully implemented
   - 7-9: Most requirements implemented, minor omissions
   - 4-6: Significant gaps in functionality
   - 0-3: Major requirements missing

2. **Behavioral Correctness** (0-10): Does the solution produce correct results?
   - 10: All behaviors correct for expected inputs
   - 7-9: Correct for typical cases, minor issues in edge cases
   - 4-6: Some incorrect behaviors or bugs
   - 0-3: Fundamentally incorrect

3. **Edge Case Handling** (0-10): Does the solution handle boundary conditions?
   - 10: Robust handling of all edge cases (empty inputs, nulls, limits)
   - 7-9: Handles common edge cases
   - 4-6: Some edge cases handled
   - 0-3: No edge case consideration

## Output Format

Return ONLY a JSON object:

```json
{
  "score": 8.5,
  "breakdown": {
    "functional_completeness": 9,
    "behavioral_correctness": 8,
    "edge_case_handling": 8
  },
  "reasoning": "Detailed explanation of the evaluation...",
  "evidence": [
    "Specific observation 1: e.g., 'Function handles null input correctly (line 15)'",
    "Specific observation 2: e.g., 'Missing validation for negative numbers'"
  ],
  "suggestions": [
    "Actionable improvement 1",
    "Actionable improvement 2"
  ]
}
```

## Guidelines

- Be objective: Base evaluation on evidence, not impressions
- Be specific: Reference actual file paths, line numbers, code snippets
- Be constructive: Every criticism should come with a suggestion
- Be calibrated: Reserve 9-10 for truly excellent work, 5 for mediocre, 0-2 for broken
```

- [ ] **Step 2: Create quality-evaluator skill**

Create file: `evals/validator/skills/quality-evaluator/SKILL.md`

```markdown
---
name: eval-quality
description: Evaluate code and response quality (clarity, maintainability, best practices)
metadata:
  version: "1.0"
  author: bourbon
---

# Eval Quality

**Evaluator Skill for Quality Validation**

You are an evaluator assessing the quality of an AI agent's code and responses.

## Input

You will receive:
1. **Task Context** (context.json): The original prompt
2. **Agent Output** (output.json): The agent's final output
3. **Workspace Files** (workspace/): The resulting code/files

## Evaluation Criteria

Score each dimension from 0-10:

1. **Code Clarity** (0-10): Is the code easy to understand?
   - 10: Crystal clear intent, excellent naming, natural flow
   - 7-9: Generally clear, minor confusion possible
   - 4-6: Some unclear sections, inconsistent naming
   - 0-3: Difficult to follow, poor naming

2. **Maintainability** (0-10): Is the code easy to modify?
   - 10: Well-structured, DRY, single responsibility
   - 7-9: Generally good structure, minor duplication
   - 4-6: Some spaghetti code, significant duplication
   - 0-3: Brittle, tightly coupled, hard to change

3. **Documentation** (0-10): Are there adequate comments and docs?
   - 10: Comprehensive docstrings, inline comments where needed
   - 7-9: Good docstrings, key sections documented
   - 4-6: Minimal documentation, missing key explanations
   - 0-3: No documentation, uncommented complex code

4. **Best Practices** (0-10): Does it follow language/framework conventions?
   - 10: Idiomatic, follows all relevant standards
   - 7-9: Mostly idiomatic, minor deviations
   - 4-6: Some unconventional choices
   - 0-3: Significant anti-patterns

## Output Format

Return ONLY a JSON object:

```json
{
  "score": 7.5,
  "breakdown": {
    "code_clarity": 8,
    "maintainability": 7,
    "documentation": 6,
    "best_practices": 8
  },
  "reasoning": "Detailed explanation...",
  "evidence": [
    "Observation with specific file/line reference",
    "Another observation"
  ],
  "suggestions": [
    "Specific improvement suggestion",
    "Another suggestion"
  ]
}
```

## Guidelines

- Focus on objective quality metrics over personal preference
- Reference specific code examples to support your evaluation
- Consider the task context - a simple task doesn't need over-engineering
- Balance "perfect" vs "good enough for purpose"
```

- [ ] **Step 3: Test skill loading**

```python
# Simple test to verify skills exist
from pathlib import Path
skills_dir = Path("evals/validator/skills")
skills = ["eval-correctness", "eval-quality"]
for skill in skills:
    path = skills_dir / skill / "SKILL.md"
    if path.exists():
        print(f"✓ {skill}")
    else:
        print(f"✗ {skill} - MISSING")
```

- [ ] **Step 4: Commit skill files**

```bash
git add evals/validator/skills/
git commit -m "feat(eval): add eval-correctness and eval-quality skills

- eval-correctness: assess functional completeness, behavioral correctness, edge cases
- eval-quality: assess code clarity, maintainability, documentation, best practices
- Both with structured JSON output format and detailed guidelines"
```

---

## Task 6: Update Config and Documentation

**Files:**
- Modify: `evals/config.toml`
- Modify: `evals/README.md`

- [ ] **Step 1: Update evals/config.toml**

```toml
# evals/config.toml additions

[evaluator]
enabled = false  # Default: disabled, enable per-case
default_threshold = 8.0
default_timeout = 60
max_artifact_size_mb = 100

[evaluator.exclude_patterns]
patterns = [".git/", "node_modules/", "__pycache__/", "*.pyc", ".venv/"]

[evaluator.default_dimensions]
correctness = { weight = 0.7, threshold = 8.0 }
quality = { weight = 0.3, threshold = 7.0 }

[evaluator.dimension_to_skill]
# Evaluator skills use 'eval-' prefix (e.g., eval-correctness, eval-quality)
correctness = "eval-correctness"
quality = "eval-quality"
```

- [ ] **Step 2: Update evals/README.md with validation docs**

Add section:
```markdown
## Independent Validation (New)

Bourbon Eval now supports independent validation using Generator-Evaluator separation.

### Enabling Validation

Add to your test case:
```json
{
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 8.0,
    "dimensions": {
      "correctness": { "weight": 0.6, "threshold": 9.0 },
      "quality": { "weight": 0.4, "threshold": 7.0 }
    }
  }
}
```

### How It Works

1. Runner executes test case as usual
2. Output Artifact is created (meta, context, output, workspace snapshot)
3. Evaluator Agent runs in separate subprocess
4. Evaluator loads specified skills and validates each dimension
5. Validation Report is generated with scores and suggestions
6. Report is merged into test results

### Available Dimensions

- `correctness`: Functional completeness, behavioral correctness
- `quality`: Code clarity, maintainability, documentation

### Debugging

Set environment variable to keep artifacts:
```bash
EVAL_KEEP_ARTIFACTS=1 python -m evals.runner
```

Artifacts will be preserved in the temp workdir for inspection.
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/evals/ -v --tb=short
```
Expected: All tests PASS

- [ ] **Step 4: Final commit**

```bash
git add evals/config.toml evals/README.md
git commit -m "docs(eval): add validation configuration and documentation

- Update config.toml with evaluator settings
- Document validation feature in README
- Include usage examples and debugging tips"
```

---

## Task 7: Setup Script for Skills Installation

**Files:**
- Create: `evals/validator/install_skills.py`

- [ ] **Step 1: Create skills installation script**

```python
# evals/validator/install_skills.py
"""Install built-in evaluator skills to user's skill directory."""

import shutil
from pathlib import Path


def install_skills():
    """Copy built-in evaluator skills to ~/.bourbon/skills/evaluators/."""
    builtin_dir = Path(__file__).parent / "skills"
    user_dir = Path.home() / ".bourbon" / "skills" / "evaluators"
    
    user_dir.mkdir(parents=True, exist_ok=True)
    
    for skill_dir in builtin_dir.iterdir():
        if skill_dir.is_dir():
            target = user_dir / skill_dir.name
            if target.exists():
                print(f"Skipping {skill_dir.name} (already exists)")
            else:
                shutil.copytree(skill_dir, target)
                print(f"Installed {skill_dir.name}")
    
    print(f"Skills installed to {user_dir}")


if __name__ == "__main__":
    install_skills()
```

- [ ] **Step 2: Test installation**

```bash
python evals/validator/install_skills.py
```
Expected output:
```
Installed correctness-evaluator
Installed quality-evaluator
Skills installed to /Users/.../.bourbon/skills/evaluators
```

- [ ] **Step 3: Commit**

```bash
git add evals/validator/install_skills.py
git commit -m "feat(eval): add skill installation script

- Script to copy built-in skills to user's skill directory
- Idempotent: skips existing skills
- Run once after setup or when skills are updated"
```

---

## Summary

This plan implements Phase 1 of the Agent Eval Validator:

1. **Artifact System** - Structured output for Generator-Evaluator handoff
2. **Report System** - Validation results with weighted scoring
3. **Evaluator Agent** - Subprocess-based independent validation
4. **Runner Integration** - Seamless integration with existing evals
5. **Evaluator Skills** - correctness-evaluator and quality-evaluator
6. **Configuration** - Per-case and global config options

All tasks include tests and follow TDD approach with frequent commits.
