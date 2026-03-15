#!/usr/bin/env python3
"""Audit CGCS runtime traces for strict dataset readiness."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from src.config import PathConfig


def _iter_trace_files(trace_root: Path) -> Iterable[Path]:
    if not trace_root.exists():
        return []
    for strategy_dir in trace_root.iterdir():
        if not strategy_dir.is_dir():
            continue
        for trace_file in strategy_dir.glob("*.json"):
            yield trace_file


def _load_rounds(trace_file: Path) -> Iterable[Dict[str, object]]:
    try:
        payload = json.loads(trace_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload.get("rounds", [])


def _coerce_list(value: object) -> List[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _round_ready(contract_items: List[object], active_clause: str, witnesses: List[object], raw_payload: str) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    ready = True
    if not contract_items:
        reasons.append("missing_contract_items")
        ready = False
    if not active_clause:
        reasons.append("missing_active_clause_id")
        ready = False
    if not witnesses and not raw_payload:
        reasons.append("missing_witness_and_payload")
        ready = False
    return ready, reasons


def audit_trace_dir(trace_root: Path) -> Dict[str, object]:
    stats = {
        "total_rounds": 0,
        "rounds_with_contract_items": 0,
        "rounds_with_active_clause_id": 0,
        "rounds_with_regression_guard_ids": 0,
        "rounds_with_witnesses": 0,
        "rounds_with_raw_edit_payload": 0,
        "rounds_with_candidate_files": 0,
        "rounds_payload_parse_failed": 0,
        "rounds_with_weak_contracts": 0,
        "rounds_ready_for_strict_dataset": 0,
    }
    failure_reasons: Counter[str] = Counter()
    for trace_file in _iter_trace_files(trace_root):
        for round_entry in _load_rounds(trace_file):
            stats["total_rounds"] += 1
            edit_meta = round_entry.get("edit_metadata") or {}
            cgcs_state = edit_meta.get("cgcs_state") or {}
            contract_items = _coerce_list(cgcs_state.get("contract_items") or edit_meta.get("contract_items"))
            if contract_items:
                stats["rounds_with_contract_items"] += 1
            active_clause = (
                str(edit_meta.get("active_clause_id") or cgcs_state.get("active_clause_id") or cgcs_state.get("active_clause") or "")
            )
            if active_clause:
                stats["rounds_with_active_clause_id"] += 1
            regression_guards = _coerce_list(
                edit_meta.get("regression_guard_ids") or cgcs_state.get("regression_guard_ids") or cgcs_state.get("regression_guards")
            )
            if regression_guards:
                stats["rounds_with_regression_guard_ids"] += 1
            witnesses = _coerce_list(edit_meta.get("witnesses") or cgcs_state.get("witnesses"))
            if witnesses:
                stats["rounds_with_witnesses"] += 1
            raw_payload = str(edit_meta.get("raw_edit_payload") or "").strip()
            if raw_payload:
                stats["rounds_with_raw_edit_payload"] += 1
            candidate_files = _coerce_list(edit_meta.get("candidate_files") or cgcs_state.get("candidate_files"))
            if candidate_files:
                stats["rounds_with_candidate_files"] += 1
            payload_ok = bool(edit_meta.get("payload_parse_ok"))
            if not payload_ok:
                stats["rounds_payload_parse_failed"] += 1
            row_quality = edit_meta.get("row_quality") or cgcs_state.get("row_quality") or {}
            if (row_quality.get("contract_quality") or "").lower() == "weak":
                stats["rounds_with_weak_contracts"] += 1
            ready, reasons = _round_ready(contract_items, active_clause, witnesses, raw_payload)
            if ready:
                stats["rounds_ready_for_strict_dataset"] += 1
            else:
                failure_reasons.update(reasons)
            if not payload_ok and raw_payload:
                failure_reasons.update(["payload_parse_failed"])
    return {
        **stats,
        "failure_reasons": failure_reasons.most_common(),
    }


def _write_summary(output_dir: Path, summary: Dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "trace_quality_summary.json"
    md_path = output_dir / "trace_quality_summary.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Trace Quality Summary",
        "",
        f"- Total rounds: {summary['total_rounds']}",
        f"- Rounds ready for strict dataset: {summary['rounds_ready_for_strict_dataset']}",
        f"- Rounds with contract items: {summary['rounds_with_contract_items']}",
        f"- Rounds with active clause id: {summary['rounds_with_active_clause_id']}",
        f"- Rounds with witnesses: {summary['rounds_with_witnesses']}",
        f"- Rounds with raw payload: {summary['rounds_with_raw_edit_payload']}",
        f"- Rounds with candidate files: {summary['rounds_with_candidate_files']}",
        f"- Payload parse failures: {summary['rounds_payload_parse_failed']}",
        "",
        "## Top failure reasons",
    ]
    failures = summary.get("failure_reasons") or []
    if not failures:
        lines.append("- none")
    else:
        for reason, count in failures[:10]:
            lines.append(f"- {reason}: {count}")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Audit CGCS trace quality.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=PathConfig().reports_root / "decomposition" / "real_world" / "real_repo_tiny",
        help="Directory containing tiny run outputs (expects traces/ subdir).",
    )
    args = parser.parse_args()
    trace_root = args.input_dir / "traces"
    summary = audit_trace_dir(trace_root)
    _write_summary(args.input_dir, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
