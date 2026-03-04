"""Batch runner evaluating all strategies on benchmark tasks."""
from __future__ import annotations

import json
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
    return row


def run_benchmark(tasks_file: Path | None = None) -> pd.DataFrame:
    tasks = _load_tasks(tasks_file)
    ensure_reports_subdirs()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, object]] = []
    for task in tasks:
        for name in STRATEGIES:
            result = run_strategy_on_task(name, task)
            rows.append(_result_to_row(name, task, result))

    df = pd.DataFrame(rows)
    df.to_csv(REPORT_DIR / "strategy_comparison.csv", index=False)

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
    (REPORT_DIR / "strategy_comparison.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return df


def main() -> None:  # pragma: no cover
    run_benchmark()
    print("Wrote reports to", REPORT_DIR)


if __name__ == "__main__":  # pragma: no cover
    main()
