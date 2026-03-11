"""Helpers to summarise decomposition plans for logging."""
from __future__ import annotations

from typing import Any, Dict

from src.decomposition.interfaces import DecompositionPlan, StrategyResult

from .result_schema import DecompositionSummary


def _summarize_plan(plan: DecompositionPlan) -> Dict[str, Any]:
    return {
        "contract": plan.contract,
        "patterns": plan.patterns,
        "subtasks": plan.subtasks,
        "tests": plan.tests,
        "simulation_traces": plan.simulation_traces,
        "role_messages": plan.role_messages,
        "diagnostics": plan.diagnostics,
    }


def summarize_strategy_result(result: StrategyResult) -> DecompositionSummary:
    plan = result.plan
    plan_snapshot = _summarize_plan(plan)
    notes: Dict[str, Any] = {
        "tests_defined": len(plan.tests),
        "patterns": plan.patterns,
        "simulation_traces": plan.simulation_traces,
    }
    if plan.diagnostics:
        notes["diagnostics"] = plan.diagnostics
    notes["plan_snapshot"] = plan_snapshot
    contract = plan.contract or ""
    return DecompositionSummary(
        strategy=plan.strategy_name,
        num_subtasks=len(plan.subtasks),
        num_tests=len(plan.tests),
        plan_contract=contract,
        notes=notes,
    )
