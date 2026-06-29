# Flywheel Lean Eval Loop

Flywheel is a small eval loop for Bourbon:

1. Sample real traces into a Langfuse error-analysis pool.
2. Manually annotate and promote representative cases in Langfuse.
3. Run Bourbon on the `regression` split for baseline and candidate harnesses.
4. Score frozen judge cases and regression run outputs with one verified judge.
5. Write JSON and Markdown reports for the read-only API and UI.

## Install

```bash
cd flywheel
uv pip install -e ".[dev]"
```

## Dataset Item Shape

The scripts can read Langfuse datasets or a local JSON mirror for smoke runs:

```json
{
  "items": [
    {
      "id": "case_001",
      "split": "judge_train",
      "input": "user input",
      "expected": "acceptance criteria",
      "output": "frozen annotated output for judge splits",
      "human_label": "pass",
      "metadata": {
        "failure_label": "tool_misuse",
        "critique": "why the human label applies",
        "trace_url": "https://langfuse.example/project/traces/..."
      }
    }
  ]
}
```

Valid splits are `judge_train`, `judge_dev`, `judge_test`, and `regression`.
Judge splits require frozen `output` plus binary `human_label`. Regression items
do not store frozen output; their outputs come from `run_harness.py`. Every
regression item should carry a curated `failure_label` from `labels.md`.

## Real Smoke Path

```bash
python scripts/sample_traces.py --project bourbon --dataset bourbon-error-pool --limit 30
```

Then manually annotate the sampled traces in Langfuse, cluster comments into
`labels.md`, and promote representative cases into the Langfuse dataset with
`input`, `expected`, `failure_label`, and a split label. Freeze annotated output
and `human_label` on judge items only.

```bash
python scripts/run_harness.py --project bourbon --dataset bourbon-flywheel \
  --model claude-sonnet-4-6 --git-sha "$(git -C .. rev-parse origin/main)" \
  --run-id baseline-main-$(date -u +%Y%m%dT%H%M%SZ)

python scripts/run_harness.py --project bourbon --dataset bourbon-flywheel \
  --model claude-sonnet-4-6 --git-sha "$(git -C .. rev-parse HEAD)" \
  --run-id candidate-pr-$(date -u +%Y%m%dT%H%M%SZ)

python scripts/run_judge.py --project bourbon --dataset bourbon-flywheel \
  --split judge_test --judge-version judge-v1 --model claude-opus-4-8 --prompt-version p1

python scripts/run_judge.py --project bourbon --dataset bourbon-flywheel \
  --split regression --run baseline-main-YYYYMMDDTHHMMSSZ \
  --judge-version judge-v1 --model claude-opus-4-8 --prompt-version p1

python scripts/run_judge.py --project bourbon --dataset bourbon-flywheel \
  --split regression --run candidate-pr-YYYYMMDDTHHMMSSZ \
  --judge-version judge-v1 --model claude-opus-4-8 --prompt-version p1

python scripts/validate_judge.py --project bourbon --dataset bourbon-flywheel

python scripts/run_regression.py --project bourbon --dataset bourbon-flywheel \
  --baseline-run baseline-main-YYYYMMDDTHHMMSSZ \
  --candidate-run candidate-pr-YYYYMMDDTHHMMSSZ
```

`run_regression.py` refuses to compare when the judge report is missing, when
`passes` is false, when baseline and candidate carry mixed judge versions, when
repeat budgets differ, or when the regression split overlaps any judge split.

## Local Credential-Free Smoke

Use a local dataset JSON and canned judge responses to exercise the report path:

```bash
python scripts/run_harness.py --project bourbon --dataset-json /tmp/flywheel-dataset.json \
  --model local-smoke --git-sha baseline000 --run-id baseline-smoke \
  --output-template "baseline output for {case_id}" --trace-url-template "http://lf/{sample_id}"

python scripts/run_harness.py --project bourbon --dataset-json /tmp/flywheel-dataset.json \
  --model local-smoke --git-sha candidate0 --run-id candidate-smoke \
  --output-template "candidate output for {case_id}" --trace-url-template "http://lf/{sample_id}"

python scripts/run_judge.py --project bourbon --dataset-json /tmp/flywheel-dataset.json \
  --split judge_test --judge-version judge-v1 --model local --prompt-version p1 \
  --canned-labels-json /tmp/flywheel-canned-judge-test.json

python scripts/validate_judge.py --project bourbon --dataset-json /tmp/flywheel-dataset.json \
  --min-class-support 1
```

For regression smoke, run `run_judge.py --split regression --run baseline-smoke`
and `--run candidate-smoke` with canned responses, then run `run_regression.py`.

## UI and API

The read API is intentionally injected with a run provider:

```python
from pathlib import Path

from api.read_api import create_app
from api.runs_provider import list_runs
from scripts.common import create_langfuse_client

client = create_langfuse_client()
app = create_app(
    Path("~/.flywheel").expanduser(),
    project="bourbon",
    runs_provider=lambda project: list_runs(Path("~/.flywheel").expanduser(), project, langfuse=client),
)
```

Run the frontend during development:

```bash
cd ui
npm install
npm run dev
```
