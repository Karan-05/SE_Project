"""Run Reflexion-style ablations (memory/RL/repair) and export metrics."""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.research.reflexion import ReflexionConfig, run_reflexion_experiment


TASK_SUITE = [
    {"id": "algo_easy", "title": "Algo Warm-up", "complexity": 1.0},
    {"id": "repo_medium", "title": "Repo Patch", "complexity": 1.8},
    {"id": "doc_hard", "title": "Architecture Doc", "complexity": 2.4},
    {"id": "etl_spec", "title": "Data ETL", "complexity": 2.0},
    {"id": "api_backend", "title": "API Backend", "complexity": 2.2},
]


ABLATIONS = [
    (False, False, False),
    (True, False, False),
    (False, True, False),
    (False, False, True),
    (True, True, False),
    (True, False, True),
    (False, True, True),
    (True, True, True),
]


def _write_csv(rows: List[Dict[str, object]], path: Path) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(rows: List[Dict[str, object]], path: Path) -> None:
    lines = [
        "# Reflexion Research Ablations",
        "",
        "| Memory | RL | Repair | Pass Rate | Avg Attempts | Token Cost | Repair Rate | Gate Pass Rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {memory_enabled} | {rl_enabled} | {repair_enabled} | {pass_rate:.2f} | {avg_attempts:.2f} | "
            "{token_cost:.0f} | {repair_rate:.2f} | {gate_pass_rate:.2f} |".format(**row)
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Reflexion plan/execute/verify ablations.")
    parser.add_argument("--output-dir", type=Path, help="Directory for CSV/Markdown outputs.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic loops.")
    args = parser.parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_root = (args.output_dir or Path("reports") / "research" / "reflexion") / timestamp
    output_root.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    for enable_memory, enable_rl, enable_repair in ABLATIONS:
        config = ReflexionConfig(
            enable_memory=enable_memory,
            enable_rl=enable_rl,
            enable_repair=enable_repair,
        )
        metrics = run_reflexion_experiment(TASK_SUITE, config, seed=args.seed)
        rows.append(metrics)
    csv_path = output_root / "reflexion_results.csv"
    md_path = output_root / "reflexion_results.md"
    _write_csv(rows, csv_path)
    _write_markdown(rows, md_path)
    print(f"Wrote Reflexion metrics to {csv_path}")
    print(f"Markdown summary: {md_path}")


if __name__ == "__main__":
    main()
