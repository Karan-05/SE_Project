"""Validate and run the real-repo Topcoder benchmark in a single command."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from src.config import PathConfig
from src.decomposition.real_repo import RepoTaskHarness, RepoTaskSpec, load_repo_tasks
from src.decomposition.real_repo.preflight import run_preflight_checks, write_preflight_report
from src.decomposition.runners.run_real_repo_benchmark import BenchmarkPaths, run_real_repo_benchmark
from src.providers import llm


def _collect_tasks(sources: List[Path]) -> List[RepoTaskSpec]:
    tasks: List[RepoTaskSpec] = []
    for source in sources:
        tasks.extend(load_repo_tasks(source))
    return tasks


def _prepare_workspaces(tasks: List[RepoTaskSpec], output_root: Path) -> List[dict]:
    statuses: List[dict] = []
    for task in tasks:
        harness = RepoTaskHarness(task, "prep", output_root)
        statuses.append(
            {
                "task_id": task.task_id,
                "repo": str(task.repo_path),
                "setup_status": harness.setup_record.get("status", "unknown"),
                "setup_log": harness.setup_record.get("last_log", ""),
            }
        )
    return statuses


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Preflight + run the real Topcoder benchmark.")
    parser.add_argument("--task-root", action="append", type=Path, default=[], help="Task root directory (defaults to Topcoder pack).")
    parser.add_argument("--mode", choices=["dev", "real_world_research"], default="real_world_research")
    parser.add_argument("--strategies", type=str, default="contract_first,failure_mode_first", help="Comma-separated strategies.")
    parser.add_argument("--prep-only", action="store_true", help="Run setup/preflight without executing strategies.")
    parser.add_argument("--skip-oracle", action="store_true", help="Skip oracle/teacher baseline run.")
    parser.add_argument("--prep-output", type=Path, default=PathConfig().reports_root / "decomposition" / "workspace_prep", help="Where to store prep workspaces/logs.")
    args = parser.parse_args()

    default_root = PathConfig().experiments_dir / "real_repo_tasks" / "topcoder"
    sources = args.task_root or [default_root]
    tasks = _collect_tasks(list(sources))
    if not tasks:
        raise RuntimeError("No repo tasks found for the requested task roots.")
    provider = str(llm.CONFIG.provider or "unknown")
    model = str(llm.CONFIG.model or "")
    paths = BenchmarkPaths(args.mode)
    preflight = run_preflight_checks(tasks, task_sources=sources, mode=args.mode, provider=provider, model=model)
    write_preflight_report(preflight, paths.preflight_json, paths.preflight_md)
    if not preflight.ok:
        raise RuntimeError("Preflight failed; see preflight report for details.")

    prep_records = _prepare_workspaces(tasks, args.prep_output)
    for record in prep_records:
        print(f"[prep] {record['task_id']}: {record['setup_status']} ({record['setup_log']})")

    if args.prep_only:
        print("Prep complete; skipping benchmark run.")
        return
    strategy_list = [item.strip() for item in args.strategies.split(",") if item.strip()]
    run_real_repo_benchmark(
        sources,
        strategies=strategy_list,
        mode=args.mode,
        paths=paths,
        include_oracle=not args.skip_oracle,
    )
    print(f"Benchmark complete. Reports in {paths.root}")


if __name__ == "__main__":  # pragma: no cover
    main()
