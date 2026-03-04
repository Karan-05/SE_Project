"""Summarize Topcoder experiment runs and emit final results."""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
REPORTS_DIR = PROJECT_ROOT / "reports" / "experiments"

from src.experiments.topcoder.task_router import TaskType
from src.experiments.topcoder.reporting import SUCCESS_STATUSES

SUCCESS_STATUSES_LOWER = {status.lower() for status in SUCCESS_STATUSES}

PRESENTATION_MIN_ALGO = 5
PRESENTATION_MIN_NON_ALGO = 2


@dataclass
class RunArtifacts:
    run_id: str
    run_dir: Path
    per_problem: Path
    checkpoint: Path
    summary: Optional[Path]
    manifest: Optional[Path]
    deliverables: Path


def _find_run(run_id: Optional[str], latest: bool) -> RunArtifacts:
    if run_id and latest:
        raise ValueError("Specify either --run-id or --latest, not both.")
    if not run_id and not latest:
        raise ValueError("Must supply --run-id or --latest.")
    if run_id:
        run_dir = REPORTS_DIR / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run {run_id} not found under {REPORTS_DIR}")
    else:
        candidates: List[Path] = []
        for child in REPORTS_DIR.glob("*"):
            if not child.is_dir():
                continue
            per_problem = child / "per_problem.csv"
            checkpoint = child / "checkpoint.jsonl"
            if per_problem.exists() or checkpoint.exists():
                candidates.append(child)
        if not candidates:
            raise FileNotFoundError("No runs with per_problem.csv or checkpoint.jsonl found.")
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        run_dir = candidates[0]
        run_id = run_dir.name
    per_problem = run_dir / "per_problem.csv"
    checkpoint = run_dir / "checkpoint.jsonl"
    summary = run_dir / "summary.json"
    manifest = run_dir / "tasks_manifest.json"
    if not per_problem.exists() and not checkpoint.exists():
        raise FileNotFoundError(f"Run {run_id} missing both per_problem.csv and checkpoint.jsonl.")
    deliverables = run_dir / "deliverables"
    return RunArtifacts(
        run_id=run_id,
        run_dir=run_dir,
        per_problem=per_problem,
        checkpoint=checkpoint,
        summary=summary if summary.exists() else None,
        manifest=manifest if manifest.exists() else None,
        deliverables=deliverables,
    )


def _compute_metrics_for_artifacts(artifacts: RunArtifacts) -> Dict[str, object]:
    df = _load_records(artifacts)
    summary_data = _load_json(artifacts.summary)
    manifest_data = _load_manifest(artifacts.manifest)
    metrics = compute_metrics(df, summary_data, manifest_data, deliverables_dir=artifacts.deliverables)
    metrics["run_id"] = artifacts.run_id
    return metrics


def build_run_metrics(run_id: str) -> Tuple[Dict[str, object], RunArtifacts]:
    artifacts = _find_run(run_id, latest=False)
    metrics = _compute_metrics_for_artifacts(artifacts)
    return metrics, artifacts


