# Bourbon Eval Guide

Bourbon's evaluation framework runs through [promptfoo](https://www.promptfoo.dev/).

## Architecture

```
promptfooconfig.yaml          # Entrypoint
       ↓
evals/promptfoo_provider.py   # Wraps Agent.step() for promptfoo
       ↓
evals/cases/*.yaml            # Test case definitions
       ↓
promptfoo assertions          # javascript, llm-rubric, contains, etc.
```

### Components

- **`promptfooconfig.yaml`** - Root config. Defines provider, default options, and test file references.
- **`evals/promptfoo_provider.py`** - Custom Python provider that runs `Agent.step()` and returns JSON `{text, workdir, duration}`.
- **`evals/promptfoo_artifact_provider.py`** - Serves pre-built calibration artifacts for `llm-rubric` evaluation.
- **`evals/cases/`** - YAML test case files organized by category.
- **`evals/fixtures/`** - Pre-built test fixtures (calibration artifacts, project templates).

## Quick Start

```bash
# Run all evaluations
npx promptfoo@latest eval

# Filter by category description
npx promptfoo@latest eval --filter-pattern "Skills"

# Run with multiple iterations for variance analysis
npx promptfoo@latest eval --repeat 5

# Disable cache for fresh runs
npx promptfoo@latest eval --no-cache

# Open dashboard to view results
npx promptfoo@latest view
```

## Test Categories

| Category | File | Description |
|----------|------|-------------|
| Calibration | `calibration.yaml` | Multi-dimensional scoring with pre-built artifacts |
| Safety | `safety.yaml` | Red team tests for safety guardrails |
| Security | `security.yaml` | Security behavior validation |
| Sandbox | `sandbox.yaml` | Sandbox isolation tests |
| Skills | `skills.yaml` | Skill functionality and trigger accuracy |
| Code Search | `code-search.yaml` | Code search result quality |
| File Operations | `file-operations.yaml` | File operation correctness |
| General | `general.yaml` | General agent behavior |
| Validator Smoke | `validator-smoke.yaml` | Validator smoke tests |

## Assertion Types

### Programmatic (javascript)

File and audit assertions parse the provider's JSON output to access `workdir`, then check filesystem state:

```yaml
assert:
  - type: javascript
    value: |
      const output = JSON.parse(output);
      const fs = require('fs');
      const path = require('path');
      const filePath = path.join(output.workdir, 'expected-file.py');
      return fs.existsSync(filePath);
```

### LLM Judge (llm-rubric)

Subjective evaluation of output quality:

```yaml
assert:
  - type: llm-rubric
    value: "The response correctly identifies the bug and explains why it occurs"
```

### Text Matching

Simple substring checks on the raw JSON output:

```yaml
assert:
  - type: contains
    value: "expected text"
  - type: not-contains
    value: "should not appear"
```

## Calibration Cases

Calibration uses pre-built artifacts (in `evals/fixtures/`) evaluated by `llm-rubric` with multi-dimensional scoring. Each dimension gets a separate metric:

```yaml
assert:
  - type: llm-rubric
    value: "Evaluate correctness of the implementation..."
    metric: correctness
  - type: javascript
    value: |
      const scores = context.namedScores;
      return scores.correctness >= 0.6 && scores.correctness <= 0.9;
```

## Provider Output Contract

The agent provider returns JSON-encoded output:

```json
{
  "text": "Agent's text response...",
  "workdir": "/tmp/eval-workspace-xxx",
  "duration": 12.5
}
```

- `javascript` assertions parse this JSON to access `workdir` and filesystem
- `contains`/`not-contains` assertions match against the raw JSON string
- `llm-rubric` assertions receive the raw JSON; the LLM extracts the text field

## Configuration Options

In `promptfooconfig.yaml`:

```yaml
evaluateOptions:
  maxConcurrency: 1    # Serial for workspace isolation
  repeat: 3            # Default iterations per case
  timeoutMs: 60000     # Per-case timeout
```

## Fixtures

Pre-built fixtures in `evals/fixtures/`:

| Fixture | Purpose |
|---------|---------|
| `calibration-below-zero-*` | Pre-built below_zero implementations (gold/buggy/messy) |
| `calibration-logic-puzzle-*` | Pre-built logic puzzle solutions (gold/buggy/messy) |
| `python-project` | Template Python project for file operation tests |
| `js-project` | Template JS project for file operation tests |
| `malicious` | Malicious fixtures for security tests |
