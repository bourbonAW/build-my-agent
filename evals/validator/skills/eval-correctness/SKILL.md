---
name: eval-correctness
description: Evaluate whether agent output fulfills task requirements.
metadata:
  version: "1.0"
  author: bourbon
---

# Eval Correctness

Use this evaluator to assess correctness against the task prompt, success criteria, and resulting workspace state.

Return JSON with:
- `score`
- `breakdown`
- `reasoning`
- `evidence`
- `suggestions`
