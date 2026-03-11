"""Simulation-trace / hierarchical reasoning strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.agentic import execute_plan_with_repair
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker
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
        metrics: Dict[str, float | str] = {
            "trace_length": float(plan.diagnostics.get("trace_length", 1)),
        }
        return execute_plan_with_repair(ctx, plan, strategy_name=self.name, extra_metrics=metrics)
