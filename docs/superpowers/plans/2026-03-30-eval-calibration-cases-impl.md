# Eval-Agent Calibration Cases Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 calibration eval cases (2 problems × 3 variants) with pre-built artifacts and expected score ranges to verify the eval-agent's scoring accuracy.

**Architecture:** Calibration cases skip agent execution entirely — pre-built fixture directories contain the artifact (context.json, output.json, meta.json, workspace/). The runner's new `_run_calibration_case()` method copies the fixture, passes `workdir / "artifact"` to `EvaluatorAgentRunner`, then compares actual scores against `expected_scores` ranges defined in the case JSON. Each fixture's `artifact/` subdirectory mirrors `ArtifactBuilder` output so `EvaluatorAgentRunner` path conventions (`artifact_dir.parent` for config/report) work correctly.

**Tech Stack:** Python 3.10+, existing evals/runner.py, existing evals/validator/ infrastructure

**Reference Spec:** `docs/superpowers/specs/2026-03-30-eval-calibration-cases-design.md`

---

## File Structure

```
evals/
├── runner.py                                   # MODIFY: add _run_calibration_case(), modify run_single()
├── cases/
│   └── calibration/
│       ├── coding/
│       │   ├── below-zero-gold.json            # CREATE
│       │   ├── below-zero-buggy.json           # CREATE
│       │   └── below-zero-messy.json           # CREATE
│       └── reasoning/
│           ├── logic-puzzle-gold.json           # CREATE
│           ├── logic-puzzle-buggy.json          # CREATE
│           └── logic-puzzle-messy.json          # CREATE
├── fixtures/
│   ├── calibration-below-zero-gold/
│   │   └── artifact/                           # CREATE (all contents)
│   ├── calibration-below-zero-buggy/
│   │   └── artifact/                           # CREATE (all contents)
│   ├── calibration-below-zero-messy/
│   │   └── artifact/                           # CREATE (all contents)
│   ├── calibration-logic-puzzle-gold/
│   │   └── artifact/                           # CREATE (all contents)
│   ├── calibration-logic-puzzle-buggy/
│   │   └── artifact/                           # CREATE (all contents)
│   └── calibration-logic-puzzle-messy/
│       └── artifact/                           # CREATE (all contents)
└── tests/
    └── test_calibration_runner.py              # CREATE: unit tests for _run_calibration_case
```

---

## Task 1: Create `below_zero` Coding Fixtures (Gold/Buggy/Messy)

**Files:**
- Create: `evals/fixtures/calibration-below-zero-gold/artifact/context.json`
- Create: `evals/fixtures/calibration-below-zero-gold/artifact/output.json`
- Create: `evals/fixtures/calibration-below-zero-gold/artifact/meta.json`
- Create: `evals/fixtures/calibration-below-zero-gold/artifact/workspace/solution.py`
- Create: `evals/fixtures/calibration-below-zero-gold/artifact/workspace/test_solution.py`
- Create: `evals/fixtures/calibration-below-zero-buggy/artifact/context.json`
- Create: `evals/fixtures/calibration-below-zero-buggy/artifact/output.json`
- Create: `evals/fixtures/calibration-below-zero-buggy/artifact/meta.json`
- Create: `evals/fixtures/calibration-below-zero-buggy/artifact/workspace/solution.py`
- Create: `evals/fixtures/calibration-below-zero-messy/artifact/context.json`
- Create: `evals/fixtures/calibration-below-zero-messy/artifact/output.json`
- Create: `evals/fixtures/calibration-below-zero-messy/artifact/meta.json`
- Create: `evals/fixtures/calibration-below-zero-messy/artifact/workspace/solution.py`

- [ ] **Step 1: Create directory structure for all three variants**

```bash
mkdir -p evals/fixtures/calibration-below-zero-gold/artifact/workspace
mkdir -p evals/fixtures/calibration-below-zero-buggy/artifact/workspace
mkdir -p evals/fixtures/calibration-below-zero-messy/artifact/workspace
```

- [ ] **Step 2: Create shared context.json for all three variants**

All three variants share the same task prompt and success criteria. Create `evals/fixtures/calibration-below-zero-gold/artifact/context.json`:

```json
{
  "prompt": "Implement the function below_zero that detects if a bank account balance falls below zero during a series of deposit/withdrawal operations.\n\nThe account starts at zero balance. Return True if balance goes below zero at any point, False otherwise.\n\ndef below_zero(operations: List[int]) -> bool:\n    ...\n\nExamples:\n  below_zero([1, 2, 3]) → False\n  below_zero([1, 2, -4, 5]) → True",
  "success_criteria": [
    "Function signature is below_zero(operations: List[int]) -> bool",
    "Empty list returns False",
    "[1, 2, -4, 5] returns True",
    "[1, 2, -3, 1, 2, -3] returns False (balance touches zero but never goes below)",
    "Implementation correctly tracks cumulative balance"
  ],
  "success_criteria_formal": [],
  "constraints": [],
  "evaluation_hints": [
    "Check workspace/solution.py for the implementation",
    "Run the test assertions mentally against the code"
  ],
  "reference_files": []
}
```

