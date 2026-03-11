"""Aggregate experiment checkpoints into summary reports."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Tuple, Optional, Any

from .task_router import TaskType

SUCCESS_STATUSES = {
    "passed",
    "success",
    "completed_architecture_doc",
    "completed_design_doc",
    "completed_patch",
    "completed_data_etl",
}
SUCCESS_STATUSES_LOWER = {status.lower() for status in SUCCESS_STATUSES}


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _strategy_split(path: str) -> Tuple[str, str]:
    if not path:
        return "", ""
    parts = path.split("->")
    initial = parts[0]
    final = parts[-1]
    return initial, final


def _tasks_by_dataset(records: List[Dict[str, object]]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        dataset_id = str(record.get("dataset_id", "unknown"))
        counter[dataset_id] += 1
    return dict(counter)


def generate_reports(
    run_id: str,
    run_dir: Path,
    records: List[Dict[str, object]],
    *,
    artifact_dir: Path,
    llm_usage: Optional[Dict[str, Any]] = None,
    llm_available: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    markdown_path = run_dir / "summary.md"
    per_problem_path = run_dir / "per_problem.csv"
    failures_path = run_dir / "failures.csv"

    deduped_records = _deduplicate_summary_records(records)
    total = len(deduped_records)
    raw_total = len(records)
    unique_task_ids = {str(rec.get("task_id") or idx) for idx, rec in enumerate(deduped_records)}
    total_unique_tasks = len(unique_task_ids)
    duplicates_removed = raw_total - total
    attempted_records = [rec for rec in deduped_records if not str(rec.get("status", "")).startswith("skipped")]
    attempted = len(attempted_records)
    successes = [rec for rec in attempted_records if str(rec.get("status", "")).lower() in SUCCESS_STATUSES_LOWER]
    completed = len(successes)
    actionable_attempted_total = attempted
    attempted_success_total = completed
    attempted_failed_total = actionable_attempted_total - attempted_success_total
    parse_failures_total = sum(1 for rec in deduped_records if str(rec.get("status", "")) == "skipped_parse_failure")
    success_rate = completed / total if total else 0.0
    success_attempts = [_to_float(rec.get("attempt_count")) for rec in successes]
    avg_attempts = mean(success_attempts) if success_attempts else 0.0
    median_attempts = median(success_attempts) if success_attempts else 0.0
    max_attempts = max(success_attempts) if success_attempts else 0.0
    fallback_count = sum(1 for rec in attempted_records if "->" in str(rec.get("fallback_path", "")))
    stagnation_count = sum(1 for rec in attempted_records if _to_float(rec.get("stagnation_events")) > 0)
    def _resolved_type(rec: Dict[str, object]) -> str:
        return str(rec.get("resolved_task_type") or rec.get("task_type") or "").lower()

    self_check_sources = {"self_check", "synthesized"}
    attempted_extracted = [
        rec for rec in attempted_records if str(rec.get("tests_source", "")).lower() not in self_check_sources
    ]
    attempted_synthesized = [rec for rec in attempted_records if str(rec.get("tests_source", "")).lower() in self_check_sources]
    attempted_with_extracted_tests = len(attempted_extracted)
    attempted_with_synthesized_tests = len(attempted_synthesized)
    successes_extracted = [
        rec for rec in successes if str(rec.get("tests_source", "")).lower() not in self_check_sources
    ]
    successes_synth = [rec for rec in successes if str(rec.get("tests_source", "")).lower() in self_check_sources]
    overall_success_rate_with_tests = len(successes_extracted) / attempted_with_extracted_tests if attempted_with_extracted_tests else 0.0
    success_rate_synthesized = len(successes_synth) / attempted_with_synthesized_tests if attempted_with_synthesized_tests else 0.0
    algo_attempted_records = [rec for rec in attempted_records if _resolved_type(rec) == TaskType.ALGO_CODING.value]
    non_actionable_statuses = {"skipped_insufficient_context", "skipped_non_actionable", "skipped_non_coding_task"}
    non_actionable_total = sum(
        1
        for rec in deduped_records
        if str(rec.get("status", "")).startswith("skipped_insufficient_context") or str(rec.get("status", "")) in non_actionable_statuses
    )
    non_coding_records = [
        rec
        for rec in attempted_records
        if _resolved_type(rec)
        in {
            TaskType.REPO_PATCH.value,
            TaskType.API_BACKEND.value,
            TaskType.ARCHITECTURE_DOC.value,
            TaskType.DATA_ETL.value,
        }
    ]
    attempted_algo = len(algo_attempted_records)
    solved_algo = sum(1 for rec in algo_attempted_records if rec.get("unit_test_success"))
    attempted_non_coding = len(non_coding_records)
    completed_deliverables = sum(1 for rec in non_coding_records if rec.get("deliverable_success"))
    algo_extracted = [
        rec for rec in algo_attempted_records if str(rec.get("tests_source", "")).lower() not in self_check_sources
    ]
    pass_algo_extracted = sum(1 for rec in algo_extracted if rec.get("unit_test_success"))
    pass_at_final_extracted_only = (pass_algo_extracted / len(algo_extracted)) if algo_extracted else 0.0
    algo_verified_success_rate = pass_at_final_extracted_only
    algo_verified_attempted = len(algo_extracted)
    algo_verified_solved = pass_algo_extracted
    deliverable_success_rate = (completed_deliverables / attempted_non_coding) if attempted_non_coding else 0.0
    self_check_attempted_records = [
        rec for rec in algo_attempted_records if str(rec.get("tests_source", "")).lower() == "self_check"
    ]
    self_check_attempted = len(self_check_attempted_records)
    self_check_success = sum(1 for rec in self_check_attempted_records if rec.get("self_check_passed"))
    self_check_pass_rate = (self_check_success / self_check_attempted) if self_check_attempted else 0.0
    initial_distribution: Counter[str] = Counter()
    final_distribution: Counter[str] = Counter()
    for rec in attempted_records:
        initial, final = _strategy_split(str(rec.get("fallback_path", "")) or str(rec.get("strategy_used", "")))
        if initial:
            initial_distribution[initial] += 1
        if final:
            final_distribution[final] += 1

    durations = [_to_float(rec.get("duration_seconds")) for rec in attempted_records if _to_float(rec.get("duration_seconds")) > 0]
    avg_time_per_task = mean(durations) if durations else 0.0
    start_times = [_parse_time(str(rec.get("start_time", ""))) for rec in records]
    end_times = [_parse_time(str(rec.get("end_time", ""))) for rec in records]
    start_times = [ts for ts in start_times if ts]
    end_times = [ts for ts in end_times if ts]
    overall_start = min(start_times).isoformat() if start_times else ""
    overall_end = max(end_times).isoformat() if end_times else ""
    total_wall = 0.0
    if start_times and end_times:
        total_wall = max((max(end_times) - min(start_times)).total_seconds(), 0.0)

    error_counter: Counter[str] = Counter()
    for rec in records:
        error_counter[str(rec.get("error_type", "none"))] += 1

    solve_attempts_total = sum(_to_float(rec.get("attempt_count")) for rec in attempted_records)
    llm_calls_total = 0.0
    if llm_usage:
        per = llm_usage.get("per_caller", {})
        if isinstance(per, dict):
            llm_calls_total = sum((stats.get("calls", 0.0) if isinstance(stats, dict) else 0.0) for stats in per.values())
    run_validity = "VALID"
    metadata = metadata or {}
    if metadata.get("mock_provider"):
        run_validity = "DEMO_ONLY_MOCK"
    if run_validity != "DEMO_ONLY_MOCK" and llm_available and attempted > 0 and llm_calls_total <= 0:
        run_validity = "INVALID_NO_LLM"
    task_type_breakdown: Dict[str, Dict[str, int]] = {}
    for rec in attempted_records:
        type_key = _resolved_type(rec) or ""
        if not type_key:
            continue
        bucket = task_type_breakdown.setdefault(type_key, {"attempted": 0, "success": 0, "failed": 0})
        bucket["attempted"] += 1
        if str(rec.get("status", "")).lower() in SUCCESS_STATUSES_LOWER:
            bucket["success"] += 1
        else:
            bucket["failed"] += 1
    evaluation_coverage = actionable_attempted_total / total_unique_tasks if total_unique_tasks else 0.0
    evaluation_coverage = max(0.0, min(1.0, evaluation_coverage))
    summary = {
        "run_id": run_id,
        "total_problems": total,
        "total_unique_tasks": total_unique_tasks,
        "raw_task_rows": raw_total,
        "duplicate_task_rows": duplicates_removed,
        "attempted": attempted,
        "completed_successfully": completed,
        "actionable_attempted_total": actionable_attempted_total,
        "attempted_success_total": attempted_success_total,
        "attempted_failed_total": attempted_failed_total,
        "parse_failures_total": parse_failures_total,
        "non_actionable_total": non_actionable_total,
        "success_rate": success_rate,
        "pass_at_final": pass_at_final_extracted_only,
        "avg_attempts_to_success": avg_attempts,
        "median_attempts_to_success": median_attempts,
        "max_attempts_to_success": max_attempts,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_count / attempted if attempted else 0.0,
        "stagnation_count": stagnation_count,
        "stagnation_rate": stagnation_count / attempted if attempted else 0.0,
        "attempted_with_extracted_tests": attempted_with_extracted_tests,
        "attempted_with_synthesized_tests": attempted_with_synthesized_tests,
        "overall_success_rate_with_tests": overall_success_rate_with_tests,
        "success_rate_extracted": overall_success_rate_with_tests,
        "success_rate_synthesized": success_rate_synthesized,
        "self_check_attempted": self_check_attempted,
        "self_check_pass_rate": self_check_pass_rate,
        "strategy_distribution_initial": dict(initial_distribution),
        "strategy_distribution_final": dict(final_distribution),
        "runtime": {
            "start_time": overall_start,
            "end_time": overall_end,
            "total_wall_time_seconds": total_wall,
            "avg_time_per_task": avg_time_per_task,
        },
        "error_taxonomy": dict(error_counter),
        "artifact_dir": str(artifact_dir),
        "tasks_by_dataset": _tasks_by_dataset(records),
        "solve_attempts_total": solve_attempts_total,
        "llm_calls_total": llm_calls_total,
        "llm_calls_avg_per_task": (llm_calls_total / attempted) if attempted else 0.0,
        "llm_calls_per_attempted": (llm_calls_total / actionable_attempted_total) if actionable_attempted_total else 0.0,
        "llm_available": llm_available,
        "run_validity": run_validity,
        "llm_provider": metadata.get("llm_provider") or "",
        "attempted_algo": attempted_algo,
        "solved_algo": solved_algo,
        "attempted_non_coding": attempted_non_coding,
        "completed_deliverables": completed_deliverables,
        "deliverable_success_rate": deliverable_success_rate,
        "pass_at_final_extracted_only": pass_at_final_extracted_only,
        "algo_pass_at_final": pass_at_final_extracted_only,
        "algo_verified_success_rate": algo_verified_success_rate,
        "algo_verified_attempted": algo_verified_attempted,
        "algo_verified_solved": algo_verified_solved,
        "task_type_breakdown": task_type_breakdown,
        "evaluation_coverage": evaluation_coverage,
    }
    if metadata:
        summary.update(metadata)

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        f"# Topcoder Self-Verify Experiment {run_id}",
        "",
    ]
    if summary.get("presentation_mode"):
        lines.append(
            f"> **Sample Estimate** — sample_size={summary.get('sample_size')} seed={summary.get('sample_seed')} strategy={summary.get('sample_strategy')}"
        )
        lines.append("")
    algo_ratio = f"{algo_verified_solved}/{algo_verified_attempted}" if algo_verified_attempted else "0/0"
    lines.extend(
        [
            f"- Total problems: **{total}** (raw rows {raw_total})",
            f"- Actionable attempted: {actionable_attempted_total} (success {attempted_success_total}, failed {attempted_failed_total})",
            f"- Non-actionable (insufficient context): {non_actionable_total}",
            f"- Evaluation coverage: {evaluation_coverage:.2%} | Parse failures captured: {parse_failures_total}",
            f"- Completed successfully: **{completed}** | Overall success rate: {success_rate:.2%}",
            f"- Algo pass@final (provided tests only): {pass_at_final_extracted_only:.2%} ({algo_ratio})",
            f"- Algorithmic coding: attempted {attempted_algo}, solved {solved_algo}",
            f"- Non-coding deliverables: attempted {attempted_non_coding}, completed {completed_deliverables} (success {deliverable_success_rate:.2%})",
            f"- Avg/Median/Max attempts to success: {avg_attempts:.2f} / {median_attempts:.2f} / {max_attempts:.2f}",
            f"- Fallback switches: {fallback_count} (rate {summary['fallback_rate']:.2f}) | Stagnation triggers: {stagnation_count} (rate {summary['stagnation_rate']:.2f})",
            f"- Tests: provided/extracted={attempted_with_extracted_tests} (success {overall_success_rate_with_tests:.2%}) synthesized/self-check={attempted_with_synthesized_tests} (success {success_rate_synthesized:.2%})",
            f"- Self-checks: attempted {self_check_attempted} (pass {self_check_pass_rate:.2%}) — excluded from pass@final",
            f"- LLM calls: total={llm_calls_total:.0f} avg/task={summary['llm_calls_avg_per_task']:.2f} per_attempted={summary['llm_calls_per_attempted']:.2f} | Solve attempts logged: {solve_attempts_total:.1f}",
            f"- Runtime: start={overall_start or 'n/a'} end={overall_end or 'n/a'} wall={total_wall:.1f}s avg/task={avg_time_per_task:.2f}s",
            f"- Artifact traces: `{artifact_dir}`",
            "",
            "## Strategy usage",
        ]
    )
    if initial_distribution:
        lines.append(f"- Initial strategies: {dict(initial_distribution)}")
    if final_distribution:
        lines.append(f"- Final strategies: {dict(final_distribution)}")
    lines.append("")
    lines.append("## Error taxonomy")
    lines.append(str(dict(error_counter)))
    lines.append("")
    lines.append("Reports: ")
    lines.append(f"- `{per_problem_path}`")
    lines.append(f"- `{failures_path}`")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    # per-problem CSV
    per_problem_columns = [
        "task_id",
        "dataset_id",
        "dataset_path",
        "title",
        "task_type",
        "resolved_task_type",
        "status",
        "error_type",
        "pass_rate",
        "pass_at_final",
        "attempt_count",
        "strategy_used",
        "fallback_path",
        "stagnation_events",
        "start_time",
        "end_time",
        "duration_seconds",
        "tests_provided",
        "tests_source",
        "tests_path",
        "router_rationale",
        "router_heuristics",
        "solver_used",
        "solver_name",
        "verifier_type",
        "verifier_name",
        "verifier_score",
        "used_synthesized_tests",
        "self_check_only",
        "self_check_pass_rate",
        "self_check_passed",
        "memory_hint_count",
        "memory_hints_retrieved",
        "artifact_path",
        "unit_test_report_path",
        "deliverable_path",
        "patch_path",
        "repo_log_path",
        "rubric_path",
        "classification_path",
        "verification_path",
        "reflections_path",
        "raw_agent_response_path",
        "repaired_agent_response_path",
        "failure_signature",
        "failing_tests",
        "last_error",
        "llm_calls_used",
        "timed_out",
        "timeout_reason",
        "unit_test_success",
        "deliverable_success",
    ]
    with per_problem_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=per_problem_columns)
        writer.writeheader()
        for rec in records:
            row = {col: rec.get(col, "") for col in per_problem_columns}
            row["tests_provided"] = bool(rec.get("tests_provided"))
            row["used_synthesized_tests"] = bool(rec.get("used_synthesized_tests"))
            row["pass_rate"] = _to_float(rec.get("pass_rate"))
            row["attempt_count"] = _to_float(rec.get("attempt_count"))
            row["stagnation_events"] = _to_float(rec.get("stagnation_events"))
            row["pass_at_final"] = bool(rec.get("pass_at_final"))
            row["llm_calls_used"] = _to_float(rec.get("llm_calls_used"))
            row["timed_out"] = bool(rec.get("timed_out"))
            row["verifier_score"] = _to_float(rec.get("verifier_score"))
            row["unit_test_success"] = bool(rec.get("unit_test_success"))
            row["deliverable_success"] = bool(rec.get("deliverable_success"))
            row["self_check_only"] = bool(rec.get("self_check_only"))
            row["self_check_pass_rate"] = _to_float(rec.get("self_check_pass_rate"))
            row["self_check_passed"] = bool(rec.get("self_check_passed"))
            row["memory_hint_count"] = int(rec.get("memory_hint_count", 0) or 0)
            row["memory_hints_retrieved"] = int(rec.get("memory_hints_retrieved", 0) or 0)
            writer.writerow(row)

    failure_rows = []
    for rec in records:
        status_value = str(rec.get("status", ""))
        if status_value in {"passed", "success"} or status_value.startswith("completed_"):
            continue
        if status_value.startswith("skipped"):
            continue
        failure_rows.append(rec)
    failure_columns = [
        "task_id",
        "dataset_id",
        "status",
        "error_type",
        "failure_signature",
        "failing_tests",
        "last_error",
        "artifact_path",
        "tests_source",
        "raw_agent_response_path",
        "repaired_agent_response_path",
    ]
    with failures_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=failure_columns)
        writer.writeheader()
        for rec in failure_rows:
            writer.writerow({col: rec.get(col, "") for col in failure_columns})

    per_task_metrics_path = run_dir / "per_task_metrics.jsonl"
    with per_task_metrics_path.open("w", encoding="utf-8") as fp:
        for rec in records:
            attempt_blob = rec.get("attempt_logs", "")
            try:
                attempt_data = json.loads(attempt_blob) if attempt_blob else []
            except json.JSONDecodeError:
                attempt_data = []
            payload = {
                "task_id": rec.get("task_id"),
                "status": rec.get("status"),
                "llm_calls_used": rec.get("llm_calls_used", 0.0),
                "timed_out": bool(rec.get("timed_out")),
                "timeout_reason": rec.get("timeout_reason", ""),
                "attempt_logs": attempt_data,
            }
            fp.write(json.dumps(payload) + "\n")

    return {
        "summary": summary_path,
        "summary_md": markdown_path,
        "per_problem": per_problem_path,
        "failures": failures_path,
        "per_task_metrics": per_task_metrics_path,
    }
def _deduplicate_summary_records(records: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Keep the highest-priority record for each task."""

    best: Dict[str, Tuple[int, int, Dict[str, object]]] = {}
    for idx, rec in enumerate(records):
        task_id = str(rec.get("task_id") or f"task_{idx}")
        status_value = str(rec.get("status", ""))
        priority = 1 if status_value.startswith("skipped") else 0
        candidate = (priority, idx, rec)
        existing = best.get(task_id)
        if existing is None or candidate[:2] < existing[:2]:
            best[task_id] = candidate
    deduped = [entry[2] for entry in sorted(best.values(), key=lambda item: item[1])]
    return deduped
