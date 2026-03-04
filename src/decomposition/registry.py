"""Registry mapping strategy identifiers to implementations."""
from __future__ import annotations

from typing import Dict

from src.decomposition.interfaces import TaskDecompositionStrategy
from src.decomposition.strategies.contract_first import ContractFirstStrategy
from src.decomposition.strategies.pattern_skeleton import PatternSkeletonStrategy
from src.decomposition.strategies.failure_mode_first import FailureModeFirstStrategy
from src.decomposition.strategies.multi_view import MultiViewStrategy
from src.decomposition.strategies.semantic_diff import SemanticDiffStrategy
from src.decomposition.strategies.role_decomposed import RoleDecomposedStrategy
from src.decomposition.strategies.simulation_trace import SimulationTraceStrategy


STRATEGIES: Dict[str, TaskDecompositionStrategy] = {
    "contract_first": ContractFirstStrategy(),
    "pattern_skeleton": PatternSkeletonStrategy(),
    "failure_mode_first": FailureModeFirstStrategy(),
    "multi_view": MultiViewStrategy(),
    "semantic_diff": SemanticDiffStrategy(),
    "role_decomposed": RoleDecomposedStrategy(),
    "simulation_trace": SimulationTraceStrategy(),
}


def get_strategy(name: str) -> TaskDecompositionStrategy:
    try:
        return STRATEGIES[name]
    except KeyError as exc:  # pragma: no cover
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGIES)}") from exc
