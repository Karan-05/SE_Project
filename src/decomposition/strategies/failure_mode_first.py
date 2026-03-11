"""Failure-mode-first strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.agentic import execute_plan_with_repair
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker
from src.decomposition.agentic.semantic import get_semantic_config
from src.providers import llm


class FailureModeFirstStrategy(TaskDecompositionStrategy):
    name = "failure_mode_first"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        prompt = (
            "List three high-risk failure modes for this coding task along with short rationales: "
            f"{ctx.problem_statement[:300]}"
        )
        response = tracker.consume(
            llm.call(prompt, model="failure-scout", max_tokens=96, temperature=0.1, caller=self.name),
            fallback="capacity, degenerate inputs, adversarial cases",
        )
        failure_modes = [part.strip() for part in response.split(";") if part.strip()]
        if len(failure_modes) < 3:
            failure_modes.extend([
                "max constraints: extremely large inputs",
                "degenerate: empty or single-element",
                "adversarial: repeated values or cycles",
            ])
        diagnostics = {
            "failure_modes": ";".join(failure_modes[:3]),
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
        }
        plan = DecompositionPlan(
            strategy_name=self.name,
            subtasks=["enumerate failure modes", "design tests", "only then implement"],
            tests=failure_modes,
            diagnostics=diagnostics,
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        config = get_semantic_config(self.name)
        metrics: Dict[str, float | str] = {
            "failure_mode_count": float(len(plan.tests)),
            "semantic_variant": config.name,
        }
        return execute_plan_with_repair(
            ctx,
            plan,
            strategy_name=self.name,
            extra_metrics=metrics,
            semantic_config=config,
        )


class FailureModeFirstBaselineStrategy(FailureModeFirstStrategy):
    name = "failure_mode_first_baseline"


class FailureModeFirstChecklistStrategy(FailureModeFirstStrategy):
    name = "failure_mode_first_checklist"


class FailureModeFirstSemanticStrategy(FailureModeFirstStrategy):
    name = "failure_mode_first_semantic"
