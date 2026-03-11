"""Minimal baseline strategy without explicit decomposition."""
from __future__ import annotations

from src.decomposition.agentic import execute_plan_with_repair
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy


class DirectBaselineStrategy(TaskDecompositionStrategy):
    """Skip structured decomposition and rely solely on the provided reference solution."""

    name = "direct_baseline"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        return DecompositionPlan(
            strategy_name=self.name,
            contract={},
            subtasks=[],
            tests=[],
            diagnostics={"note": "No decomposition, direct execution."},
        )

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        metrics = {
            "contract_completeness": 0.0,
        }
        return execute_plan_with_repair(ctx, plan, strategy_name=self.name, extra_metrics=metrics)
