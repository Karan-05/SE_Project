"""Generate publication tables for the AEGIS-RL report."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def load_metrics(path: Path) -> List[Dict[str, float]]:
    if not path.exists():
        raise FileNotFoundError(f"Metrics CSV missing: {path}")
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def aggregate_by_method(metrics: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    for row in metrics:
        grouped[row["method"]].append(row)
    summaries: Dict[str, Dict[str, float]] = {}
    for method, rows in grouped.items():
        n = len(rows)
        success = sum(float(r["success"]) for r in rows) / n if n else 0.0
        avg_reward = sum(float(r["reward"]) for r in rows) / n if n else 0.0
        avg_steps = sum(float(r["steps"]) for r in rows) / n if n else 0.0
        avg_tokens = sum(float(r.get("token_spent", 0.0)) for r in rows) / n if n else 0.0
        avg_constraint = sum(float(r["constraint_penalty"]) for r in rows) / n if n else 0.0
        budgeted = sum(float(r.get("budgeted_success", 0.0)) for r in rows) / n if n else 0.0
        catastrophic = sum(float(r.get("catastrophic_failure", 0.0)) for r in rows) / n if n else 0.0
        entropy = sum(float(r.get("action_entropy", 0.0)) for r in rows) / n if n else 0.0
        summaries[method] = {
            "success_rate": success,
            "avg_reward": avg_reward,
            "avg_steps": avg_steps,
            "avg_tokens": avg_tokens,
            "avg_constraint": avg_constraint,
            "budgeted_success": budgeted,
            "catastrophic_failure": catastrophic,
            "action_entropy": entropy,
        }
    return summaries


def load_calibration(path: Path) -> Dict[str, Tuple[float, float]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["method"]: (float(row["brier"]), float(row["cost_mae"])) for row in reader}


def write_table(path: Path, header: List[str], rows: List[List[float | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    results_root = Path("results/aegis_rl/metrics")
    metrics = load_metrics(results_root / "metrics.csv")
    summaries = aggregate_by_method(metrics)
    calibration = load_calibration(results_root / "calibration.csv")

    write_table(
        Path("reports/ase2026_aegis/table_main.csv"),
        ["method", "success_rate", "avg_reward", "avg_steps", "avg_tokens", "avg_constraint", "budgeted_success", "catastrophic_failure", "action_entropy"],
        [
            [
                method,
                stats["success_rate"],
                stats["avg_reward"],
                stats["avg_steps"],
                stats["avg_tokens"],
                stats["avg_constraint"],
                stats.get("budgeted_success", 0.0),
                stats.get("catastrophic_failure", 0.0),
                stats.get("action_entropy", 0.0),
            ]
            for method, stats in summaries.items()
        ],
    )
    write_table(
        Path("reports/ase2026_aegis/table_ablation.csv"),
        ["method", "success_rate", "avg_reward", "avg_steps"],
        [
            [method, stats["success_rate"], stats["avg_reward"], stats["avg_steps"]]
            for method, stats in summaries.items()
            if "aegis_no" in method
        ],
    )
    write_table(
        Path("reports/ase2026_aegis/table_calibration.csv"),
        ["method", "brier", "cost_mae"],
        [[method, *calibration[method]] for method in calibration],
    )


if __name__ == "__main__":
    main()
