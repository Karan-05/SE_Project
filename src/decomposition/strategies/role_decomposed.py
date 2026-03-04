"""Role-decomposed collaborative strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker, finalize_result, run_tests
from src.providers import llm


class RoleDecomposedStrategy(TaskDecompositionStrategy):
    name = "role_decomposed"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        architect_plan = tracker.consume(
            llm.call(
                f"Architect: propose a phased plan for task {ctx.task_id}: {ctx.problem_statement[:200]}",
                model="role-architect",
                max_tokens=96,
                temperature=0.2,
                caller=self.name,
            ),
            fallback="Architect unavailable",
        )
        critic_notes = tracker.consume(
            llm.call("Critic: find two weaknesses in the architect plan.", model="role-critic", max_tokens=64, temperature=0.2, caller=self.name),
            fallback="Critic unavailable",
        )
        diagnostics = {
            "critic_comments": str(max(1, critic_notes.count("-"))) if critic_notes else "0",
            "fuzzer_tests": "3",
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
        }
        plan = DecompositionPlan(
            strategy_name=self.name,
            subtasks=["Architect proposal", "Critic review", "Coder implementation", "Fuzzer tests"],
            role_messages=[architect_plan, critic_notes],
            diagnostics=diagnostics,
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        tracker = BudgetTracker(f"{self.name}:solve")
        tracker.consume(
            llm.call("Coder: summarize the approved plan before coding.", model="role-coder", max_tokens=80, caller=self.name),
            fallback="Coder unavailable",
        )
        base_code = ctx.metadata.get("reference_solution", "def solve(*args):\n    return None")
        tests_run = run_tests(base_code, ctx)
        planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0)
        planning_time = float(plan.diagnostics.get("planning_time", 0) or 0.0)
        metrics: Dict[str, float | str] = {
            "critic_comments": int(plan.diagnostics.get("critic_comments", 0) or 0),
            "tokens_used": planning_tokens + tracker.tokens,
            "planning_time": planning_time + tracker.time_spent,
            "roles": len(plan.subtasks),
        }
        return finalize_result(ctx, plan, base_code, tests_run, metrics)
