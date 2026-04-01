# Benchmark Baselines

Update this file after each intentional benchmark run (model upgrade, prompt change, etc.).
A regression is defined as a drop of >=5 percentage points (or >=0.5 score points for MT-Bench)
vs. the most recent committed baseline.

`repeat: 3` is set in `promptfooconfig-benchmarks.yaml` for run stability. It runs each test
3 times and reports pass rate across runs. This smooths transient failures but does not expose
standard deviation directly.

## Baseline History

| Benchmark | Dimension | Pass Rate | MT-Bench Score | Date | Git Commit | Notes |
|-----------|-----------|-----------|----------------|------|------------|-------|
| (run benchmarks and fill in first row) | | | | | | Initial baseline |

## How to Update

1. Run: `npx promptfoo@latest eval --config promptfooconfig-benchmarks.yaml`
2. Record pass rates from promptfoo dashboard; use `--filter-pattern "HumanEval"` etc. to isolate dimensions
   (Note: `--filter-pattern` matches description text, not `metadata.category` tags)
3. Add a new row above the previous baseline
4. Commit: `git add evals/benchmarks/BASELINES.md && git commit -m "chore(eval): update baselines after <reason>"`

## Dimension Reference

| Benchmark | Category Tag | Dimension | Assertion Type |
|-----------|-------------|-----------|----------------|
| HumanEval | `benchmark-humaneval` | A — Code correctness | llm-rubric (sandbox execution + LLM judge) |
| GAIA L1 | `benchmark-gaia` | B — Tool use | javascript (answer match) |
| MT-Bench | `benchmark-mt-bench` | C — Instruction following | llm-rubric (score >=7) |
| GSM8K | `benchmark-gsm8k` | D1 — Arithmetic reasoning | javascript (#### delimiter) |
| BIG-bench Hard | `benchmark-bigbench-hard` | D2 — Logical reasoning | javascript (Answer: (X)) |

## Initial Thresholds (calibrate after first run)

| Benchmark | Threshold | Regression Signal |
|-----------|-----------|-------------------|
| HumanEval | pass@1 >= 60% | Drop >= 5pp |
| GAIA L1 | pass@1 >= 40% | Drop >= 5pp |
| MT-Bench | mean score >= 7.0 | Drop >= 0.5 |
| GSM8K | pass@1 >= 75% | Drop >= 5pp |
| BIG-bench Hard | pass@1 >= 55% | Drop >= 5pp |
