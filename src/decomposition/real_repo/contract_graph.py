"""Contract graph tracking for CGCS clause selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.decomposition.real_repo.contracts import ContractCoverageResult, ContractItem
from src.decomposition.real_repo.witnesses import SemanticWitness, link_witnesses_to_contract, witness_signature


@dataclass
class ContractNodeState:
    """State of a single contract clause over multiple repair rounds."""

    contract_id: str
    status: str = "pending"
    satisfied_round: Optional[int] = None
    regressed_round: Optional[int] = None
    witness_signatures: List[str] = field(default_factory=list)


@dataclass
class ContractGraphState:
    """Collection of contract nodes plus aggregate tracking."""

    nodes: Dict[str, ContractNodeState] = field(default_factory=dict)
    satisfied_ids: List[str] = field(default_factory=list)
    unsatisfied_ids: List[str] = field(default_factory=list)
    regressed_ids: List[str] = field(default_factory=list)
    active_clause_id: Optional[str] = None
    regression_guard_ids: List[str] = field(default_factory=list)
    clause_history: List[str] = field(default_factory=list)
    contract_items: Dict[str, ContractItem] = field(default_factory=dict)
    witness_index: Dict[str, List[SemanticWitness]] = field(default_factory=dict)
    last_round_updated: Optional[int] = None
    last_clause_reason: str = ""


def build_contract_graph(contract_items: Sequence[ContractItem]) -> ContractGraphState:
    """Initialize graph state for the provided contract entries."""

    nodes = {item.id: ContractNodeState(contract_id=item.id) for item in contract_items}
    active_clause = next(iter(nodes.keys()), None)
    item_map = {item.id: item for item in contract_items}
    state = ContractGraphState(
        nodes=nodes,
        satisfied_ids=[],
        unsatisfied_ids=list(nodes.keys()),
        regressed_ids=[],
        active_clause_id=active_clause,
        regression_guard_ids=[],
        clause_history=[],
        contract_items=item_map,
        witness_index={},
        last_round_updated=None,
        last_clause_reason="initial_clause_seed" if active_clause else "",
    )
    return state


def _apply_failure_mapping(
    state: ContractGraphState,
    witnesses: Sequence[SemanticWitness],
) -> None:
    """Populate witness index for each clause based on test evidence."""

    if not state.nodes:
        state.witness_index = {}
        return
    linked = link_witnesses_to_contract(state.contract_items.values(), witnesses)
    index: Dict[str, List[SemanticWitness]] = {}
    for cid in state.nodes:
        index[cid] = list(linked.get(cid, []))
    state.witness_index = index
    for cid, node in state.nodes.items():
        assigned = index.get(cid, [])
        node.witness_signatures = [witness_signature(wit) for wit in assigned]


def update_from_run(
    state: ContractGraphState,
    coverage_result: ContractCoverageResult,
    witnesses: Sequence[SemanticWitness],
    round_index: int,
) -> ContractGraphState:
    """Update node statuses with the latest contract coverage and witnesses."""

    state.last_round_updated = round_index
    _apply_failure_mapping(state, witnesses)
    satisfied_set = set(coverage_result.satisfied_ids)
    unsatisfied_set = set(coverage_result.unsatisfied_ids)
    new_satisfied: List[str] = []
    new_unsatisfied: List[str] = []
    for cid, node in state.nodes.items():
        was_satisfied = node.status == "satisfied"
        if cid in satisfied_set:
            node.status = "satisfied"
            if node.satisfied_round is None:
                node.satisfied_round = round_index
            node.regressed_round = None
            new_satisfied.append(cid)
        elif cid in unsatisfied_set:
            if node.satisfied_round is not None and not was_satisfied:
                # Already flagged as regressed, keep previous round.
                node.status = "regressed"
            elif node.satisfied_round is not None and was_satisfied:
                node.status = "regressed"
                node.regressed_round = round_index
            elif node.status == "regressed":
                node.regressed_round = node.regressed_round or round_index
            else:
                node.status = "unsatisfied"
            new_unsatisfied.append(cid)
        else:
            if node.status not in {"satisfied"}:
                node.status = "pending"
            if node.status != "satisfied":
                new_unsatisfied.append(cid)
    state.satisfied_ids = sorted(satisfied_set)
    state.regressed_ids = sorted(
        cid for cid, node in state.nodes.items() if node.status == "regressed"
    )
    state.unsatisfied_ids = sorted({cid for cid in new_unsatisfied if cid not in state.regressed_ids})
    state.regression_guard_ids = sorted(
        cid for cid, node in state.nodes.items() if node.status == "satisfied"
    )
    return state


def choose_next_clause(state: ContractGraphState) -> Tuple[Optional[str], str]:
    """Select the next active clause with priority on regressions and witness volume."""

    def _score_candidates(candidates: Iterable[str]) -> Tuple[Optional[str], int]:
        best_id: Optional[str] = None
        best_score = (-1, "")
        witness_count = 0
        for cid in candidates:
            node = state.nodes.get(cid)
            if not node:
                continue
            current_count = len(node.witness_signatures)
            score = (current_count, cid)
            if best_id is None or score > best_score:
                best_id = cid
                best_score = score
                witness_count = current_count
        return best_id, witness_count

    next_clause = None
    witness_score = 0
    source = "complete"
    for label, candidates in (("regressed", state.regressed_ids), ("unsatisfied", state.unsatisfied_ids)):
        candidate, witness_count = _score_candidates(candidates)
        if candidate:
            next_clause = candidate
            witness_score = witness_count
            source = label
            break
    if not next_clause:
        unresolved = [cid for cid, node in state.nodes.items() if node.status not in {"satisfied"}]
        candidate, witness_count = _score_candidates(unresolved)
        if candidate:
            next_clause = candidate
            witness_score = witness_count
            source = "pending"
    reason_map = {
        "regressed": "regressed_clause_priority",
        "unsatisfied": "unsatisfied_clause_priority",
        "pending": "pending_clause_priority",
        "complete": "all_clauses_satisfied",
    }
    reason = reason_map.get(source, "unspecified")
    if witness_score > 0 and next_clause:
        reason = f"{reason}_most_witnesses"
    state.active_clause_id = next_clause
    state.last_clause_reason = reason
    if next_clause:
        state.clause_history.append(next_clause)
    return next_clause, reason


__all__ = [
    "ContractGraphState",
    "ContractNodeState",
    "build_contract_graph",
    "choose_next_clause",
    "update_from_run",
]
