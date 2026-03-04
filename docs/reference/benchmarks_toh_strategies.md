# benchmarks.toh.strategies

_Summary_: Strategy implementations for the Tower-of-Hanoi benchmark.

## Classes
### BaseStrategy
No class docstring.

Methods:
- `__init__(token_budget)` — 
- `reset(n_disks, seed, goal_peg)` — 
- `_consume_tokens(*chunks)` — 
- `select_move(env)` — Return the next legal move.

### FullDecompositionStrategy
No class docstring.

Methods:
- `reset(n_disks, seed, goal_peg)` — 
- `select_move(env)` — 

### SelectThenDecomposeStrategy
No class docstring.

Methods:
- `__init__(token_budget, chunk_size, greedy_threshold)` — 
- `reset(n_disks, seed, goal_peg)` — 
- `_refill_chunk()` — 
- `_fallback_move(env)` — 
- `select_move(env)` — 

### NoDecompositionStrategy
No class docstring.

Methods:
- `select_move(env)` — 

## Functions
- `estimate_tokens(*chunks)` — 
- `_generate_plan(n, source, target, aux)` —