Copy this same file to buggy and messy variants:

```bash
cp evals/fixtures/calibration-below-zero-gold/artifact/context.json \
   evals/fixtures/calibration-below-zero-buggy/artifact/context.json
cp evals/fixtures/calibration-below-zero-gold/artifact/context.json \
   evals/fixtures/calibration-below-zero-messy/artifact/context.json
```

- [ ] **Step 3: Create Gold variant workspace and output**

Create `evals/fixtures/calibration-below-zero-gold/artifact/workspace/solution.py`:

```python
from typing import List


def below_zero(operations: List[int]) -> bool:
    """Detect if bank account balance falls below zero.

    Args:
        operations: List of deposit (positive) and withdrawal (negative) amounts.

    Returns:
        True if balance goes below zero at any point, False otherwise.
    """
    balance = 0
    for op in operations:
        balance += op
        if balance < 0:
            return True
    return False
```

Create `evals/fixtures/calibration-below-zero-gold/artifact/workspace/test_solution.py`:

```python
from solution import below_zero


def test_empty():
    assert below_zero([]) == False

def test_all_positive():
    assert below_zero([1, 2, 3]) == False

def test_goes_below():
    assert below_zero([1, 2, -4, 5]) == True

def test_touches_zero():
    assert below_zero([1, 2, -3, 1, 2, -3]) == False

def test_immediate_negative():
    assert below_zero([-1, 2, 3]) == True

def test_deep_negative():
    assert below_zero([1, -1, 2, -2, 5, -5, 4, -5]) == True
```

Create `evals/fixtures/calibration-below-zero-gold/artifact/output.json`:

