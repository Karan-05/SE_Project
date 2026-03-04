# decomposition.strategies._utils

_Summary_: Utility helpers for decomposition strategies.

## Classes
### BudgetTracker
Track tokens/time consumed when calling the LLM provider.

Methods:
- `consume(response, fallback)` — Record a response and return usable content or the fallback if budgeted out.

## Functions
- `run_tests(solution_code, ctx)` — 
- `finalize_result(ctx, plan, solution_code, tests_run, extra_metrics)` —
