"""Semantic diff / case-based adaptation strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker, finalize_result, run_tests
from src.providers import llm


class SemanticDiffStrategy(TaskDecompositionStrategy):
    name = "semantic_diff"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        neighbors = ctx.nearest_neighbors or ctx.metadata.get("neighbors", [])
        base_task = neighbors[0]["task_id"] if neighbors else "baseline"
        deltas: List[str] = []
        if ctx.constraints and neighbors:
            deltas.append("constraint_delta")
        if ctx.difficulty and neighbors and neighbors[0].get("difficulty") != ctx.difficulty:
            deltas.append("difficulty_delta")
        diff_prompt = (
            f"You are comparing a new task to base task {base_task}. List semantic deltas succinctly: {ctx.problem_statement[:200]}"
        )
        delta_note = tracker.consume(
            llm.call(diff_prompt, model="semantic-diff", max_tokens=80, temperature=0.0, caller=self.name),
            fallback="No deltas provided",
        )
        if delta_note:
            deltas.append(delta_note[:60])
        diagnostics = {
            "base_task": base_task,
            "num_deltas": str(len(deltas)),
            "delta_note": delta_note,
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
        }
        plan = DecompositionPlan(
            strategy_name=self.name,
            diagnostics=diagnostics,
            subtasks=["load base solution", "apply semantic deltas", "re-test"],
            patterns=[base_task],
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        tracker = BudgetTracker(f"{self.name}:solve")
        tracker.consume(
            llm.call("Explain how to adapt the base solution for listed deltas.", model="semantic-adapt", max_tokens=96, caller=self.name),
            fallback="Adaptation skipped",
        )
        base_code = ctx.metadata.get("reference_solution", "def solve(*args):\n    return None")
        tests_run = run_tests(base_code, ctx)
        planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0)
        planning_time = float(plan.diagnostics.get("planning_time", 0) or 0.0)
        metrics: Dict[str, float | str] = {
            "num_deltas": float(plan.diagnostics.get("num_deltas", 0) or 0),
            "tokens_used": planning_tokens + tracker.tokens,
            "planning_time": planning_time + tracker.time_spent,
            "neighbor": plan.diagnostics.get("base_task", "baseline"),
        }
        return finalize_result(ctx, plan, base_code, tests_run, metrics)
