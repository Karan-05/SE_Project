# Decomposition Usefulness Summary

## Strategy-level comparison
- `reports/ase2026_aegis/decomposition_strategy_comparison.csv` shows that every strategy (contract_first, pattern_skeleton, multi_view, failure_mode_first, and the new `direct_baseline`) solved 45/50 benchmark tasks (`success_rate=0.9`). The only failures are the five graph-degree variants, which share the same reference solution, so decomposition provided **no additional executable wins** over the no-decomposition baseline.
- Decomposition mainly changes plan richness: `pattern_skeleton` averages 8 subtasks and 2 explicit tests per task, while `direct_baseline` has only the mandatory four testing loops and two synthesized tests. Token and planning-time costs scale with plan depth (e.g., `avg_tokens_used` ranges from 0 for the baseline to 76.7 for pattern_skeleton).

## Task-type (difficulty) view
- Difficulty `S` tasks (12/50) pass in every strategy, including `direct_baseline`, confirming that extra decomposition is unnecessary for trivial additions (`reports/ase2026_aegis/decomposition_strategy_comparison.csv` + benchmark metadata).
- Difficulty `M` tasks (18/50) have 3 build failures per strategy, all on the `graph_degree_*` family where the provided reference solution is buggy. Decomposition could not repair these because the harness currently reuses the same code regardless of plan.
- Difficulty `H` tasks (20/50) also share 2 build failures per strategy for the same reason. No strategy produces additional successes because no repair loop is triggered.

## Takeaways
1. With the current reference-solution solver, decomposition only improves transparency (longer plans, richer tests) but **not** executable success relative to the no-decomposition baseline (`direct_baseline` vs. others).
2. Cost grows with decomposition depth (tokens/time), so deeper strategies incur overhead without yielding extra passes.
3. Future usefulness studies need an actual code generator/repair loop to expose cases where decomposition changes correctness; the present setup is ideal for visibility diagnostics but not for demonstrating success gains.
