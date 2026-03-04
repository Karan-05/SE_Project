"""Run decomposition strategies on a small real (or synthetic) slice."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.config import PathConfig
from src.decomposition.interfaces import DecompositionContext
from src.decomposition.runners.run_on_task import run_strategy_on_task
from src.decomposition.strategies._utils import run_tests

REPORTS_DIR = PathConfig().reports_root / "decomposition"
REAL_CSV = REPORTS_DIR / "real_slice_metrics.csv"
REAL_MD = REPORTS_DIR / "real_slice_summary.md"
BENCHMARK_FILE = PathConfig().experiments_dir / "decomposition" / "benchmark_tasks.json"


def _load_real_tasks(limit: int = 5) -> List[Dict]:
    processed_tasks = PathConfig().processed_data / "tasks.parquet"
    if processed_tasks.exists():
        df = pd.read_parquet(processed_tasks).head(limit)
        tasks: List[Dict] = []
        for row in df.to_dict(orient="records"):
            prize = float(row.get("prize", 1000))
            difficulty = float(row.get("difficulty", 3) or 3)
            task = {
                "id": f"real_{row.get('task_id', len(tasks))}",
                "problem_statement": f"Return prize minus difficulty for challenge {row.get('task_id')}.",
                "statement": f"Compute prize - difficulty for {row.get('title', 'task')}.",
                "type": "mixed",
                "difficulty": "M",
                "pitfalls": ["float_precision"],
                "split": "real",
                "examples": [{"input": f"prize={prize}, difficulty={difficulty}", "output": f"{prize - difficulty}"}],
                "inputs": "float, float",
                "outputs": "float",
                "entry_point": "solve",
                "tests": [
                    {"input": [[prize, difficulty]], "expected": prize - difficulty},
                    {"input": [[prize / 2, difficulty / 2]], "expected": prize / 2 - difficulty / 2},
                ],
                "reference_solution": "def solve(prize, difficulty):\n    return prize - difficulty\n",
            }
            tasks.append(task)
        return tasks
    # Fallback synthetic slice
    with BENCHMARK_FILE.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    fallback = []
    for task in data[:limit]:
        dup = dict(task)
        dup.setdefault("split", "synthetic")
        dup.setdefault("statement", dup.get("problem_statement"))
        fallback.append(dup)
    return fallback


def _baseline_result(task: Dict) -> Dict[str, float]:
    ctx = DecompositionContext(
        task_id=task["id"],
        problem_statement=task.get("problem_statement", task.get("statement", "")),
        metadata=task,
    )
    tests = run_tests(task.get("reference_solution", "def solve(*args):\n    return None"), ctx)
    pass_rate = sum(1 for t in tests if t["status"] == "pass") / max(1, len(tests))
    return {"pass_rate": pass_rate}


def run_real_slice(limit: int = 5) -> pd.DataFrame:
    tasks = _load_real_tasks(limit)
    strategies = ["contract_first", "pattern_skeleton", "multi_view"]
    records: List[Dict[str, float]] = []
    for task in tasks:
        for strategy in strategies:
            result = run_strategy_on_task(strategy, task)
            records.append(
                {
                    "task_id": task["id"],
                    "strategy": strategy,
                    "pass_rate": result.metrics.get("pass_rate", 0.0),
                    "tokens_used": result.metrics.get("tokens_used", 0.0),
                    "planning_time": result.metrics.get("planning_time", 0.0),
                }
            )
        baseline = _baseline_result(task)
        records.append(
            {
                "task_id": task["id"],
                "strategy": "baseline_direct",
                "pass_rate": baseline["pass_rate"],
                "tokens_used": 0.0,
                "planning_time": 0.0,
            }
        )
    df = pd.DataFrame(records)
    df.to_csv(REAL_CSV, index=False)
    top = df.groupby("strategy")["pass_rate"].mean().sort_values(ascending=False)
    lines = ["# Real Slice Summary", ""]
    source = "processed parquet" if (PathConfig().processed_data / "tasks.parquet").exists() else "synthetic fallback"
    lines.append(f"Source: {source} (n={limit} tasks)")
    lines.append("")
    lines.append("Top strategies:")
    for strategy, value in top.head(3).items():
        lines.append(f"- {strategy}: {value:.2%} average pass-rate")
    REAL_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return df


def main() -> None:  # pragma: no cover
    run_real_slice()
    print("Wrote real slice metrics to", REAL_CSV)


if __name__ == "__main__":  # pragma: no cover
    main()