def _load_records(artifacts: RunArtifacts) -> pd.DataFrame:
    if artifacts.per_problem.exists():
        df = pd.read_csv(artifacts.per_problem)
    else:
        records: List[Dict[str, object]] = []
        with artifacts.checkpoint.open("r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        df = pd.DataFrame(records)
    if "task_id" not in df.columns:
        raise ValueError("per_problem data missing 'task_id' column.")
    # Normalize optional columns
    for column, default in [
        ("status", ""),
        ("pass_at_final", False),
        ("pass_rate", 0.0),
        ("attempt_count", 0.0),
        ("fallback_path", ""),
        ("stagnation_events", 0.0),
        ("tests_source", ""),
        ("tests_path", ""),
        ("duration_seconds", 0.0),
        ("unit_test_success", False),
        ("deliverable_success", False),
    ]:
        if column not in df.columns:
            df[column] = default
    return df


def _load_json(path: Optional[Path]) -> Dict[str, object]:
    if not path:
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_manifest(manifest_path: Optional[Path]) -> Dict[str, object]:
    data = _load_json(manifest_path)
    if not data:
        return {}
    entries = data.get("tasks", [])
    if isinstance(entries, list):
        return {
            "entries": entries,
            "count": len(entries),
            "unique_task_ids": len({str(entry.get("id")) for entry in entries if entry.get("id")}),
        }
    return {}


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _count_deliverable_artifacts(deliverables_dir: Optional[Path]) -> int:
    if not deliverables_dir or not deliverables_dir.exists():
        return 0
    allowed_suffixes = {".md", ".diff", ".txt", ".sql"}
    count = 0
    for path in deliverables_dir.glob("*"):
        if not path.is_file():
            continue
        name = path.name
        if "_agent_" in name or name.endswith("_agent_parse_diag.json"):
            continue
        if path.suffix.lower() not in allowed_suffixes:
            continue
        count += 1
    return count


def compute_metrics(
    df: pd.DataFrame,
    summary: Dict[str, object],
    manifest: Dict[str, object],
    *,
    deliverables_dir: Optional[Path] = None,
) -> Dict[str, object]:
    statuses = df["status"].fillna("")
    priorities = statuses.str.startswith("skipped").astype(int)
    df_with_priority = df.assign(_priority=priorities, _idx=range(len(df)))
    dedup = (
        df_with_priority.sort_values(["task_id", "_priority", "_idx"])
        .drop_duplicates("task_id", keep="first")
        .drop(columns=["_priority", "_idx"])
    )
    total_rows = len(df)
    unique_tasks = len(dedup)
    manifest_unique = manifest.get("unique_task_ids") or manifest.get("count") or unique_tasks
    manifest_unique = int(manifest_unique)
    status_series = dedup["status"].fillna("")
    status_lower = status_series.str.lower()
    actionable_mask = (~status_series.str.startswith("skipped")) & status_series.ne("")
    attempted = int(actionable_mask.sum())
    success_mask = status_lower.isin(SUCCESS_STATUSES_LOWER)
    attempted_success_total = int((actionable_mask & success_mask).sum())
    attempted_failed_total = attempted - attempted_success_total
    parse_failures_total = int((status_lower == "skipped_parse_failure").sum())
    non_actionable_labels = {"skipped_insufficient_context", "skipped_non_actionable", "skipped_non_coding_task"}
    non_actionable_total = int(status_lower.isin(non_actionable_labels).sum())
    resolved_types = dedup.get("resolved_task_type", pd.Series([""] * len(dedup))).fillna("")
    if resolved_types.eq("").all() and "task_type" in dedup:
        resolved_types = dedup["task_type"].fillna("")
    resolved_lower = resolved_types.str.lower()
    tests_source_series = dedup.get("tests_source", pd.Series([""] * len(dedup))).fillna("").str.lower()
    algo_mask = resolved_lower == TaskType.ALGO_CODING.value
    non_coding_mask = resolved_lower.isin(
        {
            TaskType.REPO_PATCH.value,
            TaskType.API_BACKEND.value,
            TaskType.ARCHITECTURE_DOC.value,
            TaskType.DATA_ETL.value,
        }
    )
    unit_test_success_series = dedup.get("unit_test_success", pd.Series([False] * len(dedup))).fillna(False).astype(bool)
    deliverable_success_series = dedup.get("deliverable_success", pd.Series([False] * len(dedup))).fillna(False).astype(bool)
    algo_verified_mask = algo_mask & (~tests_source_series.isin({"synthesized", "self_check"}))
    algo_verified_attempted = int((actionable_mask & algo_verified_mask).sum())
    algo_verified_solved = int((actionable_mask & algo_verified_mask & unit_test_success_series).sum())
    pass_at_final = (algo_verified_solved / algo_verified_attempted) if algo_verified_attempted else 0.0
    attempted_algo = int((actionable_mask & algo_mask).sum())
    solved_algo = int((actionable_mask & algo_mask & unit_test_success_series).sum())
    attempted_non_coding = int((actionable_mask & non_coding_mask).sum())
    completed_deliverables = int((actionable_mask & non_coding_mask & deliverable_success_series).sum())
    deliverable_success_rate = (
        completed_deliverables / attempted_non_coding if attempted_non_coding else 0.0
    )
    deliverable_artifacts = _count_deliverable_artifacts(deliverables_dir)
    skipped_counts: Dict[str, int] = {}
    for status, count in status_series[status_series.str.startswith("skipped")].value_counts().items():
        skipped_counts[status] = int(count)
    type_breakdown: Dict[str, Dict[str, int]] = {}
    resolved_for_breakdown = resolved_lower.where(resolved_lower != "", other="unknown")
    for type_value in resolved_for_breakdown.unique():
        mask = (resolved_for_breakdown == type_value) & actionable_mask
        attempted_type = int(mask.sum())
        if not attempted_type:
            continue
        success_type = int((mask & success_mask).sum())
        type_breakdown[type_value] = {
            "attempted": attempted_type,
            "success": success_type,
            "failed": attempted_type - success_type,
        }
    attempted_df = dedup[actionable_mask]
    attempt_counts = attempted_df.get("attempt_count", pd.Series([], dtype=float)).apply(_safe_float).tolist()
    avg_attempts = statistics.mean(attempt_counts) if attempt_counts else 0.0
    median_attempts = statistics.median(attempt_counts) if attempt_counts else 0.0
    p90_attempts = statistics.quantiles(attempt_counts, n=10)[-1] if len(attempt_counts) >= 10 else (max(attempt_counts) if attempt_counts else 0.0)
    fallback_rate = (
        attempted_df["fallback_path"].fillna("").str.contains("->").mean() if not attempted_df.empty else 0.0
    )
    stagnation_rate = (
        (attempted_df.get("stagnation_events", 0).fillna(0).astype(float) > 0).mean()
        if not attempted_df.empty
        else 0.0
    )
    attempt_success_series = (
        attempted_df.get("unit_test_success", pd.Series([False] * len(attempted_df))).fillna(False).astype(bool)
        | attempted_df.get("deliverable_success", pd.Series([False] * len(attempted_df))).fillna(False).astype(bool)
    )
    retries_exhausted_count = int(
        ((attempted_df.get("attempt_count", 0).astype(float) >= 10) & (~attempt_success_series)).sum()
    )
    test_source_series_attempted = (
        attempted_df.get("tests_source", pd.Series([""] * len(attempted_df))).fillna("").str.lower()
    )
    synth_mask = test_source_series_attempted.isin({"synthesized", "self_check"})
    attempted_with_extracted = int((~synth_mask).sum())
    attempted_with_synthesized = int(synth_mask.sum())
    extracted_successes = int(((~synth_mask) & attempted_df.get("unit_test_success", pd.Series([False] * len(attempted_df))).fillna(False).astype(bool)).sum())
    synthesized_successes = int(((synth_mask) & attempted_df.get("unit_test_success", pd.Series([False] * len(attempted_df))).fillna(False).astype(bool)).sum())
    algo_mask_attempted = algo_mask[actionable_mask] if not attempted_df.empty else pd.Series([], dtype=bool)
    self_check_mask = (test_source_series_attempted == "self_check") & algo_mask_attempted
    self_check_attempted = int(self_check_mask.sum())
    self_check_passed_series = attempted_df.get("self_check_passed", pd.Series([False] * len(attempted_df))).fillna(False).astype(bool)
    self_check_pass = int((self_check_mask & self_check_passed_series).sum())
    self_check_pass_rate = (self_check_pass / self_check_attempted) if self_check_attempted else 0.0
    success_rate_extracted = (
        extracted_successes / attempted_with_extracted if attempted_with_extracted else 0.0
    )
    success_rate_synthesized = (
        synthesized_successes / attempted_with_synthesized if attempted_with_synthesized else 0.0
    )
    runtime = summary.get("runtime", {}) if isinstance(summary.get("runtime"), dict) else {}
    start_time = runtime.get("start_time")
    end_time = runtime.get("end_time")
    wall_time = _safe_float(runtime.get("total_wall_time_seconds"))
    if not start_time or not end_time:
        start_time = dedup.get("start_time", pd.Series([], dtype=str)).min()
        end_time = dedup.get("end_time", pd.Series([], dtype=str)).max()
        if start_time and end_time:
            try:
                wall_time = (
                    datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)
                ).total_seconds()
            except Exception:
                wall_time = 0.0
    avg_wall_time_per_attempted = (wall_time / attempted) if attempted and wall_time else 0.0
    llm_calls_total = _safe_float(summary.get("llm_calls_total"))
    if not llm_calls_total:
        llm_calls_total = 0.0
    llm_calls_avg = (llm_calls_total / attempted) if attempted else 0.0
    discovered_rows = int(summary.get("total_problems") or manifest.get("count") or total_rows)
    duplicates = discovered_rows - unique_tasks if discovered_rows >= unique_tasks else 0
    manifest_count = int(manifest.get("count") or discovered_rows)
    filtered_out = manifest_count - discovered_rows if manifest_count > discovered_rows else 0
    datasets_count = len({entry.get("dataset_id") for entry in manifest.get("entries", []) if entry.get("dataset_id")}) or dedup["dataset_id"].nunique()
    progress = unique_tasks / manifest_unique if manifest_unique else 1.0
    evaluation_coverage = (attempted / unique_tasks) if unique_tasks else 0.0
    evaluation_coverage = max(0.0, min(1.0, evaluation_coverage))
    recon_table = {
        "discovered_rows": discovered_rows,
        "unique_tasks": unique_tasks,
        "duplicates": duplicates,
        "filtered_out": filtered_out,
        "manifest_total": manifest_count,
        "dataset_files": datasets_count,
    }
    llm_available = summary.get("llm_available")
    if llm_available is None:
        llm_available = True
    validity = "VALID"
    if attempted > 0 and llm_calls_total == 0:
        validity = "INVALID_NO_LLM"
    elif attempted == 0:
        validity = "NO_ATTEMPTS"
    summary_validity = summary.get("run_validity")
    if summary_validity:
        validity = summary_validity
    metrics = {
        "run_id": summary.get("run_id") or "",
        "total_rows": total_rows,
        "total_unique_task_ids": unique_tasks,
        "manifest_unique_task_ids": manifest_unique,
        "llm_provider": summary.get("llm_provider") or "",
        "attempted": attempted,
        "actionable_attempted_total": attempted,
        "attempted_success_total": attempted_success_total,
        "attempted_failed_total": attempted_failed_total,
        "parse_failures_total": parse_failures_total,
        "non_actionable_total": non_actionable_total,
        "solved_pass_final": algo_verified_solved,
        "algo_verified_attempted": algo_verified_attempted,
        "pass_at_final": pass_at_final,
        "pass_at_final_extracted_only": pass_at_final,
        "attempted_algo": attempted_algo,
        "solved_algo": solved_algo,
        "attempted_non_coding": attempted_non_coding,
        "completed_deliverables": completed_deliverables,
        "deliverable_success_rate": deliverable_success_rate,
        "deliverable_artifacts": deliverable_artifacts,
        "task_type_breakdown": type_breakdown,
        "skipped_counts": skipped_counts,
        "attempted_with_extracted_tests": attempted_with_extracted,
        "attempted_with_synthesized_tests": attempted_with_synthesized,
        "success_rate_extracted": success_rate_extracted,
        "success_rate_synthesized": success_rate_synthesized,
        "self_check_attempted": self_check_attempted,
        "self_check_pass_rate": self_check_pass_rate,
        "avg_attempts": avg_attempts,
        "median_attempts": median_attempts,
        "p90_attempts": p90_attempts,
        "fallback_rate": fallback_rate,
        "stagnation_rate": stagnation_rate,
        "retries_exhausted_count": retries_exhausted_count,
        "llm_calls_total": llm_calls_total,
        "llm_calls_avg_per_task": llm_calls_avg,
        "llm_calls_per_attempted": (llm_calls_total / attempted) if attempted else 0.0,
        "llm_available": llm_available,
        "runtime": {
            "start_time": start_time,
            "end_time": end_time,
            "wall_time_seconds": wall_time,
            "avg_wall_time_per_attempted": avg_wall_time_per_attempted,
        },
        "reconciliation": recon_table,
        "progress_fraction": progress,
        "evaluation_coverage": evaluation_coverage,
        "pipeline_status": "COMPLETE" if progress >= 0.999 else "IN_PROGRESS",
        "validity": validity,
    }
    if summary.get("presentation_mode"):
        metrics["presentation_mode"] = True
        metrics["sample_size"] = summary.get("sample_size")
        metrics["sample_strategy"] = summary.get("sample_strategy")
        metrics["sample_seed"] = summary.get("sample_seed")
    if summary.get("stop_reason"):
        metrics["stop_reason"] = summary.get("stop_reason")
    return metrics


