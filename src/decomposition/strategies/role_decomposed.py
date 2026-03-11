"""Role-decomposed collaborative strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.agentic import execute_plan_with_repair
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker
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
        metrics: Dict[str, float | str] = {
            "critic_comments": int(plan.diagnostics.get("critic_comments", 0) or 0),
            "roles": len(plan.subtasks),
        }
        return execute_plan_with_repair(ctx, plan, strategy_name=self.name, extra_metrics=metrics)
