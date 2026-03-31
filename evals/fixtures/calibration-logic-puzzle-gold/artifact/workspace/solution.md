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

**Step 3: Check whether the remaining assignments are uniquely determined**
- The clues no longer distinguish Alice from Carol for dog and fish
- Both of these assignments satisfy every clue:
  - Alice owns the dog, Carol owns the fish
  - Alice owns the fish, Carol owns the dog
- Therefore, Bob owning the cat is forced, but the remaining two pets are not uniquely assigned

## Answer

- Forced assignment: Bob owns the cat
- Remaining valid completions:
  - Option A: Alice owns the dog, Carol owns the fish
  - Option B: Alice owns the fish, Carol owns the dog
