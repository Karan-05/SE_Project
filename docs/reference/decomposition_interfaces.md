# decomposition.interfaces

_Summary_: Shared interfaces and dataclasses for task decomposition strategies.

## Classes
### DecompositionContext
Problem context passed into every strategy.

### DecompositionPlan
Structured plan produced by every strategy.

### StrategyResult
Full result bundle from executing a strategy.

### TaskDecompositionStrategy
Protocol that all strategies must implement.

Methods:
- `decompose(ctx)` — 
- `solve(ctx, plan)` —
