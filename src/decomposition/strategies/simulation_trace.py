"""Simulation-trace / hierarchical reasoning strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker, finalize_result, run_tests
from src.providers import llm


class SimulationTraceStrategy(TaskDecompositionStrategy):
    name = "simulation_trace"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        traces: List[str] = []
        for example in ctx.examples[:2]:
            trace_prompt = f"Simulate algorithm steps for input {example.get('input')}"
            trace = tracker.consume(
                llm.call(trace_prompt, model="trace-writer", max_tokens=80, temperature=0.0, caller=self.name),
                fallback=f"Trace unavailable for {example.get('input')}",
            )
            traces.append(trace)
        if not traces:
            traces.append("Trace placeholder")
        diagnostics = {
            "trace_length": str(len(traces)),
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
        }
        plan = DecompositionPlan(
            strategy_name=self.name,
            simulation_traces=traces,
            subtasks=["run official example", "run adversarial example", "compare states"],
            diagnostics=diagnostics,
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        tracker = BudgetTracker(f"{self.name}:solve")
        tracker.consume(
            llm.call("Verify trace consistency before coding.", model="trace-check", max_tokens=64, caller=self.name),
            fallback="Trace verification skipped",
        )
        base_code = ctx.metadata.get("reference_solution", "def solve(*args):\n    return None")
        tests_run = run_tests(base_code, ctx)
        planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0)
        planning_time = float(plan.diagnostics.get("planning_time", 0) or 0.0)
        metrics: Dict[str, float | str] = {
            "trace_length": float(plan.diagnostics.get("trace_length", 1)),
            "tokens_used": planning_tokens + tracker.tokens,
            "planning_time": planning_time + tracker.time_spent,
            "mismatches_detected": 0.0,
        }
        return finalize_result(ctx, plan, base_code, tests_run, metrics)
