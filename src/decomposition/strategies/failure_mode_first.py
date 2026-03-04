"""Failure-mode-first strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker, build_implementation_contract, finalize_result, run_tests
from src.decomposition.self_verify import request_repair_patch, summarize_failures
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
        tracker = BudgetTracker(f"{self.name}:solve")
        contract = build_implementation_contract(ctx)
        tracker.consume(
            llm.call(
                f"{contract}\nGenerate targeted tests for the enumerated failure modes.",
                model="failure-tests",
                max_tokens=64,
                caller=self.name,
            ),
            fallback="tests deferred",
        )
        base_code = ctx.metadata.get("reference_solution", "def solve(*args):\n    return None")
        tests_run = run_tests(base_code, ctx)
        iterations = 1
        repair_feedback = ""
        if any(tr["status"] == "fail" for tr in tests_run):
            summary = summarize_failures(tests_run)
            repair_feedback = "; ".join(summary.assertion_msgs)
            patched_code, repair_meta = request_repair_patch(self.name, ctx, plan, summary, base_code)
            base_code = patched_code
            tests_run = run_tests(base_code, ctx)
            iterations += 1
        planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0)
        planning_time = float(plan.diagnostics.get("planning_time", 0) or 0.0)
        metrics: Dict[str, float | str] = {
            "iterations": iterations,
            "tokens_used": planning_tokens + tracker.tokens,
            "planning_time": planning_time + tracker.time_spent,
            "fixed_failure_modes": sum(1 for tr in tests_run if tr["status"] == "pass"),
        }
        if repair_feedback:
            metrics["repair_feedback"] = repair_feedback
            metrics["repair_attempted"] = 1.0
            if repair_meta:
                metrics["repair_tokens"] = float(repair_meta.get("llm_tokens", "0") or 0)
        return finalize_result(ctx, plan, base_code, tests_run, metrics)
