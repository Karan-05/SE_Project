"""Runner helpers to execute a single strategy on a single task."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

from src.config import PROJECT_ROOT
from src.decomposition.interfaces import DecompositionContext, StrategyResult
from src.decomposition.self_verify import RetryConfig, execute_with_self_verification
from src.decomposition.registry import get_strategy


def _load_task(task: Dict | str) -> Dict:
    if isinstance(task, dict):
        return task
    task_path = Path(task)
    with task_path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _build_context(task: Dict) -> DecompositionContext:
    statement = task.get("problem_statement") or task.get("statement") or task.get("title", "")
    tags = task.get("tags")
    if not tags and task.get("type"):
        tags = [task["type"]]
    merged_metadata = dict(task)
    inner_metadata = task.get("metadata")
    if isinstance(inner_metadata, dict):
        merged_metadata.update(inner_metadata)
        memory_hints = inner_metadata.get("memory_hints") or []
    else:
        memory_hints = []
    if memory_hints:
        hints_text = "\n".join(f"- {hint}" for hint in memory_hints if hint)
        statement = f"{statement}\n\nMemory Hints:\n{hints_text}".strip()
    return DecompositionContext(
        task_id=task["id"],
        problem_statement=statement,
        tags=tags or [],
        difficulty=task.get("difficulty"),
        constraints=task.get("constraints"),
        examples=task.get("examples", []),
        metadata=merged_metadata,
        nearest_neighbors=task.get("neighbors", []),
        historical_stats=task.get("historical_stats"),
    )


def run_strategy_on_task(
    strategy_name: str,
    task: Dict | str,
    retry_config: RetryConfig | None = None,
    strategy_order: List[str] | None = None,
) -> StrategyResult:
    task_dict = _load_task(task)
    ctx = _build_context(task_dict)
    cfg = retry_config or RetryConfig.from_env()
    if strategy_order is not None:
        cfg = replace(cfg, strategy_order=strategy_order)
    order = cfg.strategy_order or [strategy_name]
    return execute_with_self_verification(ctx, order, cfg)


def main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run a decomposition strategy on a single task")
    parser.add_argument("strategy", choices=get_strategy.__globals__["STRATEGIES"].keys())
    parser.add_argument("--task-id", default="two_sum_sorted")
    parser.add_argument("--tasks-file", type=Path, default=PROJECT_ROOT / "experiments" / "decomposition" / "benchmark_tasks.json")
    args = parser.parse_args()

    with args.tasks_file.open("r", encoding="utf-8") as fp:
        tasks = {task["id"]: task for task in json.load(fp)}
    task = tasks[args.task_id]
    result = run_strategy_on_task(args.strategy, task)
    print(result.metrics)


if __name__ == "__main__":  # pragma: no cover
    main()
