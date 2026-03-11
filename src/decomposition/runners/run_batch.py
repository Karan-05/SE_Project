"""Batch runner evaluating all strategies on benchmark tasks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.config import PROJECT_ROOT, ensure_reports_subdirs
from src.decomposition.registry import STRATEGIES
from src.decomposition.runners.run_on_task import run_strategy_on_task
from src.decomposition.interfaces import StrategyResult

BENCHMARK_FILE = PROJECT_ROOT / "experiments" / "decomposition" / "benchmark_tasks.json"
REPORT_DIR = PROJECT_ROOT / "reports" / "decomposition"


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_tasks(tasks_file: Path | None = None) -> List[Dict]:
    path = tasks_file or BENCHMARK_FILE
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _result_to_row(strategy: str, task: Dict, result: StrategyResult) -> Dict[str, object]:
    row: Dict[str, object] = {
        "strategy": strategy,
        "task_id": task["id"],
        "task_type": task.get("type", task.get("category", "unknown")),
        "category": task.get("category", "unknown"),
        "task_difficulty": task.get("difficulty", "unknown"),
        "pitfalls": ";".join(task.get("pitfalls", [])),
        "tag_count": len(task.get("tags", [])),
        "split": task.get("split", "train"),
        "pass_rate": result.metrics.get("pass_rate", 0.0),
        "num_tests": result.metrics.get("num_tests", 0),
        "decomposition_steps": result.metrics.get("decomposition_steps", 0),
        "tokens_used": result.metrics.get("tokens_used", 0),
        "planning_time": result.metrics.get("planning_time", 0),
        "initial_pass": result.metrics.get("initial_pass", 0.0),
        "final_pass": result.metrics.get("final_pass", 0.0),
        "repair_rounds": result.metrics.get("repair_rounds", 0.0),
        "total_tests_run": result.metrics.get("total_tests_run", 0.0),
        "subtasks_repaired": result.metrics.get("subtasks_repaired", 0.0),
        "localized_repairs": result.metrics.get("localized_repairs", 0.0),
        "localized_repair_rate": result.metrics.get("localized_repair_rate", 0.0),
        "compile_failed": result.metrics.get("compile_failed", False),
        "final_status": result.metrics.get("final_status", ""),
        "round_trace_path": result.metrics.get("round_trace_path", ""),
        "subtasks_targeted": result.metrics.get("subtasks_targeted", ""),
    }
    for key in ["contract_completeness", "pattern_confidence", "iterations", "view_consistency", "num_deltas", "critic_comments", "trace_length"]:
        if key in result.metrics:
            row[key] = result.metrics[key]
    diagnostics = getattr(result, "plan").diagnostics if result.plan else {}
    if diagnostics:
        if "contract_length" in diagnostics:
            row["contract_length"] = _to_float(diagnostics.get("contract_length"))
        if "planning_tokens" in diagnostics:
            row.setdefault("planning_tokens_diag", _to_float(diagnostics.get("planning_tokens")))
        if "planning_time" in diagnostics:
            row.setdefault("planning_time_diag", _to_float(diagnostics.get("planning_time")))
    if result.round_traces:
        row["round_traces_json"] = json.dumps(result.round_traces)
    return row


def _should_track_case(result: StrategyResult) -> bool:
    initial = float(result.metrics.get("initial_pass", 0.0) or 0.0)
    final_status = str(result.metrics.get("final_status", ""))
    repairs = float(result.metrics.get("repair_rounds", 0.0) or 0.0)
    return initial < 1.0 or repairs > 0.0 or final_status != "passed_initial"


def _case_entry(task: Dict, strategy: str, result: StrategyResult) -> Dict[str, object]:
    return {
        "task_id": task["id"],
        "task_title": task.get("title", task.get("id")),
        "task_type": task.get("type", task.get("category", "unknown")),
        "difficulty": task.get("difficulty", "unknown"),
        "strategy": strategy,
        "plan": result.plan,
        "rounds": result.round_traces,
        "metrics": result.metrics,
    }


def _write_case_studies(entries: List[Dict[str, object]]) -> None:
    path = REPORT_DIR / "repair_case_studies.md"
    lines = ["# Repair Case Studies", ""]
    if not entries:
        lines.append("All recorded strategies passed on the initial attempt. No repair loops were triggered.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    for entry in entries:
        plan = entry["plan"]
        rounds = entry["rounds"] or []
        metrics = entry["metrics"]
        lines.append(f"## {entry['task_id']} – {entry['strategy']}")
        lines.append(f"- Task type: {entry['task_type']} | difficulty: {entry['difficulty']}")
        lines.append(f"- Subtasks: {', '.join(plan.subtasks) if plan.subtasks else 'None'}")
        if plan.tests:
            lines.append(f"- Tests sketched in plan: {', '.join(plan.tests[:4])}")
        if rounds:
            first = rounds[0]
            failing = ", ".join(first.get("failing_tests", [])) or "none"
            lines.append(
                f"- Initial status: {first.get('status')} (pass_rate={first.get('pass_rate', 0):.2f}) "
                f"failing tests: {failing}"
            )
        repairs = rounds[1:] if len(rounds) > 1 else []
        if repairs:
            lines.append("- Repair rounds:")
            for trace in repairs:
                failing = ", ".join(trace.get("failing_tests", [])) or "none"
                lines.append(
                    f"  - Round {trace.get('round')} "
                    f"(subtask={trace.get('subtask')} localized={trace.get('localized')}): "
                    f"status={trace.get('status')} pass_rate={trace.get('pass_rate', 0):.2f} "
                    f"failing tests={failing}"
                )
        else:
            lines.append("- Repair rounds: none executed")
        lines.append(f"- Final outcome: {metrics.get('final_status', 'unknown')} (final_pass={metrics.get('final_pass', 0.0)})")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_repair_summary(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby("strategy")
        .agg(
            initial_success_rate=("initial_pass", "mean"),
            final_success_rate=("final_pass", "mean"),
            avg_repair_rounds=("repair_rounds", "mean"),
            avg_subtasks_repaired=("subtasks_repaired", "mean"),
            localized_repair_rate=("localized_repair_rate", "mean"),
            compile_failure_rate=("compile_failed", "mean"),
        )
        .reset_index()
    )
    agg["repair_gain"] = agg["final_success_rate"] - agg["initial_success_rate"]
    agg.to_csv(REPORT_DIR / "strategy_repair_summary.csv", index=False)
    return agg


def _write_repair_narrative(summary_df: pd.DataFrame) -> None:
    path = REPORT_DIR / "repair_summary.md"
    lines = ["# Repair-Aware Summary", ""]
    if summary_df.empty:
        lines.append("No strategies were evaluated.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    best_final = summary_df.sort_values("final_success_rate", ascending=False).iloc[0]
    best_localized = summary_df.sort_values("localized_repair_rate", ascending=False).iloc[0]
    avg_depth = summary_df["avg_subtasks_repaired"].mean()
    if summary_df["final_success_rate"].sum() == 0:
        lines.append(
            "No strategy achieved a passing repair in this run (likely due to mock LLM output), "
            "but the new loop captured compile failures and repair attempts for auditing."
        )
    else:
        lines.append(
            f"**{best_final['strategy']}** delivered the strongest final success rate "
            f"({best_final['final_success_rate']:.2f}) with a gain of {best_final['repair_gain']:.2f} "
            "over its initial solves."
        )
    lines.append(
        f"Localized repairs were most common for **{best_localized['strategy']}** "
        f"(localized rate {best_localized['localized_repair_rate']:.2f})."
    )
    lines.append(
        f"On average, strategies touched {avg_depth:.2f} subtasks when attempting repairs, "
        "providing a measurable link between decomposition depth and recovery attempts."
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(tasks_file: Path | None = None, *, max_repair_rounds: int | None = None) -> pd.DataFrame:
    if max_repair_rounds is not None:
        os.environ["DECOMP_MAX_REPAIR_ROUNDS"] = str(max_repair_rounds)
    tasks = _load_tasks(tasks_file)
    ensure_reports_subdirs()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    case_entries: List[Dict[str, object]] = []
    for task in tasks:
        for name in STRATEGIES:
            result = run_strategy_on_task(name, task)
            rows.append(_result_to_row(name, task, result))
            if _should_track_case(result):
                case_entries.append(_case_entry(task, name, result))

    df = pd.DataFrame(rows)
    df.to_csv(REPORT_DIR / "strategy_comparison.csv", index=False)
    _write_case_studies(case_entries)
    repair_summary = _write_repair_summary(df)
    _write_repair_narrative(repair_summary)

    cost_vs_quality = (
        df.groupby("strategy")
        .agg(avg_pass_rate=("pass_rate", "mean"), avg_tokens=("tokens_used", "mean"))
        .reset_index()
    )
    cost_vs_quality.to_csv(REPORT_DIR / "cost_vs_quality.csv", index=False)

    ablation = (
        df.groupby(["category", "strategy"])["pass_rate"].mean().reset_index()
    )
    ablation.to_csv(REPORT_DIR / "ablation_by_task_type.csv", index=False)

    top_strategies = df.groupby("strategy")["pass_rate"].mean().sort_values(ascending=False)
    summary_lines = ["# Strategy Comparison", "", "Top strategies by average pass-rate:"]
    for strat, value in top_strategies.head(3).items():
        summary_lines.append(f"- **{strat}**: {value:.3f}")
    summary_lines.append("")
    summary_lines.append("Repair-aware metrics:")
    for _, row in repair_summary.iterrows():
        summary_lines.append(
            f"- **{row['strategy']}** initial={row['initial_success_rate']:.2f} "
            f"final={row['final_success_rate']:.2f} gain={row['repair_gain']:.2f} "
            f"avg_repair_rounds={row['avg_repair_rounds']:.2f} localized_rate={row['localized_repair_rate']:.2f}"
        )
    (REPORT_DIR / "strategy_comparison.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return df


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run decomposition benchmark suite.")
    parser.add_argument("--tasks-file", type=Path, default=BENCHMARK_FILE)
    parser.add_argument("--max-repair-rounds", type=int, default=None, help="Override the max repair rounds per task.")
    args = parser.parse_args()
    run_benchmark(args.tasks_file, max_repair_rounds=args.max_repair_rounds)
    print("Wrote reports to", REPORT_DIR)


if __name__ == "__main__":  # pragma: no cover
    main()
