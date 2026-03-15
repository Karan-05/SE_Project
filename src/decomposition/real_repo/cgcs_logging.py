"""Structured instrumentation for CGCS runtime traces."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from src.decomposition.real_repo.contracts import classify_contract_quality
from src.decomposition.real_repo.witnesses import SemanticWitness, witness_signature


def _serialize_witnesses(witnesses: Sequence[SemanticWitness]) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    seen: set[str] = set()
    for witness in witnesses:
        signature = witness_signature(witness)
        if signature in seen:
            continue
        seen.add(signature)
        entries.append(
            {
                "signature": signature,
                "test_case": witness.test_case,
                "message": witness.message,
                "expected": witness.expected,
                "actual": witness.actual,
                "location": witness.location,
                "category": witness.category,
                "linked_contract_ids": list(witness.linked_contract_ids),
            }
        )
    return entries


def _normalize_list(items: Optional[Iterable[object]]) -> List[object]:
    if not items:
        return []
    return [item for item in items]


@dataclass
class CGCSRoundTrace:
    """Stable per-round trace emitted for CGCS instrumentation."""

    round_index: int
    strategy: str
    task_id: str
    contract_items: List[Dict[str, object]]
    active_clause_id: str
    regression_guard_ids: List[str]
    witnesses: List[Dict[str, object]]
    raw_edit_payload: str
    payload_parse_ok: bool
    payload_parse_error: Optional[str]
    candidate_files: List[str]
    candidate_files_raw: List[str]
    candidate_files_filtered: List[str]
    clause_selection_reason: str
    row_quality: Dict[str, object]
    lint_errors: List[str] = field(default_factory=list)
    skipped_targets: List[object] = field(default_factory=list)
    outcome_metrics: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "round": self.round_index,
            "round_index": self.round_index,
            "strategy": self.strategy,
            "task_id": self.task_id,
            "contract_items": self.contract_items,
            "active_clause_id": self.active_clause_id,
            "active_clause": self.active_clause_id,
            "regression_guard_ids": self.regression_guard_ids,
            "witnesses": self.witnesses,
            "raw_edit_payload": self.raw_edit_payload,
            "payload_parse_ok": self.payload_parse_ok,
            "payload_parse_error": self.payload_parse_error or "",
            "candidate_files": self.candidate_files,
            "candidate_files_raw": self.candidate_files_raw,
            "candidate_files_filtered": self.candidate_files_filtered,
            "clause_selection_reason": self.clause_selection_reason,
            "row_quality": self.row_quality,
            "lint_errors": self.lint_errors,
            "skipped_targets": self.skipped_targets,
            "outcome_metrics": self.outcome_metrics,
        }


def build_cgcs_round_trace(
    *,
    task_id: str,
    strategy: str,
    round_index: int,
    contract_items: Sequence[Dict[str, object]],
    active_clause_id: str,
    regression_guard_ids: Sequence[str],
    witnesses: Sequence[SemanticWitness],
    raw_edit_payload: str,
    payload_parse_ok: bool,
    payload_parse_error: Optional[str],
    candidate_files_raw: Sequence[str],
    candidate_files_filtered: Sequence[str],
    clause_selection_reason: str,
    lint_errors: Sequence[str],
    skipped_targets: Sequence[object],
    outcome_metrics: Dict[str, object],
    strategy_mode: str = "cgcs",
    used_fallback: bool = False,
) -> CGCSRoundTrace:
    serialized_witnesses = _serialize_witnesses(witnesses)
    witness_signatures = {entry["signature"] for entry in serialized_witnesses if entry.get("signature")}
    contract_quality = classify_contract_quality(contract_items)
    row_quality = {
        "contract_quality": contract_quality,
        "contract_item_count": len(contract_items),
        "active_clause_source": clause_selection_reason or "",
        "active_clause_present": bool(active_clause_id),
        "witness_count": len(serialized_witnesses),
        "witness_unique_count": len(witness_signatures),
        "payload_present": bool(raw_edit_payload.strip()),
        "payload_parse_ok": payload_parse_ok,
        "candidate_file_count": len(candidate_files_filtered),
        "clause_selection_reason": clause_selection_reason,
        "skipped_targets_present": bool(skipped_targets),
        "lint_error_count": len(lint_errors),
        "used_fallback": bool(used_fallback),
        "strategy_mode": strategy_mode,
        "regression_guard_count": len(regression_guard_ids),
    }
    if payload_parse_error:
        row_quality["payload_parse_error"] = payload_parse_error
    trace = CGCSRoundTrace(
        round_index=round_index,
        strategy=strategy,
        task_id=task_id,
        contract_items=[dict(item) for item in contract_items],
        active_clause_id=active_clause_id,
        regression_guard_ids=[str(cid) for cid in regression_guard_ids],
        witnesses=serialized_witnesses,
        raw_edit_payload=raw_edit_payload or "",
        payload_parse_ok=payload_parse_ok,
        payload_parse_error=payload_parse_error or "",
        candidate_files=list(candidate_files_filtered),
        candidate_files_raw=list(candidate_files_raw),
        candidate_files_filtered=list(candidate_files_filtered),
        clause_selection_reason=clause_selection_reason or "",
        row_quality=row_quality,
        lint_errors=[str(err) for err in lint_errors] if lint_errors else [],
        skipped_targets=_normalize_list(skipped_targets),
        outcome_metrics=outcome_metrics,
    )
    return trace


__all__ = ["CGCSRoundTrace", "build_cgcs_round_trace"]
