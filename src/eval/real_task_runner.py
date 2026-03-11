"""High-level orchestration for the real task evaluation harness."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence

from src.config import PROJECT_ROOT
from src.decomposition.runners.run_on_task import run_strategy_on_task
from src.decomposition.self_verify import RetryConfig

from .decomposition_trace import summarize_strategy_result
from .execution_backend import ExecutionBackend, PythonCallBackend
from .model_matrix import ModelStrategy
from .result_schema import ExecutionSummary, FinalStatus, RealTaskResult
from .task_manifest import TaskManifest, TaskSpec


def _now_run_id() -> str:
    return time.strftime("real_eval_%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name)


@dataclass
class RunnerConfig:
    run_id: str | None = field(default_factory=_now_run_id)
    output_root: Path = PROJECT_ROOT / "results" / "real_eval"
    backend: ExecutionBackend = field(default_factory=PythonCallBackend)
    retry_config: RetryConfig = field(default_factory=RetryConfig.from_env)
    record_decomposition_traces: bool = True

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = _now_run_id()

    @property
    def run_dir(self) -> Path:
        return self.output_root / "runs" / str(self.run_id)

    @property
    def tasks_dir(self) -> Path:
        return self.run_dir / "tasks"


class RealTaskRunner:
    """Execute a set of tasks across a model/strategy matrix."""

    def __init__(self, config: RunnerConfig):
        self.config = config
        self.run_dir = config.run_dir
        self.tasks_dir = config.tasks_dir
        self.results_path = self.run_dir / "per_task_results.jsonl"
        self.traces_path = self.run_dir / "decomposition_traces.jsonl"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._save_config_snapshot()

    def _save_config_snapshot(self) -> None:
        snapshot = {
            "run_id": self.config.run_id,
            "backend": self.config.backend.name,
            "retry_config": self.config.retry_config.__dict__,
        }
        with (self.run_dir / "config_snapshot.json").open("w", encoding="utf-8") as fp:
            json.dump(snapshot, fp, indent=2, default=str)

    def run(self, manifest: TaskManifest, matrix: Sequence[ModelStrategy]) -> List[RealTaskResult]:
        results: List[RealTaskResult] = []
        for model in matrix:
            for task in manifest:
                result = self._evaluate_task(task, model)
                results.append(result)
                self._append_jsonl(self.results_path, result.to_dict())
                if self.config.record_decomposition_traces and result.decomposition:
                    trace_entry = {
                        "task_id": task.task_id,
                        "strategy": model.strategy_name,
                        "run_id": self.config.run_id,
                        "decomposition": result.decomposition.to_dict(),
                    }
                    self._append_jsonl(self.traces_path, trace_entry)
        return results

    def _evaluate_task(self, task: TaskSpec, model: ModelStrategy) -> RealTaskResult:
        working_dir = self.tasks_dir / f"{_sanitize(task.task_id)}__{_sanitize(model.label)}"
        working_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(task.metadata)
        payload["id"] = task.task_id
        payload["title"] = task.title
        payload["problem_statement"] = task.statement
        payload["tests"] = task.tests
        start = time.perf_counter()
        try:
            strategy_result = run_strategy_on_task(
                model.strategy_name,
                payload,
                retry_config=self.config.retry_config,
            )
            elapsed = time.perf_counter() - start
        except Exception as exc:  # pragma: no cover - defensive guardrail
            execution = ExecutionSummary(
                status=FinalStatus.EXECUTION_ERROR,
                build_seconds=0.0,
                test_seconds=0.0,
                build_log=[],
                test_cases=[],
                error=str(exc),
            )
            return RealTaskResult(
                task_id=task.task_id,
                task_title=task.title,
                task_category=task.category,
                dataset_id=task.dataset_id,
                source_path=task.source_path,
                run_id=self.config.run_id,
                model_name=model.model,
                strategy_name=model.strategy_name,
                final_status=execution.status,
                execution=execution,
                decomposition=None,
                strategy_metrics={},
                tokens_used=None,
                elapsed_seconds=time.perf_counter() - start,
            )
        solution_code = strategy_result.solution_code or ""
        code_path = working_dir / "solution.py"
        code_path.write_text(solution_code, encoding="utf-8")
        if solution_code.strip():
            execution = self.config.backend.run(task, solution_code)
        else:
            execution = ExecutionSummary(
                status=FinalStatus.INVALID_OUTPUT,
                build_seconds=0.0,
                test_seconds=0.0,
                build_log=[],
                test_cases=[],
                error="Strategy returned empty solution",
            )
        decomposition = summarize_strategy_result(strategy_result)
        metrics = dict(strategy_result.metrics or {})
        tokens_used = metrics.get("tokens_used")
        if tokens_used is not None:
            try:
                tokens_used = float(tokens_used)
            except (TypeError, ValueError):
                tokens_used = None
        result = RealTaskResult(
            task_id=task.task_id,
            task_title=task.title,
            task_category=task.category,
            dataset_id=task.dataset_id,
            source_path=task.source_path,
            run_id=self.config.run_id,
            model_name=model.model,
            strategy_name=model.strategy_name,
            final_status=execution.status,
            execution=execution,
            decomposition=decomposition,
            strategy_metrics=metrics,
            tokens_used=tokens_used,
            elapsed_seconds=elapsed,
        )
        return result

    def _append_jsonl(self, path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as fp:
            json.dump(payload, fp)
            fp.write("\n")
