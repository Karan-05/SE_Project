"""Contract-first decomposition strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.agentic import execute_plan_with_repair
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import BudgetTracker
from src.decomposition.agentic.semantic import get_semantic_config
from src.providers import llm


class ContractFirstStrategy(TaskDecompositionStrategy):
    """Enforce explicit input/output contracts before generating code."""

    name = "contract_first"
    REQUIRED_FIELDS = ["inputs", "outputs", "constraints", "edge_cases"]

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        tracker = BudgetTracker(f"{self.name}:plan")
        def _format_example(example: Dict[str, object]) -> str:
            value = example.get("input", "")
            return str(value)

        contract = {
            "inputs": ctx.metadata.get("inputs", "Underspecified"),
            "outputs": ctx.metadata.get("outputs", "Underspecified"),
            "constraints": ctx.constraints or ctx.metadata.get("constraints", ""),
            "edge_cases": ", ".join(_format_example(ec) for ec in ctx.examples) if ctx.examples else "None",
        }
        missing = [field for field, value in contract.items() if not value]
        audit_prompt = (
            "Review this contract for completeness and note any missing guarantees. "
            f"Contract: {contract}. Problem: {ctx.problem_statement[:300]}"
        )
        audit_summary = tracker.consume(
            llm.call(audit_prompt, model="contract-auditor", max_tokens=96, temperature=0.0, caller=self.name),
            fallback="Audit skipped due to LLM budget",
        )
        diagnostics = {
            "missing_fields": ",".join(missing) if missing else "",
            "contract_length": str(sum(len(str(v)) for v in contract.values())),
            "audit_note": audit_summary,
            "planning_tokens": str(tracker.tokens),
            "planning_time": f"{tracker.time_spent:.6f}",
        }
        subtasks: List[str] = [
            "Validate inputs vs contract",
            "Implement core logic",
            "Check edge cases",
        ]
        plan = DecompositionPlan(
            strategy_name=self.name,
            contract=contract,
            subtasks=subtasks,
            tests=[ex.get("output", "") for ex in ctx.examples],
            diagnostics=diagnostics,
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        completeness = sum(1 for field in self.REQUIRED_FIELDS if plan.contract.get(field)) / len(self.REQUIRED_FIELDS)
        config = get_semantic_config(self.name)
        metrics: Dict[str, float | str] = {
            "contract_completeness": round(completeness, 2),
            "semantic_variant": config.name,
        }
        return execute_plan_with_repair(
            ctx,
            plan,
            strategy_name=self.name,
            extra_metrics=metrics,
            semantic_config=config,
        )


class ContractFirstBaselineStrategy(ContractFirstStrategy):
    """Baseline variant without checklist/critic for ablations."""

    name = "contract_first_baseline"


class ContractFirstChecklistStrategy(ContractFirstStrategy):
    """Checklist-only ablation."""

    name = "contract_first_checklist"


class ContractFirstSemanticStrategy(ContractFirstStrategy):
    """Alias exposing the full semantic stack explicitly."""

    name = "contract_first_semantic"
