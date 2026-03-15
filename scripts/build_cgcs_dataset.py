#!/usr/bin/env python3
"""Build CGCS dataset JSONL files from real-repo traces and run logs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from src.config import PathConfig

ContractPayload = Union[List[Dict[str, Any]], Dict[str, Any]]

PLACEHOLDER_KEYS = {"inputs", "outputs", "constraints", "edge_cases"}
PLACEHOLDER_TOKENS = {"underspecified", "tbd", "todo", "none", "n/a"}
DISALLOWED_FILE_PATTERNS = (
    "node_modules/",
    "/node_modules/",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".package-lock.json",
)


@dataclass
class CGCSDatasetRow:
    task_id: str
    strategy: str
    round_index: int
    split: str
    repo_snapshot_sha256: str
    contract_items: ContractPayload
    active_clause_id: str
    regression_guard_ids: List[str]
    witnesses: List[Dict[str, Any]]
    candidate_files: List[str]
    context_snippets: List[Any]
    raw_edit_payload: str
    outcome_metrics: Dict[str, Any]
    oracle_patch_present: bool
    source_paths: Dict[str, str]
    row_quality: Dict[str, Any] = field(default_factory=dict)
    row_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetBuildOptions:
    strict: bool = False
    allow_placeholder_contracts: bool = False
    allow_empty_payload: bool = False
    include_tests: bool = False
    max_records: Optional[int] = None
    seed: Optional[int] = None


def _default_run_root() -> Path:
    return PathConfig().reports_root / "decomposition" / "real_world" / "real_repo" / "runs"


def _default_trace_root() -> Path:
    return PathConfig().reports_root / "decomposition" / "traces"


def _iter_strategy_runs(run_root: Path) -> Iterator[Tuple[str, str, Path, Path]]:
    for task_dir in sorted(run_root.iterdir()):
        if not task_dir.is_dir():
            continue
        for strategy_dir in sorted(task_dir.iterdir()):
            if not strategy_dir.is_dir():
                continue
            if strategy_dir.name == "oracle_teacher":
                continue
            logs_dir = strategy_dir / "logs"
            if not logs_dir.exists():
                continue
            yield task_dir.name, strategy_dir.name, task_dir, logs_dir


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _split_for_record(task_id: str, strategy: str, seed: Optional[int]) -> str:
    key = f"{task_id}:{strategy}"
    if seed is not None:
        key = f"{key}:{seed}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "dev"
    return "test"


def _clean_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _iter_dicts(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item


def _coerce_str_list(payload: Any) -> List[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    if isinstance(payload, tuple):
        return [str(item).strip() for item in payload if str(item).strip()]
    return [str(payload).strip()] if str(payload).strip() else []


def _dedupe_preserve(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_placeholder_contract(payload: Any) -> bool:
    if isinstance(payload, dict):
        keys = {str(key).strip().lower() for key in payload.keys()}
        if keys and keys <= PLACEHOLDER_KEYS:
            values = [_clean_str(value).lower() for value in payload.values() if isinstance(value, str)]
            if values and all(any(token in val for token in PLACEHOLDER_TOKENS) or not val for val in values):
                return True
    if isinstance(payload, list):
        values = [_clean_str(item.get("description", "")).lower() for item in _iter_dicts(payload)]
        if values and all(any(token in val for token in PLACEHOLDER_TOKENS) or not val for val in values):
            return True
    return False


def extract_contract_items(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
) -> Tuple[ContractPayload, Dict[str, Any], List[str]]:
    plan = trace_entry.get("plan") or {}
    edit_metadata = round_entry.get("edit_metadata") or {}
    cgcs_state = edit_metadata.get("cgcs_state") or {}
    metadata = trace_entry.get("metadata") or {}
    sources: List[Tuple[str, Any]] = [
        ("round.edit_metadata.cgcs_state.contract_items", cgcs_state.get("contract_items")),
        ("round.edit_metadata.contract_items", edit_metadata.get("contract_items")),
        ("trace.metadata.contract_items", metadata.get("contract_items")),
        ("trace.metadata.contract", metadata.get("contract")),
        ("trace.plan.contract_items", plan.get("contract_items")),
        ("trace.plan.contract", plan.get("contract")),
        ("trace.contract", trace_entry.get("contract")),
    ]
    errors: List[str] = []
    quality: Dict[str, Any] = {}
    contract_payload: ContractPayload = []
    for source, payload in sources:
        if not payload:
            continue
        contract_payload = _normalize_contract_payload(payload)
        if contract_payload:
            quality["contract_items_source"] = source
            break
    placeholder = _is_placeholder_contract(contract_payload)
    if contract_payload:
        quality["contract_item_count"] = (
            len(contract_payload) if isinstance(contract_payload, list) else len(contract_payload)
        )
        quality["contract_quality"] = "weak" if placeholder else "ok"
    else:
        quality["contract_item_count"] = 0
        quality["contract_quality"] = "missing"
        errors.append("empty_contract_items")
    quality["contract_placeholder"] = placeholder
    return contract_payload, quality, errors


def _normalize_contract_payload(payload: Any) -> ContractPayload:
    if isinstance(payload, list):
        return [dict(item) for item in _iter_dicts(payload)]
    if isinstance(payload, dict):
        if "items" in payload and isinstance(payload["items"], list):
            return [dict(item) for item in _iter_dicts(payload["items"])]
        if "clauses" in payload and isinstance(payload["clauses"], list):
            return [dict(item) for item in _iter_dicts(payload["clauses"])]
        return dict(payload)
    return []


def extract_active_clause_id(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], List[str]]:
    edit_metadata = round_entry.get("edit_metadata") or {}
    cgcs_state = edit_metadata.get("cgcs_state") or {}
    sources: List[Tuple[str, Any]] = [
        ("round.edit_metadata.cgcs_state.active_clause_id", cgcs_state.get("active_clause_id")),
        ("round.edit_metadata.cgcs_state.active_clause", cgcs_state.get("active_clause")),
        ("round.active_clause_id", round_entry.get("active_clause_id")),
        ("round.edit_metadata.active_clause_id", edit_metadata.get("active_clause_id")),
    ]
    for source, value in sources:
        cleaned = _clean_str(value)
        if cleaned:
            return cleaned, {"active_clause_source": source}, []
    witness_sources = [
        cgcs_state.get("witness_sample"),
        cgcs_state.get("witness_samples"),
        edit_metadata.get("witness_sample"),
        edit_metadata.get("witness_samples"),
        round_entry.get("witness_sample"),
        round_entry.get("witness_samples"),
    ]
    for payload in witness_sources:
        for witness in _iter_dicts(payload):
            linked = _coerce_str_list(witness.get("linked_contract_ids"))
            if linked:
                return linked[0], {"active_clause_source": "witness_inference"}, []
    return "", {"active_clause_source": "missing"}, ["missing_active_clause_id"]


def extract_regression_guards(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
) -> Tuple[List[str], Dict[str, Any], List[str]]:
    edit_metadata = round_entry.get("edit_metadata") or {}
    cgcs_state = edit_metadata.get("cgcs_state") or {}
    sources: List[Tuple[str, Any]] = [
        ("round.edit_metadata.cgcs_state.regression_guards", cgcs_state.get("regression_guards")),
        ("round.edit_metadata.regression_guards", edit_metadata.get("regression_guards")),
        ("round.regression_guards", round_entry.get("regression_guards")),
        ("trace.regression_guards", trace_entry.get("regression_guards")),
    ]
    for source, payload in sources:
        guards = _coerce_str_list(payload)
        if guards:
            return guards, {"regression_guard_source": source, "regression_guard_count": len(guards)}, []
    return [], {"regression_guard_source": "missing", "regression_guard_count": 0}, []


def extract_candidate_files(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
    include_tests: bool = False,
) -> Tuple[List[str], Dict[str, Any], List[str]]:
    plan = trace_entry.get("plan") or {}
    raw_candidates: List[str] = []
    buckets = [
        plan.get("candidate_files"),
        round_entry.get("candidate_files"),
        round_entry.get("files_touched"),
        round_entry.get("applied_files"),
        round_entry.get("proposed_files"),
        log_data.get("candidate_files"),
        log_data.get("proposed_files"),
    ]
    for payload in buckets:
        if not payload:
            continue
        raw_candidates.extend([_clean_str(path) for path in payload if _clean_str(path)])
    raw_candidates = _dedupe_preserve(raw_candidates)
    filtered: List[str] = []
    removed: List[str] = []
    for path in raw_candidates:
        if _should_filter_candidate(path, include_tests=include_tests):
            removed.append(path)
            continue
        filtered.append(path)
    quality = {
        "candidate_files_raw": len(raw_candidates),
        "candidate_files_kept": len(filtered),
        "candidate_files_removed": removed,
        "candidate_files_raw_list": raw_candidates,
    }
    return filtered, quality, []


def _should_filter_candidate(path: str, include_tests: bool) -> bool:
    lowered = path.lower()
    if any(pattern in lowered for pattern in DISALLOWED_FILE_PATTERNS):
        return True
    if include_tests:
        return False
    if re.search(r"(^|/)(tests?|specs?)/", lowered):
        return True
    if lowered.endswith((".spec.js", ".spec.ts", ".test.js", ".test.ts")):
        return True
    if "/test" in lowered or lowered.startswith("test/"):
        return True
    return False


def extract_witnesses(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
    logs_dir: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    witnesses: List[Dict[str, Any]] = []
    quality: Dict[str, Any] = {"witness_sources": []}
    errors: List[str] = []
    edit_metadata = round_entry.get("edit_metadata") or {}
    cgcs_state = edit_metadata.get("cgcs_state") or {}
    structured_sources = [
        ("cgcs_state.witness_sample", cgcs_state.get("witness_sample")),
        ("cgcs_state.witness_samples", cgcs_state.get("witness_samples")),
        ("round.witness_sample", round_entry.get("witness_sample")),
        ("round.witness_samples", round_entry.get("witness_samples")),
        ("edit_metadata.witness_samples", edit_metadata.get("witness_samples")),
        ("trace.witness_samples", trace_entry.get("witness_samples")),
    ]
    seen_signatures: set[Tuple[str, str, str, Tuple[str, ...]]] = set()
    for source, payload in structured_sources:
        for witness in _iter_dicts(payload):
            normalized = _normalize_witness(witness)
            signature = (
                normalized.get("test_case", ""),
                normalized.get("message", ""),
                normalized.get("location", ""),
                tuple(normalized.get("linked_contract_ids") or []),
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            witnesses.append(normalized)
            quality["witness_sources"].append(source)
    if not witnesses:
        log_witnesses, log_quality = _extract_witnesses_from_logs(round_entry, logs_dir)
        if log_witnesses:
            witnesses.extend(log_witnesses)
            quality["witness_sources"].append("logs")
            quality["witness_log_files"] = log_quality.get("witness_log_files", [])
    quality["witness_count"] = len(witnesses)
    quality["witness_unique_count"] = len(seen_signatures) if seen_signatures else len(witnesses)
    if not witnesses:
        errors.append("empty_witnesses")
    return witnesses, quality, errors


def _normalize_witness(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "test_case": _clean_str(
            payload.get("test_case") or payload.get("test") or payload.get("case") or payload.get("id")
        ),
        "message": _clean_str(payload.get("message") or payload.get("detail") or payload.get("reason")),
        "category": _clean_str(payload.get("category") or payload.get("type") or "unspecified"),
        "expected": _clean_str(payload.get("expected")),
        "actual": _clean_str(payload.get("actual")),
        "location": _clean_str(payload.get("location") or payload.get("file") or payload.get("path")),
        "linked_contract_ids": _coerce_str_list(
            payload.get("linked_contract_ids") or payload.get("contracts") or payload.get("labels")
        ),
    }
    extras = {key: value for key, value in payload.items() if key not in normalized}
    if extras:
        normalized["extra"] = extras
    return normalized


def _extract_witnesses_from_logs(
    round_entry: Dict[str, Any],
    logs_dir: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    witnesses: List[Dict[str, Any]] = []
    log_files: List[str] = []
    round_index = int(round_entry.get("round", 0))
    for log_path in logs_dir.glob(f"tests_*_round{round_index + 1}.log"):
        text = _read_text(log_path)
        if not text:
            continue
        witness = _parse_witness_from_log(log_path.name, text)
        if witness:
            witnesses.append(witness)
            log_files.append(str(log_path))
    return witnesses, {"witness_log_files": log_files}


def _parse_witness_from_log(log_name: str, text: str) -> Optional[Dict[str, Any]]:
    test_case = log_name.split("_round")[0]
    stderr_section = text.split("STDERR:", 1)[1] if "STDERR:" in text else text
    message = stderr_section.strip().splitlines()[0] if stderr_section.strip() else ""
    location_match = re.search(r"(/[^:\s]+:\d+)", stderr_section)
    expected_match = re.search(r"Expected[:\s]+(.+)", stderr_section)
    actual_match = re.search(r"Actual[:\s]+(.+)", stderr_section)
    witness = {
        "test_case": test_case,
        "message": message[:500],
        "category": "log",
        "expected": expected_match.group(1).strip() if expected_match else "",
        "actual": actual_match.group(1).strip() if actual_match else "",
        "location": location_match.group(1) if location_match else "",
        "linked_contract_ids": [],
        "raw_log_excerpt": stderr_section[:2000],
    }
    return witness if any(witness.values()) else None


def extract_raw_payload(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
    logs_dir: Path,
) -> Tuple[str, Dict[str, Any], List[str]]:
    metadata = log_data.get("metadata") or {}
    round_index = int(log_data.get("round") or round_entry.get("round") or 0)
    candidates: List[Tuple[str, Any]] = [
        ("log.metadata.raw_payload", metadata.get("raw_payload")),
        ("log.raw_payload", log_data.get("raw_payload")),
        ("log.response_text", log_data.get("response_text")),
        ("log.model_output", log_data.get("model_output")),
    ]
    for source, payload in candidates:
        text = _clean_str(payload)
        if text:
            return text, {"raw_payload_source": source, "raw_payload_length": len(text)}, []
    log_path = logs_dir / f"edits_round{round_index + 1}.json"
    fallback = _read_text(log_path)
    if fallback:
        return fallback, {"raw_payload_source": "log_file_text", "raw_payload_length": len(fallback)}, []
    return "", {"raw_payload_source": "missing", "raw_payload_length": 0}, ["empty_payload"]


def extract_raw_payload_preview(payload: str, length: int = 200) -> str:
    return payload[:length]


def build_dataset(
    run_roots: Sequence[Path],
    trace_root: Path,
    output_dir: Path,
    options: DatasetBuildOptions,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    split_records: Dict[str, List[Dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    rejected_rows: List[Dict[str, Any]] = []
    all_rows: List[Dict[str, Any]] = []
    quality_counts: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    total_processed = 0
    stop_early = False
    for run_root in run_roots:
        if stop_early:
            break
        if not run_root.exists():
            continue
        for task_id, strategy, task_dir, logs_dir in _iter_strategy_runs(run_root):
            if stop_early:
                break
            trace_path = trace_root / strategy / f"{task_id}.json"
            if not trace_path.exists():
                continue
            if (strategy, task_id) not in trace_cache:
                trace_cache[(strategy, task_id)] = _load_json(trace_path)
                trace_cache[(strategy, task_id)]["_source_path"] = str(trace_path)
            trace_data = trace_cache[(strategy, task_id)]
            rounds: Sequence[Dict[str, Any]] = list(trace_data.get("rounds") or [])
            snapshot_path = logs_dir / "snapshot_check.json"
            snapshot_data = _load_json(snapshot_path)
            oracle_present = bool((task_dir / "oracle_teacher").exists())
            for round_entry in rounds:
                if options.max_records and total_processed >= options.max_records:
                    stop_early = True
                    break
                round_index = int(round_entry.get("round", 0))
                log_path = logs_dir / f"edits_round{round_index + 1}.json"
                log_data = _load_json(log_path)
                log_data["_source_path"] = str(log_path)
                split = _split_for_record(task_id, strategy, options.seed)
                row = _build_row(
                    trace_entry=trace_data,
                    round_entry=round_entry,
                    log_data=log_data,
                    snapshot=snapshot_data,
                    oracle_present=oracle_present,
                    logs_dir=logs_dir,
                    split=split,
                    options=options,
                )
                total_processed += 1
                is_usable, validation_errors = _validate_row(row, options)
                row.row_errors = _dedupe_preserve(row.row_errors + validation_errors)
                row.row_quality["usable"] = is_usable
                if validation_errors:
                    row.row_quality["validation_errors"] = validation_errors
                quality_counts["total_rows"] += 1
                if not row.active_clause_id:
                    quality_counts["missing_active_clause_id"] += 1
                if (
                    isinstance(row.contract_items, list)
                    and not row.contract_items
                    or isinstance(row.contract_items, dict)
                    and not row.contract_items
                ):
                    quality_counts["empty_contract_items"] += 1
                if not row.witnesses:
                    quality_counts["empty_witnesses"] += 1
            if not row.raw_edit_payload:
                quality_counts["empty_payloads"] += 1
            if row.row_quality.get("contract_quality") == "weak":
                quality_counts["weak_contract_rows"] += 1
            row_dict = row.to_dict()
            all_rows.append(row_dict)
            if is_usable:
                split_records.setdefault(row.split, []).append(row_dict)
                quality_counts["usable_rows"] += 1
            else:
                rejected_rows.append(row_dict)
                quality_counts["rejected_rows"] += 1
                if not validation_errors:
                    rejection_reasons["unspecified"] += 1
                for reason in validation_errors:
                    rejection_reasons[reason] += 1
    summary = _write_outputs(output_dir, split_records, rejected_rows, all_rows, quality_counts, rejection_reasons)
    if options.strict and summary["rejected_rows"]:
        raise SystemExit(f"Strict mode enabled: {summary['rejected_rows']} rows rejected.")
    return summary


def _build_row(
    trace_entry: Dict[str, Any],
    round_entry: Dict[str, Any],
    log_data: Dict[str, Any],
    snapshot: Dict[str, Any],
    oracle_present: bool,
    logs_dir: Path,
    split: str,
    options: DatasetBuildOptions,
) -> CGCSDatasetRow:
    plan = trace_entry.get("plan") or {}
    context_snippets_raw = plan.get("diagnostics", {}).get("repo_context_snippets") or []
    context_snippets = list(context_snippets_raw) if isinstance(context_snippets_raw, list) else [context_snippets_raw]
    contract_items, contract_quality, contract_errors = extract_contract_items(trace_entry, round_entry, log_data)
    active_clause_id, clause_quality, clause_errors = extract_active_clause_id(trace_entry, round_entry, log_data)
    regression_guard_ids, guard_quality, guard_errors = extract_regression_guards(trace_entry, round_entry, log_data)
    witnesses, witness_quality, witness_errors = extract_witnesses(trace_entry, round_entry, log_data, logs_dir)
    candidate_files, candidate_quality, candidate_errors = extract_candidate_files(
        trace_entry, round_entry, log_data, include_tests=options.include_tests
    )
    raw_edit_payload, payload_quality, payload_errors = extract_raw_payload(trace_entry, round_entry, log_data, logs_dir)
    row_quality: Dict[str, Any] = {}
    for quality in (contract_quality, clause_quality, guard_quality, witness_quality, candidate_quality, payload_quality):
        row_quality.update(quality)
    row_quality["context_snippet_count"] = len(context_snippets)
    row_quality["raw_payload_preview"] = extract_raw_payload_preview(raw_edit_payload)
    row_quality["round_status"] = round_entry.get("status")
    row_quality["round_phase"] = round_entry.get("phase")
    row_quality["raw_round_value"] = round_entry.get("round")
    row_errors = contract_errors + clause_errors + guard_errors + witness_errors + candidate_errors + payload_errors
    source_paths = {
        "trace_file": str(trace_entry.get("_source_path", "")),
        "log_file": str(log_data.get("_source_path", "")),
        "logs_dir": str(logs_dir),
        "snapshot_file": str(logs_dir / "snapshot_check.json"),
    }
    snapshot_hash = _clean_str(snapshot.get("computed_snapshot"))
    outcome_metrics = {
        "status": round_entry.get("status"),
        "pass_rate": round_entry.get("pass_rate"),
        "duration": round_entry.get("duration"),
        "failing_tests": round_entry.get("failing_tests"),
        "error_types": round_entry.get("error_types"),
    }
    return CGCSDatasetRow(
        task_id=_clean_str(trace_entry.get("task_id")),
        strategy=_clean_str(trace_entry.get("strategy")),
        round_index=int(round_entry.get("round", 0)),
        split=split,
        repo_snapshot_sha256=snapshot_hash,
        contract_items=contract_items,
        active_clause_id=active_clause_id,
        regression_guard_ids=regression_guard_ids,
        witnesses=witnesses,
        candidate_files=candidate_files,
        context_snippets=context_snippets,
        raw_edit_payload=raw_edit_payload,
        outcome_metrics=outcome_metrics,
        oracle_patch_present=oracle_present,
        source_paths=source_paths,
        row_quality=row_quality,
        row_errors=row_errors,
    )


def _validate_row(row: CGCSDatasetRow, options: DatasetBuildOptions) -> Tuple[bool, List[str]]:
    errors = list(row.row_errors)
    if not row.task_id:
        errors.append("missing_task_id")
    if row.row_quality.get("raw_round_value") is None:
        errors.append("missing_round_index")
    has_contract_items = False
    if isinstance(row.contract_items, list):
        has_contract_items = len(row.contract_items) > 0
    elif isinstance(row.contract_items, dict):
        has_contract_items = len(row.contract_items) > 0
    if not has_contract_items:
        errors.append("empty_contract_items")
    if not row.active_clause_id:
        errors.append("missing_active_clause_id")
    has_witnesses = bool(row.witnesses)
    has_payload = bool(_clean_str(row.raw_edit_payload))
    if row.row_quality.get("contract_quality") == "weak" and not options.allow_placeholder_contracts:
        errors.append("placeholder_contract")
    if not (has_witnesses or has_payload or options.allow_empty_payload):
        errors.append("missing_witness_and_payload")
    is_usable = not errors
    return is_usable, errors


def _write_outputs(
    output_dir: Path,
    split_records: Dict[str, List[Dict[str, Any]]],
    rejected_rows: List[Dict[str, Any]],
    all_rows: List[Dict[str, Any]],
    quality_counts: Counter[str],
    rejection_reasons: Counter[str],
) -> Dict[str, Any]:
    for split, rows in split_records.items():
        _write_jsonl(output_dir / f"{split}.jsonl", rows)
    _write_jsonl(output_dir / "rejected.jsonl", rejected_rows)
    _write_jsonl(output_dir / "all_rows.jsonl", all_rows)
    dataset_summary = {
        "total_rows": quality_counts.get("total_rows", 0),
        "usable_rows": quality_counts.get("usable_rows", 0),
        "rejected_rows": quality_counts.get("rejected_rows", 0),
        "missing_active_clause_id": quality_counts.get("missing_active_clause_id", 0),
        "empty_contract_items": quality_counts.get("empty_contract_items", 0),
        "empty_witnesses": quality_counts.get("empty_witnesses", 0),
        "empty_payloads": quality_counts.get("empty_payloads", 0),
        "weak_contract_rows": quality_counts.get("weak_contract_rows", 0),
        "split_counts": {split: len(rows) for split, rows in split_records.items()},
        "rejection_reasons": dict(rejection_reasons),
    }
    summary_path = output_dir / "dataset_summary.json"
    summary_path.write_text(json.dumps(dataset_summary, indent=2), encoding="utf-8")
    _print_summary(dataset_summary)
    return dataset_summary


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _print_summary(summary: Dict[str, Any]) -> None:
    lines = [
        f"total_rows={summary.get('total_rows', 0)}",
        f"usable_rows={summary.get('usable_rows', 0)}",
        f"rejected_rows={summary.get('rejected_rows', 0)}",
        f"missing_active_clause_id={summary.get('missing_active_clause_id', 0)}",
        f"empty_contract_items={summary.get('empty_contract_items', 0)}",
        f"empty_witnesses={summary.get('empty_witnesses', 0)}",
        f"empty_payloads={summary.get('empty_payloads', 0)}",
        f"weak_contract_rows={summary.get('weak_contract_rows', 0)}",
    ]
    print(" | ".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build CGCS dataset JSONL files.")
    parser.add_argument("--run-root", type=Path, default=_default_run_root(), help="Path to real_repo runs directory.")
    parser.add_argument(
        "--pilot-run-root",
        type=Path,
        default=Path("reports/decomposition/public_repo_pilot/runs"),
        help="Path to public_repo pilot runs (if available).",
    )
    parser.add_argument(
        "--skip-pilot",
        action="store_true",
        help="Exclude public_repo pilot runs from the dataset build.",
    )
    parser.add_argument("--trace-root", type=Path, default=_default_trace_root(), help="Path to trace snapshots.")
    parser.add_argument("--output-dir", type=Path, default=Path("data") / "cgcs", help="Directory for output JSONL files.")
    parser.add_argument("--strict", action="store_true", help="Fail when unusable rows are encountered.")
    parser.add_argument(
        "--allow-placeholder-contracts",
        action="store_true",
        help="Allow placeholder contracts to pass validation.",
    )
    parser.add_argument(
        "--allow-empty-payload",
        action="store_true",
        help="Treat rows without witnesses/payload as usable.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Allow candidate files under tests/ directories.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
        help="Limit the number of processed records (0=all).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed to perturb the deterministic split.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_records = args.max_records if args.max_records > 0 else None
    options = DatasetBuildOptions(
        strict=args.strict,
        allow_placeholder_contracts=args.allow_placeholder_contracts,
        allow_empty_payload=args.allow_empty_payload,
        include_tests=args.include_tests,
        max_records=max_records,
        seed=args.seed,
    )
    run_roots: List[Path] = [args.run_root]
    if not args.skip_pilot:
        run_roots.append(args.pilot_run_root)
    # Deduplicate while preserving order
    seen: set[Path] = set()
    ordered_roots: List[Path] = []
    for root in run_roots:
        if root in seen:
            continue
        seen.add(root)
        ordered_roots.append(root)
    summary = build_dataset(ordered_roots, args.trace_root, args.output_dir, options)
    print(f"Wrote CGCS dataset to {args.output_dir} ({summary.get('total_rows', 0)} rows)")


if __name__ == "__main__":
    main()
