# Community Benchmark Integration Design

**Date:** 2026-04-01  
**Status:** Draft  
**Goal:** Integrate community golden-set benchmarks into Bourbon's promptfoo eval pipeline to enable multi-dimensional regression detection across four capability dimensions.

---

## Problem Statement

Current eval cases are white-box tests — they test Bourbon's own skills and infrastructure (sandbox, file-ops, investment-agent skill). They cannot detect regressions in general agent capabilities caused by model changes, prompt changes, or architectural changes. We need an external golden set that covers general capabilities orthogonally.

---

## Design Principles

From `docs/deep-research-report.md`:
- Build layered gates: programmatic checks as hard gates, LLM judge as supplement
- Fix a stable subset for regression (not full benchmark) — ensures score changes reflect real capability changes, not sampling noise
- Keep `maxConcurrency: 1` to prevent context pollution between test runs
- Track `mean ± stddev` per category via promptfoo's `repeat: 3`

---

## Benchmark Selection

| Dimension | Benchmark | Size (subset) | Assertion type |
|-----------|-----------|---------------|----------------|
| A — Code correctness | HumanEval | 50 tasks | `javascript` (unit test via temp file) |
| B — Tool use | GAIA Level 1 | 30 tasks (see feasibility note) | `javascript` (answer string match) |
| C — Instruction following | MT-Bench | 80 tasks (full) | `llm-rubric` (LLM judge, score 1-10) |
| D1 — Arithmetic reasoning | GSM8K | 50 tasks | `javascript` (#### delimiter extraction) |
| D2 — Logical reasoning | BIG-bench Hard | 100 tasks | `javascript` (JSON-parsed answer match) |

Total: 310 tasks per full benchmark run.

---

## Directory Structure

```
evals/
├── cases/                          # Existing project evals (unchanged)
│   ├── skills.yaml
│   ├── sandbox.yaml
│   └── ...
│
├── benchmarks/                     # NEW: committed static subsets
│   ├── humaneval_50.yaml
│   ├── gaia_level1_30.yaml
│   ├── mt_bench_80.yaml
│   ├── gsm8k_50.yaml
│   └── bigbench_hard_100.yaml
│
└── loaders/                        # NEW: HuggingFace → YAML conversion scripts
    ├── load_humaneval.py            # openai/openai-humaneval on HF
    ├── load_gaia.py                 # gaia-benchmark/GAIA on HF (requires access approval)
    ├── load_mt_bench.py             # lm-sys/mt_bench_human_judgments on HF
    ├── load_gsm8k.py                # openai/gsm8k on HF
    └── load_bigbench_hard.py        # lighteval/big_bench_hard on HF

promptfooconfig.yaml                # Existing (unchanged): project evals
promptfooconfig-benchmarks.yaml     # NEW: community benchmark entry point
```

---

## Configuration: `promptfooconfig-benchmarks.yaml`

```yaml
description: "Bourbon Agent — Community Benchmark Evaluation"

providers:
  - id: python:evals/promptfoo_provider.py
    label: bourbon-agent
    config:
      pythonExecutable: .venv/bin/python

prompts:
  - "{{prompt}}"

defaultTest:
  provider: python:evals/promptfoo_provider.py

evaluateOptions:
  maxConcurrency: 1
  repeat: 3
  timeoutMs: 180000    # Per-test timeout (not total budget for repeat:3).
                       # Each of the 3 repeat runs gets 180s independently.
                       # 180s covers slow agent inference (~60s) + subprocess execution overhead.

tests:
  - file://evals/benchmarks/humaneval_50.yaml
  - file://evals/benchmarks/gaia_level1_30.yaml
  - file://evals/benchmarks/mt_bench_80.yaml
  - file://evals/benchmarks/gsm8k_50.yaml
  - file://evals/benchmarks/bigbench_hard_100.yaml
```

---

## Output Contract

The existing provider (`evals/promptfoo_provider.py`) returns a JSON-encoded string:
```json
{"text": "<agent response>", "workdir": "<path>"}
```

All `javascript` assertions must parse this envelope first:
```js
const data = JSON.parse(output);
const text = data.text;
```

The `contains` assertion type is **not used** for any benchmark — it would substring-match against the raw JSON string and produce false positives. All option-letter matching uses `javascript` assertions with explicit JSON parsing.

---

## Assertion Strategies by Dimension

### A — HumanEval (Code Correctness)

**Source:** `openai/openai-humaneval` on HuggingFace (MIT license, no access gate).

Input: function signature + docstring. Agent completes the function body.  
Assertion: `javascript` — writes generated code + test vectors to a temp file and invokes `python3` on it. Avoids shell injection risks of the `-c` flag with multi-line code.

```yaml
- description: "HumanEval #42: sum_squares"
  vars:
    prompt: |
      Complete the following Python function. Return ONLY the completed
      function, no explanation:

      def sum_squares(lst):
          """Round each element in lst to ceiling, return sum of squares."""
          pass
    test_code: |
      import math
      assert sum_squares([1,2,3]) == 14
      assert sum_squares([1.4,4.2,0]) == 29
      assert sum_squares([-2.4,1,1]) == 6
  assert:
    - type: javascript
      value: |
        const { spawnSync } = require('child_process');
        const os = require('os');
        const fs = require('fs');
        const path = require('path');
        const data = JSON.parse(output);
        const fn = data.text;
        const script = fn + "\n" + vars.test_code;
        const tmpFile = path.join(os.tmpdir(), `humaneval_${Date.now()}.py`);
        fs.writeFileSync(tmpFile, script);
        try {
          const result = spawnSync('python3', [tmpFile], { timeout: 10000 });
          fs.unlinkSync(tmpFile);
          if (result.status === 0) return true;
          return { pass: false, reason: result.stderr?.toString() };
        } catch (e) {
          fs.unlinkSync(tmpFile);
          return { pass: false, reason: e.message };
        }
  metadata:
    category: "benchmark-humaneval"
    task_id: "HumanEval/42"
```

**Note:** Python subprocess runs in the Node.js promptfoo worker process (outside Bourbon's sandbox). This is intentional — the sandbox is for agent tool execution, not for test harness code. The test vectors come from the committed YAML (trusted source), so the sandboxing trade-off is acceptable.

### B — GAIA Level 1 (Tool Use)

**Source:** `gaia-benchmark/GAIA` on HuggingFace.  
**Access:** Requires HuggingFace account approval via dataset form. Run `load_gaia.py` after approval; committed YAML requires no runtime HF access.

Input: factual question solvable via reasoning. Agent produces a final answer.  
Assertion: `javascript` — case-insensitive substring match after JSON parse.

**Subset filtering rules** (enforced by `load_gaia.py`):
- Exclude tasks with file attachments (images, audio, PDFs) — ~30% of Level 1
- Exclude tasks annotated as requiring live web search
- Estimate: ~60-80 tasks survive both filters from ~165 Level 1 total; 30 is achievable
- Sample balanced across difficulty tiers using the dataset's `level` metadata
- Fixed `seed=42`

```yaml
- description: "GAIA L1: WHO headquarters country capital"
  vars:
    prompt: "What is the capital of the country that hosts the WHO headquarters?"
    expected_answer: "Bern"
  assert:
    - type: javascript
      value: |
        const data = JSON.parse(output);
        const text = data.text.toLowerCase();
        return text.includes(vars.expected_answer.toLowerCase());
  metadata:
    category: "benchmark-gaia"
    level: 1
    task_id: "gaia-l1-012"
```

**Feasibility note:** If `load_gaia.py` finds fewer than 30 tasks after filtering, it always writes to the fixed filename `gaia_level1_30.yaml` (so `promptfooconfig-benchmarks.yaml` never needs updating), but logs a warning and records the actual task count in the YAML header comment and in `BASELINES.md`. Estimated viable pool: 60-80 tasks after both exclusions; 30 is achievable.

### C — MT-Bench (Instruction Following, LLM Judge)

**Source:** Questions from `lm-sys/mt_bench_human_judgments` on HuggingFace (Apache 2.0).  
The dataset contains the original 80 questions in the `question` column; `load_mt_bench.py` extracts first-turn questions only.

Full 80 tasks, 8 categories × 10 tasks each. Single-turn (first question only).  
Assertion: `llm-rubric` with score 1-10, threshold 7.  
`llm-rubric` receives the raw provider output (JSON string); the LLM judge can parse the `text` field naturally.

```yaml
- description: "MT-Bench coding #1: quicksort"
  vars:
    prompt: |
      Implement QuickSort in Python and explain the time complexity
      in best, average, and worst cases.
  assert:
    - type: llm-rubric
      metric: "mt_bench_score"
      value: |
        The output below is a JSON object. Extract the "text" field and evaluate
        the agent's response on a scale of 1 to 10.

        Scoring criteria:
        - 9-10: Correct implementation, edge cases handled, accurate O(n log n) avg
          and O(n²) worst-case complexity explained clearly
        - 7-8: Correct with minor gaps in explanation or edge case handling
        - 5-6: Mostly correct with notable omissions
        - 1-4: Significantly wrong implementation or analysis

        Respond with only a single integer.
      threshold: 7
  metadata:
    category: "benchmark-mt-bench"
    subcategory: "coding"
```

**Category distribution:**

| Category | Tasks | What it tests |
|----------|-------|---------------|
| coding | 10 | Code generation + explanation (complements HumanEval) |
| math | 10 | Step-by-step derivation (complements GSM8K) |
| reasoning | 10 | Logic and inference (complements BIG-bench Hard) |
| writing | 10 | Output quality and coherence |
| roleplay | 10 | Instruction adherence in creative context |
| extraction | 10 | Structured output from unstructured input |
| stem | 10 | Domain knowledge accuracy |
| humanities | 10 | Open-ended analytical quality |

### D1 — GSM8K (Arithmetic Reasoning)

**Source:** `openai/gsm8k` on HuggingFace (MIT license).

Input: grade-school math word problem. Prompt instructs agent to end answer with `#### <number>`.  
Assertion: `javascript` — extracts number after `####` delimiter (standard GSM8K convention).

**Subset sampling:** 50 problems stratified by solution step count (1-3 / 4-6 / 7+ steps, ~17 each), `seed=42`. Step count estimated from answer string length in the dataset.

```yaml
- description: "GSM8K #128: duck eggs"
  vars:
    prompt: |
      Solve this math problem step by step. End your answer with
      "#### <number>" on its own line (the number only, no units).

      Janet's ducks lay 16 eggs per day. She eats 3 for breakfast and
      bakes 4 into muffins. She sells the rest for $2 each. How much
      does she make per day?
    expected_answer: "18"
  assert:
    - type: javascript
      value: |
        const data = JSON.parse(output);
        const match = data.text.match(/####\s*(\d+\.?\d*)/);
        const extracted = match ? match[1] : null;
        return extracted === vars.expected_answer;
  metadata:
    category: "benchmark-gsm8k"
    difficulty: "easy"
```

### D2 — BIG-bench Hard (Logical Reasoning)

**Source:** `lighteval/big_bench_hard` on HuggingFace (Apache 2.0).

100 tasks across 10 sub-tasks, 10 tasks each.  
Assertion: `javascript` with JSON parse — matches `Answer: (X)` on its own line to avoid false positives from option letters appearing in the quoted question text.

**Selected sub-tasks:**
```
causal_judgement, date_understanding, formal_fallacies,
geometric_shapes, hyperbaton, logical_deduction_five_objects,
movie_recommendation, navigate, reasoning_about_colored_objects, snarks
```

```yaml
- description: "BBH causal_judgement #3"
  vars:
    prompt: |
      How would a typical person answer this question about causation?
      "The surgery was successful, but the patient died. Did the doctor
      cause the patient's death?"
      Options: (A) Yes (B) No

      End your response with "Answer: (X)" on its own line.
    expected_option: "(B)"
  assert:
    - type: javascript
      value: |
        const data = JSON.parse(output);
        // Match "Answer: (X)" on its own line to avoid false positives
        // from option letters appearing in the quoted question
        const match = data.text.match(/^Answer:\s*(\([A-Z]\))\s*$/m);
        return match ? match[1] === vars.expected_option : false;
  metadata:
    category: "benchmark-bigbench-hard"
    subcategory: "causal_judgement"
```

---

## Regression Thresholds

Each dimension has a minimum pass rate that constitutes a regression signal. These are initial baselines to be calibrated after the first full run:

| Dimension | Benchmark | Initial threshold | Notes |
|-----------|-----------|-------------------|-------|
| A | HumanEval | pass@1 ≥ 60% | Typical for capable models; raise after baseline established |
| B | GAIA L1 | pass@1 ≥ 40% | GAIA is hard; 40% is realistic for filtered text-only subset |
| C | MT-Bench | mean score ≥ 7.0 | promptfoo `threshold: 7` per assertion handles this |
| D1 | GSM8K | pass@1 ≥ 75% | Standard baseline for capable models |
| D2 | BIG-bench Hard | pass@1 ≥ 55% | Human baseline ~65%; 55% gives headroom |

A drop of ≥5 percentage points vs. the previous committed baseline on any single dimension is treated as a regression and should block model/prompt upgrades. Baselines are updated in `evals/benchmarks/BASELINES.md` after each intentional upgrade.

`BASELINES.md` format:
```markdown
# Benchmark Baselines

| Benchmark | Dimension | Pass Rate | Mean Score | Date | Git Commit | Notes |
|-----------|-----------|-----------|------------|------|------------|-------|
| HumanEval | A | 64% | — | 2026-04-15 | abc1234 | Initial baseline |
| GAIA L1   | B | 43% | — | 2026-04-15 | abc1234 | 28 tasks (pool < 30) |
| MT-Bench  | C | —  | 7.4 | 2026-04-15 | abc1234 | Initial baseline |
| GSM8K     | D1 | 78% | — | 2026-04-15 | abc1234 | Initial baseline |
| BBH       | D2 | 57% | — | 2026-04-15 | abc1234 | Initial baseline |
```

---

## Loader Scripts Interface

All loaders share a consistent CLI and output a YAML file with embedded `# Generated by:` comment for audit trail:

```bash
# Install loader dependencies (separate from [dev] extras — large HF dependency tree)
pip install datasets pyyaml   # one-time, outside project venv

# Generate/refresh committed static subsets
python evals/loaders/load_humaneval.py --sample 50 --seed 42 \
    --output evals/benchmarks/humaneval_50.yaml

python evals/loaders/load_gaia.py --sample 30 --seed 42 \
    --exclude-attachments --exclude-web \
    --output evals/benchmarks/gaia_level1_30.yaml
# Note: requires `huggingface-cli login` and dataset access approval first

python evals/loaders/load_mt_bench.py \
    --output evals/benchmarks/mt_bench_80.yaml

python evals/loaders/load_gsm8k.py --sample 50 --seed 42 \
    --stratify-by-steps \
    --output evals/benchmarks/gsm8k_50.yaml

python evals/loaders/load_bigbench_hard.py \
    --tasks causal_judgement date_understanding formal_fallacies \
            geometric_shapes hyperbaton logical_deduction_five_objects \
            movie_recommendation navigate reasoning_about_colored_objects snarks \
    --per-task 10 --seed 42 \
    --output evals/benchmarks/bigbench_hard_100.yaml
```

**Dependency isolation:** `datasets` and `pyyaml` are **not** added to `pyproject.toml` extras. They are one-shot loader dependencies installed manually before refreshing subsets. This avoids polluting the project's dev environment with HuggingFace's large dependency tree (~hundreds of MB).

Each generated YAML file includes a header comment:
```yaml
# Generated by: python evals/loaders/load_humaneval.py --sample 50 --seed 42
# Dataset: openai/openai-humaneval, revision: <commit hash>
# Generated at: 2026-04-01
```

---

## Usage Workflow

```bash
# Day-to-day: project evals only (fast)
npx promptfoo@latest eval

# Before/after model upgrade or major refactor: run benchmarks
npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml

# Run a single dimension
npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml \
    --filter-pattern "benchmark-mt-bench"

# Refresh static subset from HuggingFace (when intentionally updating baseline)
pip install datasets pyyaml
python evals/loaders/load_humaneval.py --sample 50 --seed 42 \
    --output evals/benchmarks/humaneval_50.yaml
# Update evals/benchmarks/BASELINES.md with new baseline numbers
git add evals/benchmarks/humaneval_50.yaml evals/benchmarks/BASELINES.md
git commit -m "chore(evals): refresh humaneval subset"
```

---

## Out of Scope

- **SWE-bench:** requires Docker + real repo cloning per task. Deferred. Unblocked when Docker sandbox provider reaches production stability.
- **τ-bench:** requires mock service environment (retail/airline domain simulation). Deferred.
- **IFEval:** replaced by MT-Bench. LLM judge covers instruction-following quality more comprehensively than programmatic constraint checks.
- **Multi-turn MT-Bench:** only first turn used to keep eval scope contained and avoid compounding failures across turns.
- **GAIA with attachments:** multi-modal tasks excluded from subset (Bourbon has no vision capability).
