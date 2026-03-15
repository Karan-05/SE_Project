"""Contract-Graph Counterexample Satisfaction strategy."""
from __future__ import annotations

from typing import Dict, List

from src.decomposition.agentic import RepairPolicy, execute_plan_with_repair
from src.decomposition.agentic.semantic import get_semantic_config
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.real_repo.contracts import contract_items_to_dicts, get_contract_items


class CGCSStrategy(TaskDecompositionStrategy):
    """Clause-driven strategy that follows the CGCS contract graph."""

    name = "cgcs"

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        items = get_contract_items(metadata)
        contract_dicts = contract_items_to_dicts(items)
        clause_labels = [f"contract::{item.id}" for item in items]
        contract_payload: Dict[str, object] = {
            "clauses": [item.description for item in items],
            "categories": [item.category for item in items],
            "mapping": {item.id: item.description for item in items},
        }
        diagnostics = {
            "contract_clause_count": str(len(items)),
            "contract_ids": ",".join(item.id for item in items),
        }
        candidate_files = metadata.get("implementation_target_files") or metadata.get("repo_target_files") or []
        plan = DecompositionPlan(
            strategy_name=self.name,
            contract_items=contract_dicts,
            contract=contract_payload,
            subtasks=clause_labels or ["stabilize_repo_contracts"],
            tests=[],
            diagnostics=diagnostics,
            target_files=metadata.get("repo_target_files") or [],
            candidate_files=list(candidate_files),
        )
        return plan

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        clause_count = len(get_contract_items(metadata))
        policy = RepairPolicy(
            localized=True,
            allow_monolithic_fallback=False,
            description="cgcs_clause",
            clause_driven=True,
        ) if clause_count else None
        metrics = {
            "cgcs_clause_count": float(clause_count),
        }
        config = get_semantic_config(self.name)
        return execute_plan_with_repair(
            ctx,
            plan,
            strategy_name=self.name,
            policy=policy,
            semantic_config=config,
            extra_metrics=metrics,
        )
