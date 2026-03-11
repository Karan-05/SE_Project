#!/usr/bin/env python
"""CLI entrypoint for the real executable task evaluation harness."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.eval.execution_backend import PythonCallBackend
from src.eval.model_matrix import build_matrix, default_matrix
from src.eval.real_task_runner import RealTaskRunner, RunnerConfig
from src.eval.task_manifest import TaskManifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the real executable task evaluation harness.")
    parser.add_argument(
        "--tasks",
        type=Path,
        default=Path("experiments") / "decomposition" / "benchmark_tasks.json",
        help="Path to a JSON file containing tasks (default: benchmark tasks).",
    )
    parser.add_argument(
        "--task-ids",
        nargs="*",
        help="Optional list of task ids to run. Defaults to all tasks in the manifest.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of tasks to run.",
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        default=["contract_first"],
        help="Decomposition strategies to evaluate (default: contract_first).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM provider label for logging (default: use model_matrix.default_matrix).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name for logging (default: use model_matrix.default_matrix).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Generation temperature metadata for logging (default: 0.2).",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier (default: timestamp-based).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results") / "real_eval",
        help="Root directory for outputs (default: results/real_eval).",
    )
    parser.add_argument(
        "--no-traces",
        action="store_true",
        help="Disable recording decomposition traces.",
    )
    return parser.parse_args()


def build_strategy_matrix(strategies: Sequence[str], provider: str | None, model: str | None, temperature: float):
    if provider and model:
        return build_matrix(strategies, provider=provider, model=model, temperature=temperature)
    return default_matrix(strategies)


def main() -> None:
    args = parse_args()
    manifest = TaskManifest.from_path(args.tasks, task_ids=args.task_ids)
    if args.limit:
        manifest = manifest.filter(limit=args.limit)
    matrix = build_strategy_matrix(args.strategies, args.provider, args.model, args.temperature)
    backend = PythonCallBackend()
    config = RunnerConfig(
        run_id=args.run_id,
        output_root=args.output_dir,
        backend=backend,
        record_decomposition_traces=not args.no_traces,
    )
    runner = RealTaskRunner(config)
    results = runner.run(manifest, matrix)
    success = sum(1 for result in results if result.final_status == result.final_status.PASS_ALL_TESTS)
    print(f"Completed {len(results)} evaluations. PASS_ALL_TESTS={success}")


if __name__ == "__main__":
    main()
