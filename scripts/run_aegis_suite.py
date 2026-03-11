"""Helper to launch the AEGIS RL pipeline with sane defaults."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports" / "ase2026_aegis"


def _env_with_path() -> dict[str, str]:
    env = os.environ.copy()
    root_str = str(PROJECT_ROOT)
    current = env.get("PYTHONPATH")
    if current:
        paths = current.split(os.pathsep)
        if root_str not in paths:
            paths.insert(0, root_str)
            env["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        env["PYTHONPATH"] = root_str
    return env


def _run_once(args: argparse.Namespace, replica: int) -> None:
    env = _env_with_path()
    cmd = [
        sys.executable,
        "experiments/run_aegis_rl.py",
        "--episodes-per-agent",
        str(args.episodes_per_agent),
        "--episodes",
        str(args.episodes),
    ]
    if args.use_reduced_actions:
        cmd.append("--use-reduced-actions")
    if args.warm_start_episodes:
        cmd.extend(["--warm-start-episodes", str(args.warm_start_episodes)])
    if args.enable_curriculum:
        cmd.append("--enable-curriculum")
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT, env=env)
    summary = REPORTS_DIR / "table_main.csv"
    if summary.exists():
        snapshot = REPORTS_DIR / f"aegis_table_main_run{replica}.csv"
        shutil.copyfile(summary, snapshot)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AEGIS RL pipeline with consistent defaults.")
    parser.add_argument("--episodes-per-agent", type=int, default=16)
    parser.add_argument("--episodes", type=int, default=8)
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--use-reduced-actions", action="store_true")
    parser.add_argument("--warm-start-episodes", type=int, default=0)
    parser.add_argument("--enable-curriculum", action="store_true")
    args = parser.parse_args()
    for replica in range(args.replicas):
        _run_once(args, replica)


if __name__ == "__main__":
    main()
