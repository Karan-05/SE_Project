"""Triage tool for diagnosing systematic failures in decomposition runs."""
from __future__ import annotations

import argparse
import csv
import json
import random
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = PROJECT_ROOT / "reports" / "experiments"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "self_verifying"


@dataclass
class FailureRecord:
    task_id: str
    dataset_id: str
    dataset_path: str
    strategy_final: str
    fallback_path: str
    attempt_count: float
    failure_signature: str
    tests_source: str
    tests_path: str
    row: Dict[str, Any]


def _load_csv_records(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        return [{k: (v or "") for k, v in row.items()} for row in reader]


def _to_float(value: str | float | int | None) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _snippet(text: str, limit: int = 320) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."


ID_COLUMNS = [
    "problem_id",
    "challengeid",
    "legacyid",
    "challenge_id",
    "task_id",
    "id",
    "round_id",
]
STATEMENT_COLUMNS = [
    "problem_statement",
    "statement",
    "description",
    "details",
    "prompt",
    "requirements",
    "overview",
    "detailedrequirements",
]


def _normalize_key(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())


def _extract_row_id(row: Dict[str, Any]) -> Optional[str]:
    lower_map = {_normalize_key(k): k for k in row.keys() if isinstance(k, str)}
    for candidate in ID_COLUMNS:
        column = lower_map.get(candidate)
        if not column:
            continue
        value = row.get(column)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _extract_statement(row: Dict[str, Any]) -> str:
    lower_map = {_normalize_key(k): k for k in row.keys() if isinstance(k, str)}
    for candidate in STATEMENT_COLUMNS:
        column = lower_map.get(candidate)
        if column and isinstance(row.get(column), str) and row[column].strip():
            return row[column].strip()
    for key, value in row.items():
        if isinstance(key, str) and "description" in _normalize_key(key) and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _load_dataset_rows(dataset_path: Path, target_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    targets = {str(t) for t in target_ids if t}
    if not dataset_path.exists() or not targets:
        return {}
    suffix = dataset_path.suffix.lower()
    loader: Dict[str, Dict[str, Any]] = {}
    if suffix in {".csv", ".tsv"}:
        with dataset_path.open("r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                row_id = _extract_row_id(row)
                if row_id in targets:
                    loader[row_id] = row
                    if len(loader) == len(targets):
                        break
        return loader
    if suffix == ".jsonl":
        with dataset_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                row_id = _extract_row_id(row)
                if row_id in targets:
                    loader[row_id] = row
                    if len(loader) == len(targets):
                        break
        return loader
    if suffix == ".json":
        try:
            data = json.loads(dataset_path.read_text())
        except json.JSONDecodeError:
            return {}
        rows: Iterable[Dict[str, Any]]
        if isinstance(data, dict):
            maybe_records = data.get("records") or data.get("rows")
            if isinstance(maybe_records, list):
                rows = [item for item in maybe_records if isinstance(item, dict)]
            else:
                rows = [data]
        elif isinstance(data, list):
            rows = [item for item in data if isinstance(item, dict)]
        else:
            rows = []
        for row in rows:
            row_id = _extract_row_id(row)
            if row_id in targets:
                loader[row_id] = row
                if len(loader) == len(targets):
                    break
        return loader
    # Unsupported format (parquet/xlsx) — skip gracefully.
    return {}


def _build_failure_records(per_problem: List[Dict[str, str]], failures: List[Dict[str, str]]) -> List[FailureRecord]:
    per_problem_map = {row["task_id"]: row for row in per_problem if row.get("task_id")}
    records: List[FailureRecord] = []
    for row in failures:
        task_id = row.get("task_id")
        if not task_id or task_id not in per_problem_map:
            continue
        merged = per_problem_map[task_id]
        record = FailureRecord(
            task_id=task_id,
            dataset_id=merged.get("dataset_id", ""),
            dataset_path=merged.get("dataset_path", ""),
            strategy_final=merged.get("strategy_used", ""),
            fallback_path=merged.get("fallback_path", ""),
            attempt_count=_to_float(merged.get("attempt_count")),
            failure_signature=merged.get("failure_signature", ""),
            tests_source=merged.get("tests_source", ""),
            tests_path=merged.get("tests_path", ""),
            row=merged,
        )
        records.append(record)
    return records


def _sample_failures(records: List[FailureRecord], sample_size: int, seed: int) -> List[FailureRecord]:
    if not records:
        return []
    rng = random.Random(seed)
    buckets: Dict[str, List[FailureRecord]] = defaultdict(list)
    for record in records:
        buckets[record.dataset_id].append(record)
    for items in buckets.values():
        rng.shuffle(items)
    dataset_ids = sorted(buckets.keys())
    sampled: List[FailureRecord] = []
    # Pass 1: ensure each dataset contributes at least one failure.
    for dataset_id in dataset_ids:
        bucket = buckets[dataset_id]
        if not bucket:
            continue
        sampled.append(bucket.pop())
        if len(sampled) >= sample_size:
            return sampled
    # Pass 2: round-robin until we reach the requested sample size.
    while len(sampled) < sample_size:
        added = False
        for dataset_id in dataset_ids:
            bucket = buckets[dataset_id]
            if not bucket:
                continue
            sampled.append(bucket.pop())
            added = True
            if len(sampled) >= sample_size:
                break
        if not added:
            break
    return sampled


def _select_recent_failures(records: List[FailureRecord], count: int) -> List[FailureRecord]:
    if count <= 0:
        return []
    sorted_records = sorted(records, key=lambda rec: rec.row.get("end_time") or "", reverse=True)
    return sorted_records[:count]


def _load_tests(tests_path: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not tests_path:
        return [], []
    path = Path(tests_path)
    if not path.exists():
        return [], []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return [], []
    if isinstance(data, list):
        modes = sorted({str((test or {}).get("mode", "call")).lower() for test in data if isinstance(test, dict)})
        return data, modes
    return [], []


def _infer_modes_from_row(row: Optional[Dict[str, Any]]) -> List[str]:
    if not row:
        return []
    tests = row.get("tests")
    if not isinstance(tests, list):
        return []
    modes = set()
    for test in tests:
        if not isinstance(test, dict):
            continue
        mode = test.get("mode")
        if not mode:
            if "stdin" in test or "expected_stdout" in test:
                mode = "io"
            else:
                mode = "call"
        modes.add(str(mode).lower())
    return sorted(modes)


def _index_artifacts(artifact_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not artifact_dir.exists():
        return index
    for path in sorted(artifact_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        task_id = payload.get("task_id")
        if not task_id:
            continue
        payload["_artifact_path"] = str(path)
        index[task_id].append(payload)
    for task_id, entries in index.items():
        entries.sort(key=lambda data: float(data.get("attempt", 0)), reverse=True)
    return index


def _extract_failures(tests_run: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, str]]:
    failures: List[Dict[str, str]] = []
    for test in tests_run:
        if str(test.get("status")) == "pass":
            continue
        failures.append(
            {
                "name": str(test.get("name", "")),
                "expected": str(test.get("expected")),
                "output": str(test.get("output")),
                "error": str(test.get("error")),
            }
        )
        if len(failures) >= limit:
            break
    return failures


def _classify_failure(
    record: FailureRecord,
    tests_modes: List[str],
    latest_attempt: Optional[Dict[str, Any]],
) -> str:
    dataset_id = record.dataset_id or "unknown"
    if latest_attempt:
        tests_run = latest_attempt.get("tests_run") or []
        errors = " ".join(str(test.get("error", "")) for test in tests_run)
        statuses = {str(test.get("status")) for test in tests_run}
        if any(status in {"missing_entry_point", "compile_error"} for status in statuses):
            return "interface_mismatch"
        if "NameError" in errors or "TypeError" in errors or "AttributeError" in errors:
            return "interface_mismatch"
        if "ImportError" in errors or "ModuleNotFoundError" in errors or "PermissionError" in errors:
            return "harness_errors"
    if dataset_id.startswith("analysis_output") or record.tests_source == "synthesized":
        return "bad_test_parsing"
    if not tests_modes:
        return "bad_test_parsing"
    return "real_algorithm_wrong"


def _format_failure_entry(sample: Dict[str, Any]) -> str:
    failing_tests = sample.get("failing_tests") or []
    failures_text = ", ".join(
        f"{item['name']}: expected {item['expected']} but got {item['output']} (error={item['error']})"
        for item in failing_tests
    )
    if not failures_text:
        failures_text = sample.get("failure_note", "No failing test details available")
    snippet = _snippet(sample.get("problem_statement") or "", 240)
    return textwrap.dedent(
        f"""
        - **Task** {sample['task_id']} ({sample['dataset_id']})
          Strategy path: {sample['strategy_initial']} -> ... -> {sample['strategy_final']} | Attempts: {sample['attempts']}
          Failure: {sample['failure_signature']} | Tests: {sample['tests_source']} ({'/'.join(sample['tests_modes']) or 'n/a'})
          Problem snippet: {snippet}
          Failures: {failures_text}
        """
    ).strip()


def run_triage(run_id: str, sample_size: int, seed: int, recent_count: Optional[int] = None) -> Dict[str, Any]:
    run_dir = REPORTS_ROOT / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run '{run_id}' not found under {REPORTS_ROOT}")
    per_problem_path = run_dir / "per_problem.csv"
    failures_path = run_dir / "failures.csv"
    if not per_problem_path.exists() or not failures_path.exists():
        raise FileNotFoundError("Run is missing per_problem.csv or failures.csv")
    per_problem = _load_csv_records(per_problem_path)
    failures = _load_csv_records(failures_path)
    records = _build_failure_records(per_problem, failures)
    if recent_count:
        samples = _select_recent_failures(records, recent_count)
    else:
        samples = _sample_failures(records, sample_size, seed)
    artifact_dir = ARTIFACT_ROOT / run_id
    artifact_index = _index_artifacts(artifact_dir)
    dataset_targets: Dict[str, set[str]] = defaultdict(set)
    for record in samples:
        if record.dataset_path:
            dataset_targets[record.dataset_path].add(record.task_id)
    dataset_rows: Dict[str, Dict[str, Any]] = {}
    for path_str, targets in dataset_targets.items():
        dataset_rows[path_str] = _load_dataset_rows(Path(path_str), targets)
    sample_summaries: List[Dict[str, Any]] = []
    cluster_counts: Counter[str] = Counter()
    for record in samples:
        dataset_row = dataset_rows.get(record.dataset_path, {}).get(record.task_id)
        statement = _extract_statement(dataset_row or {}) if dataset_row else ""
        problem_snippet = _snippet(statement or record.row.get("title", ""), 400)
        entry_point = "solve"
        _, modes = _load_tests(record.tests_path)
        if not modes:
            modes = _infer_modes_from_row(dataset_row)
        latest_attempt = None
        attempts = artifact_index.get(record.task_id) or []
        if attempts:
            latest_attempt = attempts[0]
        failing_tests = _extract_failures(latest_attempt.get("tests_run", []) if latest_attempt else [])
        failure_note = ""
        if not failing_tests and latest_attempt:
            failures = latest_attempt.get("tests_run") or []
            if failures:
                failure_note = ", ".join(f"{item.get('name')}: {item.get('status')}" for item in failures)
        code_snippet = latest_attempt.get("solution_preview", "") if latest_attempt else ""
        category = _classify_failure(record, modes, latest_attempt)
        cluster_counts[category] += 1
        sample_summaries.append(
            {
                "task_id": record.task_id,
                "dataset_id": record.dataset_id,
                "strategy_initial": (record.fallback_path or "").split("->")[0] or record.strategy_final,
                "strategy_final": record.strategy_final,
                "attempts": record.attempt_count,
                "failure_signature": record.failure_signature,
                "tests_source": record.tests_source,
                "tests_modes": modes,
                "entry_point": entry_point,
                "problem_statement": problem_snippet,
                "failing_tests": failing_tests,
                "failure_note": failure_note,
                "code_snippet": code_snippet or "<not captured>",
                "category": category,
                "tests_path": record.tests_path,
            }
        )

    summary = {
        "run_id": run_id,
        "sample_size": len(sample_summaries),
        "cluster_counts": dict(cluster_counts),
        "samples": sample_summaries,
    }

    triage_md = [f"# Triage Summary — {run_id}", ""]
    if not sample_summaries:
        triage_md.append("No failures available for triage.")
    else:
        total = len(sample_summaries)
        for cluster, count in cluster_counts.most_common():
            triage_md.append(f"## {cluster.replace('_', ' ').title()} ({count}/{total})")
            examples = [sample for sample in sample_summaries if sample["category"] == cluster][:5]
            for example in examples:
                triage_md.append(_format_failure_entry(example))
            triage_md.append("")

    md_path = run_dir / "triage_summary.md"
    json_path = run_dir / "triage_summary.json"
    md_path.write_text("\n".join(triage_md).strip() + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    top_clusters = ", ".join(f"{name}:{count}" for name, count in cluster_counts.most_common(3))
    print(top_clusters or "No failures triaged.")
    if sample_summaries:
        dominant = cluster_counts.get("interface_mismatch", 0) + cluster_counts.get("bad_test_parsing", 0)
        if dominant and dominant / len(sample_summaries) >= 0.7:
            print(
                "SANITY CHECK: >70% of sampled failures stem from interface/test parsing issues — prioritize these first.",
            )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Triage decomposition failures for a Topcoder run.")
    parser.add_argument("--run-id", required=True, help="Experiment run identifier (reports/experiments/<run-id>)")
    parser.add_argument("--sample-size", type=int, default=30, help="Number of failures to sample (default 30)")
    parser.add_argument("--seed", type=int, default=13, help="Random seed for sampling")
    parser.add_argument("--recent-count", type=int, default=0, help="Use the most recent N failures instead of random sampling")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    recent = args.recent_count if args.recent_count > 0 else None
    run_triage(args.run_id, max(1, args.sample_size), args.seed, recent_count=recent)


if __name__ == "__main__":
    main()