```json
{
  "final_output": "I've implemented the below_zero function in solution.py with a simple accumulator pattern. The function tracks the running balance and returns True as soon as it drops below zero. All test cases pass.",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

Create `evals/fixtures/calibration-below-zero-gold/artifact/meta.json`:

```json
{
  "case_id": "calibration-below-zero-gold",
  "duration_ms": 5000,
  "token_usage": {"input_tokens": 1000, "output_tokens": 500},
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

- [ ] **Step 4: Create Buggy variant workspace and output**

Create `evals/fixtures/calibration-below-zero-buggy/artifact/workspace/solution.py`:

```python
from typing import List


def below_zero(operations: List[int]) -> bool:
    """Check if balance goes below zero."""
    balance = 0
    for op in operations:
        balance += op
    if balance < 0:
        return True
    return False
```

Note: The bug is that `if balance < 0` is outside the loop — only checks the final balance, not intermediate states. `[1, 2, -4, 5]` returns False (final balance is 4) but should return True (balance hits -1 mid-sequence).

Create `evals/fixtures/calibration-below-zero-buggy/artifact/output.json`:

```json
{
  "final_output": "Implemented below_zero. The function sums all operations and checks if the final balance is negative.",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

Create `evals/fixtures/calibration-below-zero-buggy/artifact/meta.json`:

```json
{
  "case_id": "calibration-below-zero-buggy",
  "duration_ms": 3000,
  "token_usage": {"input_tokens": 800, "output_tokens": 300},
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

- [ ] **Step 5: Create Messy variant workspace and output**

Create `evals/fixtures/calibration-below-zero-messy/artifact/workspace/solution.py`:

```python
from typing import List
import sys
import os

def below_zero(operations: List[int]) -> bool:
    # this function checks stuff
    x = 0  # balance
    flag = False  # did we go below?
    lst = list(operations)  # make a copy just in case
    i = 0
    while i < len(lst):
        val = lst[i]
        x = x + val
        if x < 0:
            flag = True
            break  # found it
        else:
            pass  # do nothing
        i = i + 1
    if flag == True:
        return True
    else:
        return False
```

Create `evals/fixtures/calibration-below-zero-messy/artifact/output.json`:

```json
{
  "final_output": "ok so i wrote the function. it works i think. it goes through all the numbers and keeps track. let me know if u need anything else",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

Create `evals/fixtures/calibration-below-zero-messy/artifact/meta.json`:

```json
{
  "case_id": "calibration-below-zero-messy",
  "duration_ms": 8000,
  "token_usage": {"input_tokens": 1200, "output_tokens": 600},
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

- [ ] **Step 6: Verify all fixture files exist**

```bash
find evals/fixtures/calibration-below-zero-* -type f | sort
```

Expected output:
```
evals/fixtures/calibration-below-zero-buggy/artifact/context.json
evals/fixtures/calibration-below-zero-buggy/artifact/meta.json
evals/fixtures/calibration-below-zero-buggy/artifact/output.json
evals/fixtures/calibration-below-zero-buggy/artifact/workspace/solution.py
evals/fixtures/calibration-below-zero-gold/artifact/context.json
evals/fixtures/calibration-below-zero-gold/artifact/meta.json
evals/fixtures/calibration-below-zero-gold/artifact/output.json
evals/fixtures/calibration-below-zero-gold/artifact/workspace/solution.py
evals/fixtures/calibration-below-zero-gold/artifact/workspace/test_solution.py
evals/fixtures/calibration-below-zero-messy/artifact/context.json
evals/fixtures/calibration-below-zero-messy/artifact/meta.json
evals/fixtures/calibration-below-zero-messy/artifact/output.json
evals/fixtures/calibration-below-zero-messy/artifact/workspace/solution.py
```

- [ ] **Step 7: Commit**

```bash
git add evals/fixtures/calibration-below-zero-*/
git commit -m "feat(eval): add below_zero calibration fixtures (gold/buggy/messy)

Pre-built artifacts from HumanEval/3 for eval-agent calibration.
Gold: correct accumulator pattern. Buggy: check-after-loop bug.
Messy: correct but poor naming, unused imports, anti-patterns."
```

---

## Task 2: Create Logic Puzzle Reasoning Fixtures (Gold/Buggy/Messy)

**Files:**
- Create: `evals/fixtures/calibration-logic-puzzle-gold/artifact/context.json`
- Create: `evals/fixtures/calibration-logic-puzzle-gold/artifact/output.json`
- Create: `evals/fixtures/calibration-logic-puzzle-gold/artifact/meta.json`
- Create: `evals/fixtures/calibration-logic-puzzle-gold/artifact/workspace/solution.md`
- Create: `evals/fixtures/calibration-logic-puzzle-buggy/artifact/context.json`
- Create: `evals/fixtures/calibration-logic-puzzle-buggy/artifact/output.json`
- Create: `evals/fixtures/calibration-logic-puzzle-buggy/artifact/meta.json`
- Create: `evals/fixtures/calibration-logic-puzzle-buggy/artifact/workspace/solution.md`
- Create: `evals/fixtures/calibration-logic-puzzle-messy/artifact/context.json`
- Create: `evals/fixtures/calibration-logic-puzzle-messy/artifact/output.json`
- Create: `evals/fixtures/calibration-logic-puzzle-messy/artifact/meta.json`
- Create: `evals/fixtures/calibration-logic-puzzle-messy/artifact/workspace/solution.md`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p evals/fixtures/calibration-logic-puzzle-gold/artifact/workspace
mkdir -p evals/fixtures/calibration-logic-puzzle-buggy/artifact/workspace
mkdir -p evals/fixtures/calibration-logic-puzzle-messy/artifact/workspace
```

- [ ] **Step 2: Create shared context.json for all three variants**

Create `evals/fixtures/calibration-logic-puzzle-gold/artifact/context.json`:

```json
{
  "prompt": "Solve the following logic puzzle and write your solution to solution.md:\n\nThree friends — Alice, Bob, and Carol — each own exactly one pet:\na cat, a dog, and a fish (one pet per person, no repeats).\n\nClues:\n1. Alice does not own the cat.\n2. Bob does not own the dog.\n3. Carol does not own the cat.\n\nDetermine who owns which pet. Show your reasoning step by step.",
  "success_criteria": [
    "Correct conclusion: Alice owns the dog, Bob owns the cat, Carol owns the fish",
    "Reasoning shows step-by-step elimination",
    "Solution is written to solution.md"
  ],
  "success_criteria_formal": [],
  "constraints": [],
  "evaluation_hints": [
    "Check workspace/solution.md for the reasoning and answer",
    "Verify that the final answer does not violate any of the three clues"
  ],
  "reference_files": []
}
```

```bash
cp evals/fixtures/calibration-logic-puzzle-gold/artifact/context.json \
   evals/fixtures/calibration-logic-puzzle-buggy/artifact/context.json
cp evals/fixtures/calibration-logic-puzzle-gold/artifact/context.json \
   evals/fixtures/calibration-logic-puzzle-messy/artifact/context.json
```

- [ ] **Step 3: Create Gold variant workspace and output**

Create `evals/fixtures/calibration-logic-puzzle-gold/artifact/workspace/solution.md`:

```markdown
# Logic Puzzle Solution

## Given
- Three friends: Alice, Bob, Carol
- Three pets: cat, dog, fish
- Each person owns exactly one pet

## Reasoning

**Step 1: Apply Clue 1 and 3**
- Alice does not own the cat (Clue 1)
- Carol does not own the cat (Clue 3)
- Therefore, Bob owns the cat (only remaining option)

**Step 2: Apply Clue 2**
- Bob does not own the dog (Clue 2) — consistent, since Bob owns the cat
- Remaining pets for Alice and Carol: dog and fish

**Step 3: Determine remaining assignments**
- Alice cannot own the cat (already assigned to Bob)
- No constraint prevents Alice from owning the dog
- Therefore: Alice owns the dog, Carol owns the fish

## Answer

| Person | Pet  |
|--------|------|
| Alice  | Dog  |
| Bob    | Cat  |
| Carol  | Fish |
```

Create `evals/fixtures/calibration-logic-puzzle-gold/artifact/output.json`:

```json
{
  "final_output": "I solved the logic puzzle using elimination. The key insight is that clues 1 and 3 together force Bob to own the cat, which then determines the rest. Full solution written to solution.md.",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

Create `evals/fixtures/calibration-logic-puzzle-gold/artifact/meta.json`:

```json
{
  "case_id": "calibration-logic-puzzle-gold",
  "duration_ms": 4000,
  "token_usage": {"input_tokens": 900, "output_tokens": 600},
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

- [ ] **Step 4: Create Buggy variant workspace and output**

Create `evals/fixtures/calibration-logic-puzzle-buggy/artifact/workspace/solution.md`:

```markdown
# Solution

Alice doesn't have a cat, so she has a dog.
Bob doesn't have a dog, so he has a fish.
Carol doesn't have a cat, so she has a cat... wait.

Actually, let me try again.
Alice has a fish.
Bob has a dog.
Carol has a cat.

The answer is Alice=fish, Bob=dog, Carol=cat.
```

Note: The answer is wrong — Bob=dog violates Clue 2, Carol=cat violates Clue 3. The reasoning is self-contradictory and abandoned mid-way.

Create `evals/fixtures/calibration-logic-puzzle-buggy/artifact/output.json`:

```json
{
  "final_output": "Solved it. Alice has fish, Bob has dog, Carol has cat.",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

Create `evals/fixtures/calibration-logic-puzzle-buggy/artifact/meta.json`:

```json
{
  "case_id": "calibration-logic-puzzle-buggy",
  "duration_ms": 3000,
  "token_usage": {"input_tokens": 800, "output_tokens": 400},
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

- [ ] **Step 5: Create Messy variant workspace and output**

Create `evals/fixtures/calibration-logic-puzzle-messy/artifact/workspace/solution.md`:

```markdown
ok so lets figure this out

alice no cat, bob no dog, carol no cat

so like if alice cant have cat and carol cant have cat then bob has to have cat right? yeah that makes sense

and then bob cant have dog but he already has cat so thats fine

so alice and carol have dog and fish left. alice can have dog and carol has fish

answer: alice=dog bob=cat carol=fish

actually wait let me double check. alice no cat - she has dog, ok. bob no dog - he has cat, ok. carol no cat - she has fish, ok. yeah its right
```

Create `evals/fixtures/calibration-logic-puzzle-messy/artifact/output.json`:

```json
{
  "final_output": "figured it out, wrote to solution.md. alice gets the dog, bob gets the cat, carol gets the fish. pretty sure thats right",
  "tool_calls": [],
  "errors": [],
  "exit_reason": "completed"
}
```

Create `evals/fixtures/calibration-logic-puzzle-messy/artifact/meta.json`:

```json
{
  "case_id": "calibration-logic-puzzle-messy",
  "duration_ms": 6000,
  "token_usage": {"input_tokens": 900, "output_tokens": 500},
  "timestamp": "2026-03-30T00:00:00Z",
  "generator_version": "calibration-fixture"
}
```

- [ ] **Step 6: Verify all fixture files exist**

```bash
find evals/fixtures/calibration-logic-puzzle-* -type f | sort
```

Expected: 12 files (3 variants × 4 files each: context.json, output.json, meta.json, workspace/solution.md)

- [ ] **Step 7: Commit**

```bash
git add evals/fixtures/calibration-logic-puzzle-*/
git commit -m "feat(eval): add logic puzzle calibration fixtures (gold/buggy/messy)

Pre-built artifacts for constraint reasoning eval-agent calibration.
Gold: correct elimination with structured steps. Buggy: wrong answer with
contradictory reasoning. Messy: correct answer but unstructured prose."
```

---

## Task 3: Create Calibration Case JSON Files

**Files:**
- Create: `evals/cases/calibration/coding/below-zero-gold.json`
- Create: `evals/cases/calibration/coding/below-zero-buggy.json`
- Create: `evals/cases/calibration/coding/below-zero-messy.json`
- Create: `evals/cases/calibration/reasoning/logic-puzzle-gold.json`
- Create: `evals/cases/calibration/reasoning/logic-puzzle-buggy.json`
- Create: `evals/cases/calibration/reasoning/logic-puzzle-messy.json`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p evals/cases/calibration/coding
mkdir -p evals/cases/calibration/reasoning
```

- [ ] **Step 2: Create below-zero-gold.json**

Create `evals/cases/calibration/coding/below-zero-gold.json`:

```json
{
  "id": "calibration-below-zero-gold",
  "name": "Calibration: below_zero (Gold)",
  "category": "calibration",
  "subcategory": "coding",
  "difficulty": "easy",
  "description": "Gold variant: perfect implementation of HumanEval/3 below_zero. Expects high scores on both correctness and quality.",
  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-below-zero-gold"
  },
  "assertions": [],
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Function below_zero correctly detects when balance goes below zero",
      "Function returns True for [1, 2, -4, 5] and False for [1, 2, 3]",
      "All test cases pass"
    ],
    "evaluation_hints": [
      "Check workspace/solution.py for the implementation",
      "Run the test assertions mentally against the code"
    ],
    "expected_scores": {
      "correctness": { "min": 9, "max": 10 },
      "quality": { "min": 8, "max": 10 }
    }
  },
  "tags": ["calibration", "coding", "humaneval", "gold"]
}
```

- [ ] **Step 3: Create below-zero-buggy.json**

Create `evals/cases/calibration/coding/below-zero-buggy.json`:

```json
{
  "id": "calibration-below-zero-buggy",
  "name": "Calibration: below_zero (Buggy)",
  "category": "calibration",
  "subcategory": "coding",
  "difficulty": "easy",
  "description": "Buggy variant: check-after-loop bug only checks final balance, not intermediate states. Expects low correctness score.",
  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-below-zero-buggy"
  },
  "assertions": [],
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Function below_zero correctly detects when balance goes below zero",
      "Function returns True for [1, 2, -4, 5] and False for [1, 2, 3]",
      "All test cases pass"
    ],
    "evaluation_hints": [
      "Check workspace/solution.py for the implementation",
      "Run the test assertions mentally against the code"
    ],
    "expected_scores": {
      "correctness": { "min": 1, "max": 4 },
      "quality": { "min": 2, "max": 5 }
    }
  },
  "tags": ["calibration", "coding", "humaneval", "buggy"]
}
```

- [ ] **Step 4: Create below-zero-messy.json**

Create `evals/cases/calibration/coding/below-zero-messy.json`:

```json
{
  "id": "calibration-below-zero-messy",
  "name": "Calibration: below_zero (Messy)",
  "category": "calibration",
  "subcategory": "coding",
  "difficulty": "easy",
  "description": "Correct-but-messy variant: works correctly but has unused imports, poor naming, anti-patterns. Expects high correctness but low quality.",
  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-below-zero-messy"
  },
  "assertions": [],
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Function below_zero correctly detects when balance goes below zero",
      "Function returns True for [1, 2, -4, 5] and False for [1, 2, 3]",
      "All test cases pass"
    ],
    "evaluation_hints": [
      "Check workspace/solution.py for the implementation",
      "Run the test assertions mentally against the code"
    ],
    "expected_scores": {
      "correctness": { "min": 7, "max": 9 },
      "quality": { "min": 2, "max": 4 }
    }
  },
  "tags": ["calibration", "coding", "humaneval", "messy"]
}
```

- [ ] **Step 5: Create logic-puzzle-gold.json**

Create `evals/cases/calibration/reasoning/logic-puzzle-gold.json`:

```json
{
  "id": "calibration-logic-puzzle-gold",
  "name": "Calibration: Logic Puzzle (Gold)",
  "category": "calibration",
  "subcategory": "reasoning",
  "difficulty": "easy",
  "description": "Gold variant: correct elimination reasoning with structured steps. Expects high scores on both dimensions.",
  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-logic-puzzle-gold"
  },
  "assertions": [],
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Correct conclusion: Alice owns the dog, Bob owns the cat, Carol owns the fish",
      "Reasoning shows step-by-step elimination",
      "Solution is written to solution.md"
    ],
    "evaluation_hints": [
      "Check workspace/solution.md for the reasoning and answer",
      "Verify the final answer does not violate any of the three clues"
    ],
    "expected_scores": {
      "correctness": { "min": 9, "max": 10 },
      "quality": { "min": 9, "max": 10 }
    }
  },
  "tags": ["calibration", "reasoning", "logic", "gold"]
}
```

- [ ] **Step 6: Create logic-puzzle-buggy.json**

Create `evals/cases/calibration/reasoning/logic-puzzle-buggy.json`:

```json
{
  "id": "calibration-logic-puzzle-buggy",
  "name": "Calibration: Logic Puzzle (Buggy)",
  "category": "calibration",
  "subcategory": "reasoning",
  "difficulty": "easy",
  "description": "Buggy variant: wrong answer that violates clues 2 and 3, self-contradictory reasoning. Expects low scores.",
  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-logic-puzzle-buggy"
  },
  "assertions": [],
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Correct conclusion: Alice owns the dog, Bob owns the cat, Carol owns the fish",
      "Reasoning shows step-by-step elimination",
      "Solution is written to solution.md"
    ],
    "evaluation_hints": [
      "Check workspace/solution.md for the reasoning and answer",
      "Verify the final answer does not violate any of the three clues"
    ],
    "expected_scores": {
      "correctness": { "min": 1, "max": 3 },
      "quality": { "min": 2, "max": 5 }
    }
  },
  "tags": ["calibration", "reasoning", "logic", "buggy"]
}
```

- [ ] **Step 7: Create logic-puzzle-messy.json**

Create `evals/cases/calibration/reasoning/logic-puzzle-messy.json`:

```json
{
  "id": "calibration-logic-puzzle-messy",
  "name": "Calibration: Logic Puzzle (Messy)",
  "category": "calibration",
  "subcategory": "reasoning",
  "difficulty": "easy",
  "description": "Correct-but-messy variant: right answer but unstructured, informal prose. Expects high correctness but low quality.",
  "pre_built_artifact": true,
  "context": {
    "workdir": "fixtures/calibration-logic-puzzle-messy"
  },
  "assertions": [],
  "evaluator": {
    "enabled": true,
    "focus": ["correctness", "quality"],
    "threshold": 7.0,
    "timeout": 120,
    "dimensions": {
      "correctness": { "weight": 0.7, "threshold": 8.0 },
      "quality": { "weight": 0.3, "threshold": 6.0 }
    },
    "success_criteria": [
      "Correct conclusion: Alice owns the dog, Bob owns the cat, Carol owns the fish",
      "Reasoning shows step-by-step elimination",
      "Solution is written to solution.md"
    ],
    "evaluation_hints": [
      "Check workspace/solution.md for the reasoning and answer",
      "Verify the final answer does not violate any of the three clues"
    ],
    "expected_scores": {
      "correctness": { "min": 7, "max": 9 },
      "quality": { "min": 2, "max": 4 }
    }
  },
  "tags": ["calibration", "reasoning", "logic", "messy"]
}
```

- [ ] **Step 8: Verify case loading**

```bash
python -c "
import json
from pathlib import Path
cases = list(Path('evals/cases/calibration').rglob('*.json'))
print(f'Found {len(cases)} calibration cases:')
for c in sorted(cases):
    data = json.loads(c.read_text())
    print(f'  {data[\"id\"]} ({data[\"subcategory\"]})')
"
```

Expected:
```
Found 6 calibration cases:
  calibration-below-zero-buggy (coding)
  calibration-below-zero-gold (coding)
  calibration-below-zero-messy (coding)
  calibration-logic-puzzle-buggy (reasoning)
  calibration-logic-puzzle-gold (reasoning)
  calibration-logic-puzzle-messy (reasoning)
```

- [ ] **Step 9: Commit**

```bash
git add evals/cases/calibration/
git commit -m "feat(eval): add calibration case JSON configs (6 cases)

Two problems (below_zero coding, logic puzzle reasoning) with three
variants each (gold/buggy/messy). Each case defines expected_scores
ranges for calibrating eval-agent accuracy."
```

---

## Task 4: Add `_run_calibration_case()` to Runner

**Files:**
- Modify: `evals/runner.py:486-490` (add early return in `run_single()`)
- Modify: `evals/runner.py` (add new `_run_calibration_case()` method)
- Create: `tests/evals/test_calibration_runner.py`

- [ ] **Step 1: Write failing test for calibration case loading and routing**

Create `tests/evals/test_calibration_runner.py`:

```python
"""Tests for calibration case runner support."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_run_single_routes_to_calibration(tmp_path: Path):
    """run_single dispatches to _run_calibration_case when pre_built_artifact is True."""
    from unittest.mock import MagicMock, patch

    from evals.runner import EvalRunner

    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {}

    case = {
        "id": "test-calibration",
        "pre_built_artifact": True,
        "evaluator": {"enabled": True},
    }

    mock_result = MagicMock()
    with patch.object(runner, "_run_calibration_case", return_value=mock_result) as mock_method:
        result = runner.run_single(case, run_number=1)

    mock_method.assert_called_once_with(case, 1)
    assert result is mock_result


def test_run_calibration_case_missing_artifact_dir(tmp_path: Path, monkeypatch):
    """_run_calibration_case fails gracefully when artifact/ subdirectory is missing."""
    from evals.runner import EvalRunner

    runner = EvalRunner.__new__(EvalRunner)
    runner.config = {}

    # Fixture without artifact/ subdirectory
    fixture_dir = tmp_path / "fixtures" / "bad-fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "context.json").write_text("{}", encoding="utf-8")

    case = {
        "id": "test-missing-artifact",
        "pre_built_artifact": True,
        "context": {"workdir": "fixtures/bad-fixture"},
        "evaluator": {"enabled": True, "focus": ["correctness"]},
    }

    # Patch _setup_workspace to return our fixture
    def fake_setup(c):
        dest = tmp_path / "workdir"
        shutil.copytree(fixture_dir, dest, dirs_exist_ok=True)
        return dest

    monkeypatch.setattr(runner, "_setup_workspace", fake_setup)

    result = runner._run_calibration_case(case, run_number=1)

    assert result.success is False
    assert "artifact" in result.error.lower()


def test_calibration_success_only_uses_calibration_assertions():
    """Success is determined by calibration_* assertions, not eval_* threshold assertions.

    This is critical: Buggy variants will have failing eval_* assertions (score < threshold)
    but should still pass if calibration_* assertions (score in expected range) pass.
    """
    from evals.validator.report import ValidationDimension, ValidationReport

    # Simulate a Buggy variant: low score that is BELOW threshold but IN expected range
    dim = ValidationDimension(
        name="correctness",
        score=3.0,
        weight=0.7,
        threshold=8.0,  # score 3.0 < threshold 8.0 → eval_correctness fails
        skill="eval-correctness",
        reasoning="Bad implementation",
        evidence=["has bugs"],
    )
    report = ValidationReport(dimensions=[dim], overall_threshold=8.0)

    assertion_results = report.to_assertions()
    # eval_correctness should be failing (score < threshold)
    eval_assertion = next(a for a in assertion_results if a["id"] == "eval_correctness")
    assert eval_assertion["passed"] is False

    # Add calibration assertion — score 3.0 IS in expected range [1, 4]
    expected_scores = {"correctness": {"min": 1, "max": 4}}
    for dim_name, expected in expected_scores.items():
        actual = next((d for d in report.dimensions if d.name == dim_name), None)
        if actual is None:
            assertion_results.append({"id": f"calibration_{dim_name}", "passed": False, "evidence": ""})
        else:
            in_range = expected["min"] <= actual.score <= expected["max"]
            assertion_results.append({"id": f"calibration_{dim_name}", "passed": in_range, "evidence": ""})

    # Success should be True because calibration_* assertions pass
    calibration_assertions = [a for a in assertion_results if a["id"].startswith("calibration_")]
    success = bool(calibration_assertions) and all(a["passed"] for a in calibration_assertions)
    assert success is True


def test_calibration_expected_scores_out_of_range():
    """Calibration assertions fail when actual scores are outside expected range."""
    from evals.validator.report import ValidationDimension, ValidationReport

    dim = ValidationDimension(
        name="correctness",
        score=5.0,
        weight=0.7,
        threshold=8.0,
        skill="eval-correctness",
        reasoning="Mediocre",
        evidence=["partial"],
    )
    report = ValidationReport(dimensions=[dim], overall_threshold=8.0)

    expected_scores = {"correctness": {"min": 9, "max": 10}}
    assertions = []

    for dim_name, expected in expected_scores.items():
        actual = next((d for d in report.dimensions if d.name == dim_name), None)
        if actual is None:
            assertions.append({"id": f"calibration_{dim_name}", "passed": False, "evidence": ""})
        else:
            in_range = expected["min"] <= actual.score <= expected["max"]
            assertions.append({"id": f"calibration_{dim_name}", "passed": in_range, "evidence": ""})

    calibration_assertion = next(a for a in assertions if a["id"] == "calibration_correctness")
    assert calibration_assertion["passed"] is False


def test_calibration_missing_dimension():
    """Calibration assertions fail when expected dimension is missing from report."""
    from evals.validator.report import ValidationDimension, ValidationReport

    dim = ValidationDimension(
        name="quality",
        score=8.0,
        weight=0.3,
        threshold=6.0,
        skill="eval-quality",
        reasoning="Good quality",
        evidence=["clean"],
    )
    report = ValidationReport(dimensions=[dim], overall_threshold=8.0)

    expected_scores = {"correctness": {"min": 9, "max": 10}}
    assertions = []

    for dim_name, expected in expected_scores.items():
        actual = next((d for d in report.dimensions if d.name == dim_name), None)
        if actual is None:
            assertions.append({
                "id": f"calibration_{dim_name}",
                "passed": False,
                "evidence": f"dimension '{dim_name}' not found",
            })
        else:
            in_range = expected["min"] <= actual.score <= expected["max"]
            assertions.append({"id": f"calibration_{dim_name}", "passed": in_range, "evidence": ""})

    assert len(assertions) == 1
    assert assertions[0]["passed"] is False
    assert "not found" in assertions[0]["evidence"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/evals/test_calibration_runner.py -v
```

Expected: `test_run_single_routes_to_calibration` FAILS because `run_single()` doesn't check `pre_built_artifact` yet. The assertion-logic tests may pass since they test standalone logic.

- [ ] **Step 3: Add early return in `run_single()`**

Modify `evals/runner.py:486-490`. Add the routing check at the top of `run_single()`:

```python
    def run_single(self, case: dict, run_number: int = 1) -> EvalResult:
        """执行单次运行"""
        if case.get("pre_built_artifact"):
            return self._run_calibration_case(case, run_number)

        workdir = None
        original_cwd = Path.cwd()
        start = time.time()
```

- [ ] **Step 4: Add `_run_calibration_case()` method**

Add this method to the `EvalRunner` class, after `_run_validation()` (after line 484):

```python
    def _run_calibration_case(self, case: dict, run_number: int = 1) -> EvalResult:
        """Run a pre-built artifact through the evaluator only (no agent execution)."""
        start = time.time()
        workdir = self._setup_workspace(case)

        try:
            artifact_dir = workdir / "artifact"
            if not artifact_dir.exists():
                raise RuntimeError(
                    f"Pre-built artifact not found: {artifact_dir}. "
                    "Fixture must contain an artifact/ subdirectory."
                )

            evaluator_config = case.get("evaluator", {})
            focus = evaluator_config.get("focus", ["correctness"])
            dimensions_config = dict(evaluator_config.get("dimensions", {}))
            for dim_name, dim_config in (
                self.config.get("evaluator", {}).get("default_dimensions", {}).items()
            ):
                dimensions_config.setdefault(dim_name, dim_config)

            report_path = EvaluatorAgentRunner(
                artifact_dir=artifact_dir,
                focus=focus,
                threshold=evaluator_config.get(
                    "threshold",
                    self.config.get("evaluator", {}).get("default_threshold", 8.0),
                ),
                timeout=evaluator_config.get(
                    "timeout",
                    self.config.get("evaluator", {}).get("default_timeout", 120),
                ),
                dimensions_config=dimensions_config,
                dimension_to_skill=self.config.get("evaluator", {}).get(
                    "dimension_to_skill", {}
                ),
            ).run()
            report = ValidationReport.load(report_path)

            assertion_results = report.to_assertions()

            expected_scores = evaluator_config.get("expected_scores", {})
            for dim_name, expected in expected_scores.items():
                actual = next(
                    (d for d in report.dimensions if d.name == dim_name), None
                )
                if actual is None:
                    assertion_results.append({
                        "id": f"calibration_{dim_name}",
                        "text": f"{dim_name} score in [{expected['min']}, {expected['max']}]",
                        "passed": False,
                        "evidence": f"dimension '{dim_name}' not found in evaluation report",
                    })
                else:
                    in_range = expected["min"] <= actual.score <= expected["max"]
                    assertion_results.append({
                        "id": f"calibration_{dim_name}",
                        "text": f"{dim_name} score in [{expected['min']}, {expected['max']}]",
                        "passed": in_range,
                        "evidence": f"actual={actual.score:.1f}, expected=[{expected['min']}, {expected['max']}]",
                    })

            # For calibration cases, success is determined ONLY by calibration_*
            # assertions (expected score ranges), NOT by eval_* threshold assertions.
            # Buggy/Messy variants intentionally score below threshold, so
            # report.to_assertions() will include failing eval_* assertions —
            # that's expected, not a test failure.
            calibration_assertions = [
                a for a in assertion_results if a["id"].startswith("calibration_")
            ]
            success = (
                bool(calibration_assertions)
                and all(a["passed"] for a in calibration_assertions)
            )
            duration = int((time.time() - start) * 1000)

            return EvalResult(
                case_id=case["id"],
                success=success,
                duration_ms=duration,
                assertions=assertion_results,
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
            if workdir and not os.environ.get("EVAL_KEEP_ARTIFACTS"):
                self._cleanup_workspace(workdir)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/evals/test_calibration_runner.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 6: Run existing tests for regression**

```bash
pytest tests/ -v --timeout=30 2>&1 | tail -30
```

Expected: No new failures

- [ ] **Step 7: Run linter**

```bash
ruff check evals/runner.py tests/evals/test_calibration_runner.py
ruff format evals/runner.py tests/evals/test_calibration_runner.py
```

- [ ] **Step 8: Commit**

```bash
git add evals/runner.py tests/evals/test_calibration_runner.py
git commit -m "feat(eval): add _run_calibration_case() for pre-built artifact evaluation

- run_single() routes to _run_calibration_case() when pre_built_artifact is true
- Skips agent execution, passes fixture artifact/ directly to EvaluatorAgentRunner
- Adds calibration assertions: verifies scores fall within expected_scores ranges
- Handles missing dimensions and missing artifact/ subdirectory gracefully
- Merges global default_dimensions config for consistency with normal eval path"
```

---

## Task 5: Verify Case Loading and Lint

- [ ] **Step 1: Verify cases load correctly via the runner**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from evals.runner import EvalRunner
runner = EvalRunner()
cases = runner.load_cases(category='calibration')
print(f'Loaded {len(cases)} calibration cases:')
for c in cases:
    print(f'  {c[\"id\"]} pre_built={c.get(\"pre_built_artifact\", False)}')
"
```

Expected:
```
Loaded 6 calibration cases:
  calibration-below-zero-buggy pre_built=True
  calibration-below-zero-gold pre_built=True
  calibration-below-zero-messy pre_built=True
  calibration-logic-puzzle-buggy pre_built=True
  calibration-logic-puzzle-gold pre_built=True
  calibration-logic-puzzle-messy pre_built=True
```

- [ ] **Step 2: Verify subcategory filtering works**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from evals.runner import EvalRunner
runner = EvalRunner()
cases = runner.load_cases(category='calibration/coding')
print(f'Loaded {len(cases)} coding calibration cases:')
for c in cases:
    print(f'  {c[\"id\"]}')
"
```

Expected: 3 coding cases only

- [ ] **Step 3: Run full linter pass on all changed files**

```bash
ruff check evals/ tests/evals/
ruff format evals/ tests/evals/
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v --timeout=30
```

Expected: All tests pass, no regressions

- [ ] **Step 5: Commit if any lint changes**

```bash
git diff --name-only
# If any files changed:
git add -u
git commit -m "chore(eval): lint and format calibration code"
```
