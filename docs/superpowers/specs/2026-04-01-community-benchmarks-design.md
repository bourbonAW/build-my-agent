# Community Benchmark Integration Design

**Date:** 2026-04-01  
**Status:** Draft  
**Goal:** Integrate community golden-set benchmarks into Bourbon's promptfoo eval pipeline to enable multi-dimensional regression detection across four capability dimensions.

---

## Open TODOs

- [ ] **GAIA access gate:** Authenticate with HuggingFace, request access to `gaia-benchmark/GAIA`, run `evals/loaders/load_gaia.py`, replace the committed 0-task placeholder `evals/benchmarks/gaia_level1_30.yaml`, and re-run the hard gate check. Until this is done, Dimension B is not active and the integration is not complete.
- [ ] **Promptfoo javascript assertion compatibility:** Debug `promptfoo@latest` javascript assertion behavior against Bourbon's Python provider output. Current smoke verification reaches the provider and gets the expected JSON payload, but the javascript assertion still fails unexpectedly. Resolve this by either updating the assertion contract to match the current promptfoo runtime or pinning a known-good promptfoo version.
- [ ] **Post-fix pipeline verification:** After the GAIA and promptfoo assertion issues are resolved, re-run the smoke eval, run at least one real benchmark dimension end-to-end, and update `evals/benchmarks/BASELINES.md` with the first real baseline.

---

## Problem Statement

Current eval cases are white-box tests — they test Bourbon's own skills and infrastructure (sandbox, file-ops, investment-agent skill). They cannot detect regressions in general agent capabilities caused by model changes, prompt changes, or architectural changes. We need an external golden set that covers general capabilities orthogonally.

---

## Design Principles

From `docs/deep-research-report.md`:
- Build layered gates: programmatic checks as hard gates, LLM judge as supplement
- Fix a stable subset for regression (not full benchmark) — ensures score changes reflect real capability changes, not sampling noise
- Keep `maxConcurrency: 1` to prevent context pollution between test runs
- Use `repeat: 3` for run stability — tracks pass rate consistency across runs, not stddev

---

## Benchmark Selection

| Dimension | Benchmark | Size (subset) | Assertion type |
|-----------|-----------|---------------|----------------|
| A — Code correctness | HumanEval | 50 tasks | `llm-rubric` (sandbox execution + LLM judge) |
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

Input: function signature + docstring + test assertions. Agent writes the function **and** runs the tests via Bourbon's `bash` tool (inside sandbox). The raw bash output must appear verbatim in the response.

Assertion: `llm-rubric` — an independent LLM judge evaluates both the code and the execution output included in the response. This avoids the primary failure mode of executing untrusted model-generated code in the Node.js worker outside any sandbox.

**Why not `javascript` + `spawnSync`:** OpenAI's own HumanEval harness ships with execution disabled by default and warns: *"run untrusted code only inside a robust security sandbox."* `spawnSync` in the promptfoo Node.js worker has no isolation.

**Verification tradeoff:** The LLM judge receives only the `text` field from the provider — it cannot inspect tool call transcripts or audit logs to confirm that bash was actually invoked. The rubric is probabilistic: it rewards responses that contain verbatim-looking bash stdout/stderr and penalizes those that only describe results in prose. An agent that fabricates plausible-looking execution output could score highly without having run the code. This is an accepted limitation: the eval detects regressions in the agent's tool-use behavior at scale, not individual-case correctness with cryptographic certainty. A future improvement would be to surface the audit log from `workdir` as a `javascript` assertion alongside the `llm-rubric`.

```yaml
- description: "HumanEval HumanEval/42: sum_squares"
  vars:
    prompt: |
      Complete the following Python function, then run the provided test assertions
      using your bash tool. Include the COMPLETE raw bash output in your response —
      do not paraphrase or summarize the execution result.

      def sum_squares(lst):
          """Round each element in lst to ceiling, return sum of squares."""
          pass

      Test assertions to run (write to a file and execute with python3):
      import math
      assert sum_squares([1,2,3]) == 14
      assert sum_squares([1.4,4.2,0]) == 29
      assert sum_squares([-2.4,1,1]) == 6
      print("All tests passed")
  assert:
    - type: llm-rubric
      metric: "humaneval_execution"
      value: |
        The output is a JSON string. Extract the "text" field.
        The response should contain a Python function implementation AND
        the raw output from running test assertions via bash.

        Evaluate based on the ACTUAL execution output, not the agent's verbal summary:
        - 9-10: Function implemented AND bash output shows clean execution
          (no AssertionError, no Traceback, print confirms success)
        - 5-8: Function present but execution output is unclear or missing
        - 1-4: No bash execution output, or output shows AssertionError/Traceback

        Do NOT trust the agent's summary — look for the raw bash output.
        Respond with only a single integer.
      threshold: 8
  metadata:
    category: "benchmark-humaneval"
    task_id: "HumanEval/42"
```

### B — GAIA Level 1 (Tool Use)

**Source:** `gaia-benchmark/GAIA` on HuggingFace.  
**Access:** Requires HuggingFace account approval via dataset form. Run `load_gaia.py` after approval; committed YAML requires no runtime HF access.

> **Completion gate:** A 0-task placeholder YAML may be committed during development while access is pending, but Dimension B is not considered active until the file contains real tasks. The integration is not "complete" until this gate passes. See plan Step 2b for the hard check.

Input: factual question solvable via reasoning. Agent produces a final answer.  
Assertion: `javascript` — case-insensitive substring match after JSON parse.

**Subset filtering rules** (enforced by `load_gaia.py`):
- Load only Level 1 tasks (the dataset's `Level` field == 1; ~165 tasks in `validation` split)
- Exclude tasks with file attachments (images, audio, PDFs) — ~30% of Level 1
- Exclude tasks annotated as requiring live web search
- Estimate: ~60-80 tasks survive both filters; 30 is achievable
- Random sample from the filtered pool, `seed=42` — no stratification needed because all tasks are already restricted to a single difficulty level

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
# Install loader dependencies ([loaders] extra — separate from [dev] to avoid large HF dep tree)
uv pip install -e ".[loaders]"

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

**Dependency isolation:** `datasets`, `huggingface-hub`, and `pyyaml` are placed in a dedicated `[loaders]` optional extra in `pyproject.toml`, separate from `[dev]`. This gives version pinning and `uv.lock` tracking without polluting the default dev install with HuggingFace's large dependency tree (~hundreds of MB including pyarrow, fsspec). `huggingface-hub` is declared explicitly because all loaders import it directly (`from huggingface_hub import dataset_info`) — relying on it as a transitive dep of `datasets` would leave it unpinned and subject to silent version drift.

Each generated YAML file includes a header comment with an immutable git commit SHA from the HuggingFace Hub API (`huggingface_hub.dataset_info(dataset_id).sha`), not `dataset.info.version` which is a mutable semantic version string:
```yaml
# Generated by: python evals/loaders/load_humaneval.py --sample 50 --seed 42
# Dataset: openai/openai-humaneval, revision: <git-commit-sha>
# Generated at: 2026-04-01
```

---

## Usage Workflow

```bash
# Day-to-day: project evals only (fast)
npx promptfoo@latest eval

# Before/after model upgrade or major refactor: run benchmarks
npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml

# Run a single dimension (--filter-pattern matches description text, not metadata.category)
npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml \
    --filter-pattern "MT-Bench"
# Other dimension patterns: "HumanEval", "GAIA", "GSM8K", "BBH"

# Refresh static subset from HuggingFace (when intentionally updating baseline)
uv pip install -e ".[loaders]"
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