def evaluate_gate(metrics: Dict[str, object], presentation_mode: bool) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    mock_demo = metrics.get("validity") == "DEMO_ONLY_MOCK"
    if not mock_demo:
        if metrics.get("llm_calls_total", 0.0) <= 0:
            reasons.append("llm_calls_total == 0")
        elif metrics.get("actionable_attempted_total", 0) > 0 and metrics.get("llm_calls_per_attempted", 0.0) <= 0:
            reasons.append("llm_calls_per_attempted == 0")
    if presentation_mode:
        if metrics.get("attempted_algo", 0) < PRESENTATION_MIN_ALGO:
            reasons.append(f"only {metrics.get('attempted_algo', 0)} algo tasks attempted (need {PRESENTATION_MIN_ALGO})")
        if metrics.get("attempted_non_coding", 0) < PRESENTATION_MIN_NON_ALGO:
            reasons.append(
                f"only {metrics.get('attempted_non_coding', 0)} non-algo tasks routed "
                f"(need {PRESENTATION_MIN_NON_ALGO})"
            )
        if metrics.get("deliverable_artifacts", 0) < PRESENTATION_MIN_NON_ALGO:
            reasons.append("insufficient non-algo deliverable artifacts")
    return not reasons, reasons


def _format_rate(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_markdown(metrics: Dict[str, object], artifacts: RunArtifacts) -> str:
    run_id = artifacts.run_id
    progress_pct = metrics["progress_fraction"] * 100
    coverage_pct = metrics["evaluation_coverage"] * 100
    validity = metrics.get("validity", "VALID")
    validity_note = ""
    if validity == "INVALID_NO_LLM":
        validity_note = " — configure an LLM provider or disable allow-no-llm if you only want to catalog tasks."
    elif validity == "NO_ATTEMPTS":
        validity_note = " — no tasks were attempted."
    elif validity == "DEMO_ONLY_MOCK":
        validity_note = " — Gates relaxed for mock provider; not comparable to real-provider results."
    lines = [
        f"# TopCoder Experiment Final Results — {run_id}",
        "",
        f"> **Pipeline Status:** {metrics.get('pipeline_status', 'UNKNOWN')} ({progress_pct:.2f}% processed)",
        f"> **Evaluation Coverage:** {coverage_pct:.2f}% of unique tasks attempted",
        f"> **Run Validity:** {validity}{validity_note}",
        "",
    ]
    if metrics.get("stop_reason"):
        lines.append(f"> **Stop Reason:** {metrics.get('stop_reason')}")
        lines.append("")
    if metrics.get("presentation_mode"):
        lines.append(
            f"> **Sample Estimate:** sample_size={metrics.get('sample_size')} seed={metrics.get('sample_seed')} strategy={metrics.get('sample_strategy')}"
        )
        lines.append("")
    algo_ratio = (
        f"{metrics['solved_pass_final']}/{metrics['algo_verified_attempted']}"
        if metrics.get("algo_verified_attempted")
        else "0/0"
    )
    lines.extend(
        [
            f"- Total unique tasks: **{metrics['total_unique_task_ids']}** (manifest target {metrics['manifest_unique_task_ids']})",
            f"- Actionable attempted: **{metrics['actionable_attempted_total']}** (success {metrics['attempted_success_total']}, failed {metrics['attempted_failed_total']})",
            f"- Non-actionable (insufficient context): {metrics.get('non_actionable_total', 0)}",
            f"- Evaluation coverage: {_format_rate(metrics['evaluation_coverage'])} | Parse failures captured: {metrics['parse_failures_total']}",
            f"- Algo pass@final (extracted/provided tests only): {_format_rate(metrics['pass_at_final'])} ({algo_ratio})",
            f"- Algorithmic coding attempts: {metrics['attempted_algo']} | Unit-test verified solves: {metrics['solved_algo']}",
            f"- Self-checks (excluded from pass@final): attempted {metrics['self_check_attempted']} (pass {_format_rate(metrics['self_check_pass_rate'])})",
            f"- Non-coding deliverables: attempted {metrics['attempted_non_coding']} completed {metrics['completed_deliverables']} (success {_format_rate(metrics['deliverable_success_rate'])})",
        ]
    )
    if metrics["skipped_counts"]:
        skip_parts = [f"{k}={v}" for k, v in sorted(metrics["skipped_counts"].items())]
        lines.append(f"- Skipped breakdown: {', '.join(skip_parts)}")
    lines.extend(
        [
            "",
            "## Test Source Breakdown",
            f"- Extracted: attempted {metrics['attempted_with_extracted_tests']}, success {_format_rate(metrics['success_rate_extracted'])}",
            f"- Synthesized: attempted {metrics['attempted_with_synthesized_tests']}, success {_format_rate(metrics['success_rate_synthesized'])}",
            f"- Self-checks (not counted toward pass@final): attempted {metrics['self_check_attempted']}, pass {_format_rate(metrics['self_check_pass_rate'])}",
            "",
            "## Self-Verify Loop Stats",
            f"- Avg/Median/P90 attempts: {metrics['avg_attempts']:.2f} / {metrics['median_attempts']:.2f} / {metrics['p90_attempts']:.2f}",
            f"- Fallback rate: {_format_rate(metrics['fallback_rate'])}",
            f"- Stagnation rate: {_format_rate(metrics['stagnation_rate'])}",
            f"- Retries exhausted (>=10 attempts & failed): {metrics['retries_exhausted_count']}",
            "",
            "## LLM Usage",
            f"- Total calls: {metrics['llm_calls_total']:.0f}",
            f"- Avg calls per attempted task: {metrics['llm_calls_avg_per_task']:.2f}",
            f"- Calls per actionable attempted: {metrics.get('llm_calls_per_attempted', 0.0):.2f}",
            "",
            "## Runtime",
            f"- Start: {metrics['runtime']['start_time'] or 'unknown'}",
            f"- End: {metrics['runtime']['end_time'] or 'unknown'}",
            f"- Wall-clock: {metrics['runtime']['wall_time_seconds']:.2f}s",
            f"- Avg per attempted: {metrics['runtime']['avg_wall_time_per_attempted']:.2f}s",
            "",
            "## Dataset Reconciliation vs ~22k Memories",
            "Modern discovery sweeps multiple analytics exports and challenge snapshots, which inflates row counts beyond the historical ~22k challenges. "
            "Rows represent per-dataset challenge slices; deduplication reduces them to unique task IDs.",
            "",
            "| Metric | Count |",
            "| --- | --- |",
            f"| Discovered rows | {metrics['reconciliation']['discovered_rows']} |",
            f"| Unique tasks | {metrics['reconciliation']['unique_tasks']} |",
            f"| Duplicates | {metrics['reconciliation']['duplicates']} |",
            f"| Filtered out | {metrics['reconciliation']['filtered_out']} |",
            f"| Dataset files/sheets | {metrics['reconciliation']['dataset_files']} |",
            "",
            "## Files",
            f"- summary.json: `{artifacts.run_dir / 'summary.json'}`",
            f"- per_problem.csv: `{artifacts.run_dir / 'per_problem.csv'}`",
            f"- failures.csv: `{artifacts.run_dir / 'failures.csv'}`",
            f"- checkpoint.jsonl: `{artifacts.run_dir / 'checkpoint.jsonl'}`",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Topcoder experiment results.")
    parser.add_argument("--run-id", help="Specific run ID under reports/experiments.")
    parser.add_argument("--latest", action="store_true", help="Summarize the most recent run automatically.")
    args = parser.parse_args()

    artifacts = _find_run(args.run_id, args.latest)
    metrics = _compute_metrics_for_artifacts(artifacts)
    is_presentation = bool(metrics.get("presentation_mode"))
    gate_passed, gate_reasons = evaluate_gate(metrics, is_presentation)
    if gate_reasons:
        prefix = "Presentation gate not satisfied" if is_presentation else "Run validity issues"
        print(f"{prefix}: " + "; ".join(gate_reasons))
    markdown = render_markdown(metrics, artifacts)
    out_md = artifacts.run_dir / "final_results.md"
    out_json = artifacts.run_dir / "final_results.json"
    out_md.write_text(markdown, encoding="utf-8")
    out_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
