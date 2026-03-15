"""Shared helpers for auditing and validating public-repo pilot traces."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from src.decomposition.real_repo.strict_logging import STRICT_TRACE_FILENAME


REQUIRED_FLAGS = (
    "has_contract_items",
    "has_active_clause",
    "has_regression_guards",
    "has_witnesses",
    "has_payload",
    "has_candidate_files",
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _iter_round_entries(logs_dir: Path) -> Iterator[Dict[str, Any]]:
    for edits_file in sorted(logs_dir.glob("edits_round*.json")):
        data = _load_json(edits_file)
        if isinstance(data, dict):
            rounds = data.get("rounds")
            if isinstance(rounds, list) and rounds:
                for entry in rounds:
                    if isinstance(entry, dict):
                        yield entry
            elif isinstance(data, dict):
                yield data
    for trace_file in sorted(logs_dir.glob("*trace*.json")):
        data = _load_json(trace_file)
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    yield entry
        elif isinstance(data, dict):
            yield data
    strict_path = logs_dir / STRICT_TRACE_FILENAME
    if strict_path.exists():
        yield from _iter_jsonl(strict_path)


def _round_flags(round_data: Dict[str, Any]) -> Tuple[Dict[str, bool], List[str], str]:
    metadata = round_data.get("metadata") or {}
    edit_metadata = round_data.get("edit_metadata") or metadata
    cgcs_state = edit_metadata.get("cgcs_state") or {}
    strict_entry = round_data.get("strict_trace") or edit_metadata.get("strict_trace") or {}

    def _extract(field: str) -> Tuple[bool, Any]:
        for container in (round_data, metadata, edit_metadata, strict_entry, cgcs_state):
            if isinstance(container, dict) and field in container:
                value = container[field]
                if value is None:
                    return False, None
                if isinstance(value, str):
                    return (bool(value.strip()), value)
                return True, value
        return False, None

    has_contract_items, _ = _extract("contract_items")
    has_active_clause, _ = _extract("active_clause_id")
    if not has_active_clause:
        has_active_clause, _ = _extract("active_clause")
    has_witnesses, _ = _extract("witnesses")
    if not has_witnesses:
        has_witnesses, _ = _extract("witness_sample")
    payload_present, _ = _extract("raw_edit_payload")
    if not payload_present:
        payload_present, _ = _extract("edit_payload")
    candidate_files_present, _ = _extract("candidate_files")
    if not candidate_files_present and round_data.get("files_touched"):
        candidate_files_present = True
    guards_present, _ = _extract("regression_guard_ids")
    if not guards_present:
        guards_present, _ = _extract("regression_guards")
    row_quality_present, _ = _extract("row_quality")

    flags = {
        "has_contract_items": has_contract_items,
        "has_active_clause": has_active_clause,
        "has_witnesses": has_witnesses,
        "has_payload": payload_present,
        "has_candidate_files": candidate_files_present,
        "has_regression_guards": guards_present,
        "has_row_quality": row_quality_present,
        "ready_for_strict": has_contract_items and has_active_clause and payload_present,
    }
    missing = [key for key, val in flags.items() if not val and key in REQUIRED_FLAGS]
    status = str(
        round_data.get("status")
        or round_data.get("round_status")
        or edit_metadata.get("round_status")
        or "unknown"
    ).lower()
    return flags, missing, status


def audit_strategy_logs(logs_dir: Path) -> Dict[str, Any]:
    rounds_total = 0
    totals: Counter[str] = Counter()
    missing_fields: Counter[str] = Counter()
    failure_categories: Counter[str] = Counter()

    for round_entry in _iter_round_entries(logs_dir):
        rounds_total += 1
        flags, missing, status = _round_flags(round_entry)
        for key, present in flags.items():
            if present:
                totals[key] += 1
        for field in missing:
            missing_fields[field] += 1
        if status:
            failure_categories[status] += 1

    return {
        "rounds_total": rounds_total,
        "rounds_with_contract_items": totals["has_contract_items"],
        "rounds_with_active_clause": totals["has_active_clause"],
        "rounds_with_witnesses": totals["has_witnesses"],
        "rounds_with_payload": totals["has_payload"],
        "rounds_with_candidate_files": totals["has_candidate_files"],
        "rounds_with_regression_guards": totals["has_regression_guards"],
        "rounds_with_row_quality": totals["has_row_quality"],
        "rounds_ready_for_strict": totals["ready_for_strict"],
        "missing_fields": dict(missing_fields),
        "failure_categories": dict(failure_categories),
    }


def audit_runs_root(runs_root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    per_run: List[Dict[str, Any]] = []
    aggregate_totals: Counter[str] = Counter()
    aggregate_missing: Counter[str] = Counter()
    aggregate_failures: Counter[str] = Counter()

    if not runs_root.exists():
        return [], {"error": f"{runs_root} not found"}

    for task_dir in sorted(runs_root.iterdir()):
        if not task_dir.is_dir():
            continue
        task_id = task_dir.name
        for strategy_dir in sorted(task_dir.iterdir()):
            if not strategy_dir.is_dir():
                continue
            logs_dir = strategy_dir / "logs"
            if not logs_dir.exists():
                continue
            audit = audit_strategy_logs(logs_dir)
            audit["task_id"] = task_id
            audit["strategy"] = strategy_dir.name
            per_run.append(audit)
            for key, value in audit.items():
                if isinstance(value, int):
                    aggregate_totals[key] += value
            for field, count in audit.get("missing_fields", {}).items():
                aggregate_missing[field] += count
            for failure, count in audit.get("failure_categories", {}).items():
                aggregate_failures[failure] += count

    aggregate = {
        "tasks_audited": len({item["task_id"] for item in per_run}),
        "strategy_runs_audited": len(per_run),
        "rounds_total": aggregate_totals["rounds_total"],
        "rounds_with_contract_items": aggregate_totals["rounds_with_contract_items"],
        "rounds_with_active_clause": aggregate_totals["rounds_with_active_clause"],
        "rounds_with_witnesses": aggregate_totals["rounds_with_witnesses"],
        "rounds_with_payload": aggregate_totals["rounds_with_payload"],
        "rounds_with_candidate_files": aggregate_totals["rounds_with_candidate_files"],
        "rounds_with_regression_guards": aggregate_totals["rounds_with_regression_guards"],
        "rounds_with_row_quality": aggregate_totals["rounds_with_row_quality"],
        "rounds_ready_for_strict": aggregate_totals["rounds_ready_for_strict"],
        "missing_field_counts": dict(aggregate_missing),
        "failure_categories": dict(aggregate_failures),
    }
    return per_run, aggregate


def validate_trace_requirements(logs_dir: Path) -> Tuple[bool, List[str]]:
    audit = audit_strategy_logs(logs_dir)
    missing: List[str] = []
    for field in REQUIRED_FLAGS:
        if audit.get("rounds_total", 0) == 0:
            missing.append("no_rounds_recorded")
            break
        if audit[f"rounds_with_{field.split('_', 1)[1]}"] == 0:
            missing.append(field)
    ready = not missing
    return ready, missing
