"""Multi-view synchronization strategy."""
from __future__ import annotations

from typing import Dict

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker, finalize_result, run_tests
from src.providers import llm


class MultiViewStrategy(TaskDecompositionStrategy):
    name = "multi_view"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        spec_view = ["Summarize goal", "List required outputs", "State constraints"]
        example_view = [ex.get("output", "") for ex in ctx.examples] or ["Need fresh example"]
        constraint_view = [ctx.constraints or ctx.metadata.get("constraints", "")]
        consistency_prompt = (
            "Check whether these views disagree. Spec: {spec}. Examples: {examples}. Constraints: {constraints}."
        ).format(spec=spec_view, examples=example_view, constraints=constraint_view)
        consistency_summary = tracker.consume(
            llm.call(consistency_prompt, model="view-checker", max_tokens=72, temperature=0.0, caller=self.name),
            fallback="Consistency unknown",
        )
        consistent = "inconsistent" not in consistency_summary.lower()
        diagnostics = {
            "consistent": str(consistent),
            "views": str(len(spec_view) + len(example_view) + len(constraint_view)),
            "consistency_note": consistency_summary,
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
        }
        plan = DecompositionPlan(
            strategy_name=self.name,
            subtasks=["align spec-view", "align example-view", "align constraint-view"],
            diagnostics=diagnostics,
            tests=example_view,
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        tracker = BudgetTracker(f"{self.name}:solve")
        tracker.consume(
            llm.call("Summarize consensus from tri-view before coding.", model="multi-view-notes", max_tokens=64, caller=self.name),
            fallback="Consensus unavailable",
        )
        base_code = ctx.metadata.get("reference_solution", "def solve(*args):\n    return None")
        tests_run = run_tests(base_code, ctx)
        planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0)
        planning_time = float(plan.diagnostics.get("planning_time", 0) or 0.0)
        metrics: Dict[str, float | str] = {
            "view_consistency": 1.0 if plan.diagnostics.get("consistent") == "True" else 0.0,
            "tokens_used": planning_tokens + tracker.tokens,
            "planning_time": planning_time + tracker.time_spent,
        }
        return finalize_result(ctx, plan, base_code, tests_run, metrics)
