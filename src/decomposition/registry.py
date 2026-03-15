"""Registry mapping strategy identifiers to implementations."""
from __future__ import annotations

from typing import Dict

from src.decomposition.interfaces import TaskDecompositionStrategy
from src.decomposition.strategies.contract_first import (
    ContractFirstStrategy,
    ContractFirstBaselineStrategy,
    ContractFirstChecklistStrategy,
    ContractFirstSemanticStrategy,
)
from src.decomposition.strategies.pattern_skeleton import PatternSkeletonStrategy
from src.decomposition.strategies.failure_mode_first import (
    FailureModeFirstStrategy,
    FailureModeFirstBaselineStrategy,
    FailureModeFirstChecklistStrategy,
    FailureModeFirstSemanticStrategy,
)
from src.decomposition.strategies.multi_view import MultiViewStrategy
from src.decomposition.strategies.semantic_diff import SemanticDiffStrategy
from src.decomposition.strategies.role_decomposed import RoleDecomposedStrategy
from src.decomposition.strategies.simulation_trace import SimulationTraceStrategy
from src.decomposition.strategies.direct_baseline import DirectBaselineStrategy
from src.decomposition.strategies.cgcs import CGCSStrategy


STRATEGIES: Dict[str, TaskDecompositionStrategy] = {
    "direct_baseline": DirectBaselineStrategy(),
    "contract_first": ContractFirstStrategy(),
    "contract_first_semantic": ContractFirstSemanticStrategy(),
    "contract_first_baseline": ContractFirstBaselineStrategy(),
    "contract_first_checklist": ContractFirstChecklistStrategy(),
    "pattern_skeleton": PatternSkeletonStrategy(),
    "failure_mode_first": FailureModeFirstStrategy(),
    "failure_mode_first_semantic": FailureModeFirstSemanticStrategy(),
    "failure_mode_first_baseline": FailureModeFirstBaselineStrategy(),
    "failure_mode_first_checklist": FailureModeFirstChecklistStrategy(),
    "multi_view": MultiViewStrategy(),
    "semantic_diff": SemanticDiffStrategy(),
    "role_decomposed": RoleDecomposedStrategy(),
    "simulation_trace": SimulationTraceStrategy(),
    "cgcs": CGCSStrategy(),
}


def get_strategy(name: str) -> TaskDecompositionStrategy:
    try:
        return STRATEGIES[name]
    except KeyError as exc:  # pragma: no cover
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGIES)}") from exc
