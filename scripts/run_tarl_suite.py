"""Automation helper for TARL-AEGIS runs."""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results" / "aegis_rl"
REPORTS_DIR = PROJECT_ROOT / "reports" / "ase2026_aegis"


def _ensure_py_path(env: dict[str, str]) -> dict[str, str]:
    updated = env.copy()
    root_str = str(PROJECT_ROOT)
    existing = updated.get("PYTHONPATH")
    if existing:
        paths = existing.split(os.pathsep)
        if root_str not in paths:
            paths.insert(0, root_str)
            updated["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        updated["PYTHONPATH"] = root_str
    return updated


def _run_once(args: argparse.Namespace, replica: int) -> Path:
    env = _ensure_py_path(os.environ)
    cmd = [
        sys.executable,
        "experiments/run_tarl_aegis.py",
        "--episodes",
        str(args.episodes),
        "--episodes-per-agent",
        str(args.episodes_per_agent),
        "--override-threshold",
        str(args.override_threshold),
    ]
    if args.full_action_space:
        cmd.append("--full-action-space")
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT, env=env)
    metrics_path = RESULTS_DIR / "tarl_metrics.csv"
    replica_path = RESULTS_DIR / f"tarl_metrics_run{replica}.csv"
    replica_path.write_text(metrics_path.read_text(), encoding="utf-8")
    return replica_path


def _merge_metrics(metric_files: List[Path]) -> None:
    rows: List[List[str]] = []
    header: List[str] | None = None
    for file_path in metric_files:
        if not file_path.exists():
            continue
        with file_path.open("r", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            try:
                file_header = next(reader)
            except StopIteration:
                continue
            if header is None:
                header = file_header
            rows.extend(reader)
    if not header:
        raise RuntimeError("TARL metrics missing; ensure at least one run succeeded.")
    merged = RESULTS_DIR / "tarl_metrics.csv"
    with merged.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _write_summary(metric_file: Path) -> None:
    with metric_file.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        records = list(reader)
    if not records:
        return
    def avg(key: str) -> float:
        return mean(float(row.get(key, 0.0)) for row in records)
    summary = {
        "method": "tarl_aegis",
        "success_rate": avg("success"),
        "avg_reward": avg("reward"),
        "budgeted_success": avg("budgeted_success"),
        "override_rate": avg("override_rate"),
        "override_win_rate": avg("override_win_rate"),
        "override_regret_rate": avg("override_regret_rate"),
    }
    report_path = REPORTS_DIR / "tarl_table_main.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(summary.keys())
        writer.writerow(summary.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TARL-AEGIS multiple times and consolidate metrics.")
    parser.add_argument("--episodes", type=int, default=40, help="Evaluation episodes.")
    parser.add_argument("--episodes-per-agent", type=int, default=32, help="Logged episodes per baseline for Stage A.")
    parser.add_argument("--override-threshold", type=float, default=0.6, help="Classifier override threshold.")
    parser.add_argument("--replicas", type=int, default=1, help="How many independent runs to execute.")
    parser.add_argument("--full-action-space", action="store_true")
    args = parser.parse_args()
    metric_files = []
    for replica in range(args.replicas):
        metric_files.append(_run_once(args, replica))
    _merge_metrics(metric_files)
    _write_summary(RESULTS_DIR / "tarl_metrics.csv")


if __name__ == "__main__":
    main()
