"""Orchestrate the Topcoder self-verifying experiment."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import fnmatch
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.config import PathConfig, PROJECT_ROOT
from src.decomposition.registry import STRATEGIES
from src.decomposition.self_verify import RetryConfig
from src.providers import llm

from .dataset_scanner import TopcoderDatasetDescriptor, discover_topcoder_datasets, load_tasks_from_dataset
from . import memory as memory_store
from .reporting import generate_reports
from .test_manager import TestManager, TestPolicy
from .sampling import select_sample
from .task_router import TaskType, route_task
from .solvers import (
    AlgoCodingSolver,
    DataETLSolver,
    DesignDocSolver,
    RepoPatchSolver,
    SolverContext,
)
from .solvers.base import sanitize_task_id
from .verifiers import RepoVerifier, RubricVerifier

logger = logging.getLogger(__name__)


@dataclass
class ExperimentConfig:
    run_id: Optional[str] = None
    max_tasks: Optional[int] = None
    resume: bool = False
    rate_limit: float = 0.0
    parallelism: int = 1
    dataset_roots: Optional[Sequence[Path]] = None
    dataset_limit: Optional[int] = None
    strategy_order: Optional[List[str]] = None
    require_tests: bool = False
    use_samples_as_tests: bool = True
    synthesize_tests: bool = True
    max_synthesized_tests_per_task: int = 8
    max_tasks_needing_synthesis: int = 200
    allow_no_llm: bool = False
    presentation: bool = False
    sample_size: Optional[int] = None
    sample_strategy: str = "random"
    sample_seed: int = 42
    max_llm_calls: Optional[int] = None
    max_total_tokens: Optional[int] = None
    budget_usd: Optional[float] = None
    use_cache: bool = True
    task_timeout_seconds: float = 300.0
    attempt_timeout_seconds: float = 120.0
    llm_timeout_seconds: float = 60.0
    test_timeout_seconds: float = 30.0
    include_datasets: Optional[List[str]] = None
    exclude_datasets: Optional[List[str]] = None
    force_task_type: Optional[str] = None
    default_non_coding_mode: str = "design_doc"


def _default_run_id() -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"topcoder_{timestamp}"


class RateLimiter:
    def __init__(self, delay: float):
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._next_time = 0.0

    def wait(self) -> None:
        if self.delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait_time = self._next_time - now
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.monotonic()
            self._next_time = max(now, self._next_time) + self.delay


class CheckpointManager:
    def __init__(self, path: Path, resume: bool):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if resume and path.exists() else "w"
        self._fp = path.open(mode, encoding="utf-8")
        self._lock = threading.Lock()

    def append(self, record: Dict[str, object]) -> None:
        line = json.dumps(record, default=str)
        with self._lock:
            self._fp.write(line + "\n")
            self._fp.flush()

    def close(self) -> None:
        try:
            self._fp.close()
        except Exception:
            pass


def _load_checkpoint(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


class _TopcoderExperiment:
    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.path_cfg = PathConfig()
        env_run_id = os.getenv("DECOMP_RUN_ID")
        self.run_id = config.run_id or env_run_id or _default_run_id()
        self.run_dir = self.path_cfg.reports_root / "experiments" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = self.path_cfg.artifacts_dir / "self_verifying" / self.run_id
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.deliverables_dir = self.run_dir / "deliverables"
        self.patches_dir = self.run_dir / "patches"
        self.rubric_dir = self.run_dir / "rubric"
        self.test_results_dir = self.run_dir / "unit_tests"
        self.repo_logs_dir = self.run_dir / "repo_logs"
        for path in (self.deliverables_dir, self.patches_dir, self.rubric_dir, self.test_results_dir, self.repo_logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.rate_limiter = RateLimiter(config.rate_limit)
        base_retry = RetryConfig.from_env()
        self.retry_config = replace(
            base_retry,
            store_attempt_artifacts=True,
            run_id=self.run_id,
            task_timeout_seconds=config.task_timeout_seconds,
            attempt_timeout_seconds=config.attempt_timeout_seconds,
            test_timeout_seconds=config.test_timeout_seconds,
        )
        self.strategy_order = config.strategy_order or list(STRATEGIES.keys())
        if not self.strategy_order:
            raise ValueError("No strategies configured for experiment execution")
        self.algo_solver = AlgoCodingSolver(tuple(self.strategy_order))
        rubric = RubricVerifier(self.rubric_dir)
        repo_verifier = RepoVerifier(self.repo_logs_dir)
        architecture_solver = DesignDocSolver(rubric)
        repo_solver = RepoPatchSolver(rubric, repo_verifier)
        self.solver_registry = {
            TaskType.ALGO_CODING: self.algo_solver,
            TaskType.ARCHITECTURE_DOC: architecture_solver,
            TaskType.REPO_PATCH: repo_solver,
            TaskType.API_BACKEND: repo_solver,
            TaskType.DATA_ETL: DataETLSolver(rubric),
        }
        self.checkpoint_path = self.run_dir / "checkpoint.jsonl"
        test_policy = TestPolicy(
            require_tests=config.require_tests,
            use_samples_as_tests=config.use_samples_as_tests,
            synthesize_tests=config.synthesize_tests,
            max_synthesized_tests_per_task=config.max_synthesized_tests_per_task,
            max_tasks_needing_synthesis=config.max_tasks_needing_synthesis,
            allow_no_llm=config.allow_no_llm,
        )
        self.test_manager = TestManager(test_policy, self.run_dir)
        self.llm_available = self.test_manager.llm_available
        self.llm_reason = getattr(self.test_manager, "llm_reason", "unknown")
        self._test_lock = threading.Lock()
        self.allow_no_llm = config.allow_no_llm
        self.presentation = config.presentation
        self.llm_provider = llm.CONFIG.provider
        self.sample_size = config.sample_size or (300 if config.presentation else None)
        self.sample_strategy = config.sample_strategy
        self.sample_seed = config.sample_seed
        min_with_tests = 1
        if self.sample_size:
            min_with_tests = max(1, min(5, self.sample_size // 5 or 1))
        self.sample_min_with_tests = min_with_tests
        self.sample_counts: Dict[str, int] = {}
        self.stop_reason = ""
        self.task_timeout_seconds = config.task_timeout_seconds
        self.include_datasets = list(config.include_datasets or [])
        default_excludes = ["analysis_output_*"]
        self.exclude_datasets = list(config.exclude_datasets or default_excludes)
        self.force_task_type = config.force_task_type
        self.default_non_coding_mode = (config.default_non_coding_mode or "design_doc").lower()
        self.raw_task_rows = 0
        self.duplicate_task_stats: Dict[str, object] = {"duplicates_count": 0, "duplicate_task_ids": []}

    def _discover_datasets(self) -> List[TopcoderDatasetDescriptor]:
        search_paths = (
            [Path(path) for path in self.config.dataset_roots] if self.config.dataset_roots else None
        )
        descriptors = discover_topcoder_datasets(
            root=PROJECT_ROOT,
            search_paths=search_paths,
            limit=self.config.dataset_limit,
        )
        descriptors = self._filter_dataset_descriptors(descriptors)
        datasets_path = self.run_dir / "datasets.json"
        datasets_path.write_text(
            json.dumps([descriptor.to_dict() for descriptor in descriptors], indent=2),
            encoding="utf-8",
        )
        logger.info("Discovered %s candidate datasets", len(descriptors))
        return descriptors

    def _filter_dataset_descriptors(self, descriptors: List[TopcoderDatasetDescriptor]) -> List[TopcoderDatasetDescriptor]:
        include_patterns = self.include_datasets
        exclude_patterns = self.exclude_datasets
        filtered: List[TopcoderDatasetDescriptor] = []
        for descriptor in descriptors:
            dataset_id = descriptor.dataset_id or ""
            include_match = True
            if include_patterns:
                include_match = any(fnmatch.fnmatch(dataset_id, pattern) for pattern in include_patterns)
            if not include_match:
                continue
            exclude_match = any(fnmatch.fnmatch(dataset_id, pattern) for pattern in exclude_patterns) if exclude_patterns else False
            if exclude_match and not include_patterns:
                continue
            filtered.append(descriptor)
        dropped = len(descriptors) - len(filtered)
        if dropped:
            logger.info("Filtered %s datasets via include/exclude rules", dropped)
        return filtered

    def _load_tasks(self, descriptors: List[TopcoderDatasetDescriptor]) -> List[Dict[str, object]]:
        tasks: List[Dict[str, object]] = []
        for descriptor in descriptors:
            dataset_tasks = load_tasks_from_dataset(descriptor)
            tasks.extend(dataset_tasks)
        raw_total = len(tasks)
        if self.config.max_tasks is not None:
            tasks = tasks[: self.config.max_tasks]
        tasks = self._deduplicate_tasks(tasks)
        if self.presentation and self.sample_size:
            tasks, counts = select_sample(
                tasks,
                self.sample_size,
                self.sample_strategy,
                self.sample_seed,
                min_with_tests=self.sample_min_with_tests,
            )
            self.sample_counts = counts
        self.raw_task_rows = raw_total
        manifest_entries = []
        for task in tasks:
            metadata = task.get("metadata", {})
            manifest_entries.append(
                {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "dataset_id": metadata.get("dataset_id"),
                    "dataset_path": metadata.get("dataset_path"),
                    "has_tests": bool(metadata.get("tests")),
                }
            )
        manifest = {
            "run_id": self.run_id,
            "generated_at": datetime.utcnow().isoformat(),
            "task_count": len(tasks),
            "raw_task_rows": raw_total,
            "duplicate_task_count": self.duplicate_task_stats.get("duplicates_count", 0),
            "duplicate_task_ids": self.duplicate_task_stats.get("duplicate_task_ids", []),
            "tasks": manifest_entries,
        }
        (self.run_dir / "tasks_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Loaded %s canonical tasks", len(tasks))
        return tasks

    def _deduplicate_tasks(self, tasks: List[Dict[str, object]]) -> List[Dict[str, object]]:
        seen: Dict[str, Dict[str, object]] = {}
        order: List[str] = []
        duplicates: List[str] = []
        for idx, task in enumerate(tasks):
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                task_id = f"task_{idx}"
                task["id"] = task_id
            if task_id not in seen:
                seen[task_id] = task
                order.append(task_id)
            else:
                if task_id not in duplicates and len(duplicates) < 25:
                    duplicates.append(task_id)
        deduped = [seen[task_id] for task_id in order]
        duplicates_count = len(tasks) - len(deduped)
        self.duplicate_task_stats = {"duplicates_count": duplicates_count, "duplicate_task_ids": duplicates}
        if duplicates_count:
            logger.info(
                "Deduplicated %s task rows (%s unique IDs such as %s).",
                duplicates_count,
                len(duplicates),
                ", ".join(duplicates[:3]) or "n/a",
            )
        return deduped

    def _build_task_record(self, task: Dict[str, object], *, status: str, error_type: str, start: datetime, end: datetime, **overrides: object) -> Dict[str, object]:
        metadata = task.get("metadata", {}) or {}
        dataset_id = metadata.get("dataset_id", "unknown")
        dataset_path = metadata.get("dataset_path")
        duration = max((end - start).total_seconds(), 0.0)
        record: Dict[str, object] = {
            "task_id": task.get("id"),
            "title": task.get("title"),
            "dataset_id": dataset_id,
            "dataset_path": dataset_path,
            "status": status,
            "error_type": error_type,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "duration_seconds": duration,
            "tests_provided": bool(metadata.get("tests")),
            "tests_source": metadata.get("tests_source", ""),
            "tests_path": metadata.get("tests_path", ""),
            "used_synthesized_tests": metadata.get("tests_source") in {"synthesized", "self_check"},
            "self_check_only": bool(metadata.get("self_check_only")),
            "memory_hint_count": len(metadata.get("memory_hints") or []),
            "memory_hints_retrieved": metadata.get("memory_hints_retrieved", 0),
            "artifact_path": str(self.artifact_dir),
            "pass_rate": overrides.get("pass_rate", 0.0),
            "attempt_count": overrides.get("attempt_count", 0.0),
            "strategy_used": overrides.get("strategy_used", ""),
            "fallback_path": overrides.get("fallback_path", ""),
            "stagnation_events": overrides.get("stagnation_events", 0),
            "failure_signature": overrides.get("failure_signature", ""),
            "failing_tests": overrides.get("failing_tests", ""),
            "last_error": overrides.get("last_error", ""),
            "pass_at_final": overrides.get("pass_at_final", False),
            "timed_out": overrides.get("timed_out", False),
            "timeout_reason": overrides.get("timeout_reason", ""),
            "llm_calls_used": overrides.get("llm_calls_used", 0.0),
            "attempt_logs": overrides.get("attempt_logs", ""),
        }
        if "self_check_pass_rate" in overrides:
            record["self_check_pass_rate"] = overrides["self_check_pass_rate"]
        else:
            record["self_check_pass_rate"] = metadata.get("self_check_pass_rate", 0.0)
        record["self_check_passed"] = overrides.get("self_check_passed", metadata.get("self_check_passed", False))
        return record

    def _task_text(self, task: Dict[str, object]) -> str:
        title = str(task.get("title") or "")
        statement = str(task.get("problem_statement") or task.get("statement") or "")
        return f"{title}\n{statement}".strip()

    def _inject_memory_hints(self, task: Dict[str, object]) -> int:
        metadata = task.setdefault("metadata", {})
        task_text = self._task_text(task)
        retrieved = memory_store.retrieve(task_text, k=3)
        if not retrieved:
            metadata["memory_hints_retrieved"] = 0
            return 0
        hints = metadata.setdefault("memory_hints", [])
        added = 0
        for item in retrieved:
            hint = str(item.get("reflection") or "").strip()
            if hint and hint not in hints:
                hints.append(hint)
                added += 1
        metadata["memory_hints_retrieved"] = added
        metadata["memory_hint_count"] = len(hints)
        return added

    def _remember_deliverable_failure(self, task: Dict[str, object], result: SolverResult, resolved_type: Optional[TaskType]) -> None:
        if result.deliverable_success:
            return
        reflection_reason = ""
        if isinstance(result.metrics, dict):
            reasons = result.metrics.get("rubric_reasons") or []
            missing = result.metrics.get("rubric_missing") or []
            if reasons:
                reflection_reason = "; ".join(str(reason) for reason in reasons if reason)
            if missing:
                reflection_reason += f" | Missing: {', '.join(str(item) for item in missing if item)}"
        if not reflection_reason:
            reflection_reason = f"Verifier {result.verifier_type} score {result.verifier_score:.1f}"
        reflection = (
            f"Why it failed: {reflection_reason}.\n"
            "Next steps: address each missing rubric/finding, add explicit risks/test plans, and tighten acceptance criteria."
        )
        failure_sig = result.failure_signature
        if not failure_sig:
            payload = f"{resolved_type}:{result.verifier_type}:{reflection_reason}".encode("utf-8", "ignore")
            failure_sig = hashlib.sha256(payload).hexdigest()
        metadata = {
            "task_text": self._task_text(task),
            "task_type": resolved_type.value if resolved_type else "",
            "solver": result.verifier_type,
            "run_id": self.run_id,
        }
        memory_store.store(str(task.get("id")), reflection, failure_sig, metadata)

    def _build_solver_context(self, task: Dict[str, object], decision):
        retry_cfg = replace(self.retry_config, llm_available=self.llm_available)
        return SolverContext(
            task=task,
            decision=decision,
            config=self.config,
            retry_config=retry_cfg,
            test_manager=self.test_manager,
            run_dir=self.run_dir,
            artifact_dir=self.artifact_dir,
            deliverables_dir=self.deliverables_dir,
            patches_dir=self.patches_dir,
            rubric_dir=self.rubric_dir,
            test_results_dir=self.test_results_dir,
            repo_logs_dir=self.repo_logs_dir,
            repo_search_root=PROJECT_ROOT,
            llm_available=self.llm_available,
        )

    def _prepare_algo_task(self, task: Dict[str, object]) -> Optional[Dict[str, str]]:
        metadata = task.get("metadata", {}) or {}
        statement_text = str(task.get("problem_statement") or task.get("statement") or "")
        with self._test_lock:
            tests = metadata.get("tests") or []
            skip_info = None
            if not tests or not metadata.get("tests_source") or not metadata.get("tests_path"):
                skip_info = self.test_manager.ensure_tests(task)
        if skip_info:
            if skip_info.get("parse_failure"):
                artifact_path = self._write_parse_failure_artifact(task, statement_text)
                skip_info["artifact_path"] = str(artifact_path)
            return skip_info
        metadata = task.get("metadata", {}) or {}
        tests = metadata.get("tests") or []
        if not tests:
            return {"status": "skipped_missing_tests", "error_type": "missing_tests"}
        return None

    def _write_parse_failure_artifact(self, task: Dict[str, object], statement_text: str) -> Path:
        directory = self.run_dir / "parse_failures"
        directory.mkdir(parents=True, exist_ok=True)
        safe_id = sanitize_task_id(str(task.get("id") or "task"))
        path = directory / f"{safe_id}.md"
        title = str(task.get("title") or "Untitled challenge")
        reason = "Unable to extract executable tests from problem statement."
        lines = [
            f"# Parse failure — {safe_id}",
            "",
            f"- title: {title}",
            f"- dataset_id: {task.get('dataset_id', 'unknown')}",
            f"- reason: {reason}",
            "",
            "## Statement excerpt",
            statement_text[:800] or "(empty statement)",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _resolve_task_type(self, task: Dict[str, object], decision) -> Optional[TaskType]:
        if self.force_task_type:
            return decision.task_type
        if decision.task_type == TaskType.NON_ACTIONABLE:
            if self.default_non_coding_mode in {"design_doc", "architecture_doc"}:
                return TaskType.ARCHITECTURE_DOC
            return None
        if decision.task_type == TaskType.ALGO_CODING and not self._looks_like_coding_task(task):
            # Fall back to a non-algorithmic solver when IO/tests are not credible.
            if self.default_non_coding_mode in {"design_doc", "architecture_doc"}:
                return TaskType.ARCHITECTURE_DOC
            if self.default_non_coding_mode == "skip":
                return None
            return TaskType.REPO_PATCH
        if decision.task_type in {TaskType.REPO_PATCH, TaskType.API_BACKEND, TaskType.ARCHITECTURE_DOC, TaskType.DATA_ETL} and self.default_non_coding_mode == "skip":
            return None
        return decision.task_type

    def _attach_route_metadata(self, record: Dict[str, object], decision, resolved_type: Optional[TaskType], solver_name: str) -> Dict[str, object]:
        if decision:
            record["task_type"] = decision.task_type.value
            record["router_rationale"] = decision.rationale
            record["router_heuristics"] = ",".join(decision.heuristics)
        if resolved_type:
            record["resolved_task_type"] = resolved_type.value
        record["solver_used"] = solver_name or record.get("solver_used", "")
        record["solver_name"] = record["solver_used"]
        record.setdefault("verifier_type", "")
        record.setdefault("verifier_name", "")
        record.setdefault("verifier_score", 0.0)
        record.setdefault("deliverable_path", "")
        record.setdefault("patch_path", "")
        record.setdefault("repo_log_path", "")
        record.setdefault("rubric_path", "")
        record.setdefault("artifact_path", record.get("artifact_path", ""))
        record.setdefault("unit_test_success", False)
        record.setdefault("deliverable_success", False)
        return record

    def _execute_task(self, task: Dict[str, object]) -> Dict[str, object]:
        self.rate_limiter.wait()
        start = datetime.utcnow()
        task.setdefault("metadata", {})
        self._inject_memory_hints(task)
        if not self.llm_available and not self.allow_no_llm:
            end = datetime.utcnow()
            record = self._build_task_record(
                task,
                status="skipped_no_llm_config",
                error_type="missing_dependency",
                start=start,
                end=end,
                last_error=f"LLM unavailable ({self.llm_reason})",
            )
            return self._attach_route_metadata(record, None, None, solver_name="")
        decision = route_task(task, force_task_type=self.force_task_type)
        resolved_type = self._resolve_task_type(task, decision)
        if resolved_type is None:
            status = "skipped_insufficient_context" if decision.task_type == TaskType.NON_ACTIONABLE else "skipped_non_coding_task"
            error = "insufficient_context" if decision.task_type == TaskType.NON_ACTIONABLE else "non_coding"
            if self.default_non_coding_mode == "skip" and decision.task_type not in {TaskType.ALGO_CODING}:
                status = "skipped_non_coding_mode"
                error = "non_coding"
            end = datetime.utcnow()
            record = self._build_task_record(task, status=status, error_type=error, start=start, end=end)
            return self._attach_route_metadata(record, decision, None, solver_name="")
        metadata = task.setdefault("metadata", {})
        if resolved_type != TaskType.ALGO_CODING:
            metadata.setdefault("tests_source", "n/a")
            metadata.setdefault("tests_path", "")
            metadata.setdefault("tests", [])
        solver = self.solver_registry.get(resolved_type)
        if not solver:
            end = datetime.utcnow()
            record = self._build_task_record(
                task,
                status="skipped_no_solver",
                error_type="unsupported",
                start=start,
                end=end,
                last_error=f"No solver registered for {resolved_type}",
            )
            return self._attach_route_metadata(record, decision, resolved_type, solver_name="")
        if resolved_type == TaskType.ALGO_CODING:
            skip_info = self._prepare_algo_task(task)
            if skip_info:
                status = skip_info.get("status", "skipped_missing_tests")
                error = skip_info.get("error_type", "missing_tests")
                if skip_info.get("parse_failure"):
                    status = "skipped_parse_failure"
                    error = "parse_failure"
                end = datetime.utcnow()
                record = self._build_task_record(
                    task,
                    status=status,
                    error_type=error,
                    start=start,
                    end=end,
                )
                if skip_info.get("artifact_path"):
                    record["artifact_path"] = skip_info["artifact_path"]
                return self._attach_route_metadata(record, decision, resolved_type, solver_name=solver.name)
        ctx = self._build_solver_context(task, decision)
        try:
            result = solver.solve(ctx)
            end = datetime.utcnow()
            record = self._build_task_record(
                task,
                status=result.status,
                error_type=result.error_type,
                start=start,
                end=end,
                pass_rate=float(result.metrics.get("pass_rate", 1.0 if result.unit_test_success else 0.0)),
                attempt_count=float(result.metrics.get("attempt_count", 0.0)),
                strategy_used=str(result.metrics.get("strategy_used", "")),
                fallback_path=str(result.metrics.get("fallback_path", "")),
                stagnation_events=float(result.metrics.get("stagnation_events", 0.0)),
                failure_signature=result.failure_signature,
                failing_tests=result.failing_tests,
                pass_at_final=result.unit_test_success,
                attempt_logs=str(result.metrics.get("attempt_logs", "")),
                timed_out=bool(result.metrics.get("timed_out", False)),
                timeout_reason=str(result.metrics.get("timeout_reason", "")),
                llm_calls_used=result.llm_calls_used,
            )
            record.update(result.metrics)
            artifacts = result.artifacts or {}
            record["deliverable_path"] = artifacts.get("deliverable_path", "")
            record["patch_path"] = artifacts.get("patch_path", "")
            record["repo_log_path"] = artifacts.get("repo_log_path", "")
            record["rubric_path"] = artifacts.get("rubric_path", "")
            record["unit_test_report_path"] = artifacts.get("unit_test_report", "")
            record["raw_agent_response_path"] = artifacts.get("raw_agent_response_path", "")
            record["repaired_agent_response_path"] = artifacts.get("repaired_agent_response_path", "")
            record["verifier_type"] = result.verifier_type
            record["verifier_name"] = result.verifier_name
            record["verifier_score"] = result.verifier_score
            record["unit_test_success"] = bool(result.unit_test_success)
            record["deliverable_success"] = bool(result.deliverable_success)
            if resolved_type and resolved_type != TaskType.ALGO_CODING:
                self._remember_deliverable_failure(task, result, resolved_type)
            return self._attach_route_metadata(record, decision, resolved_type, solver_name=solver.name)
        except ImportError as exc:
            end = datetime.utcnow()
            record = self._build_task_record(
                task,
                status="skipped_missing_dependency",
                error_type="missing_dependency",
                start=start,
                end=end,
                last_error=str(exc),
            )
            return self._attach_route_metadata(record, decision, resolved_type, solver_name=solver.name)
        except Exception as exc:  # pragma: no cover - defensive logging path
            end = datetime.utcnow()
            logger.exception("Task %s failed unexpectedly", task.get("id"))
            record = self._build_task_record(
                task,
                status="error",
                error_type="exception",
                start=start,
                end=end,
                last_error=str(exc),
            )
            return self._attach_route_metadata(record, decision, resolved_type, solver_name=solver.name)

    def _run_tasks(self, tasks: List[Dict[str, object]], checkpoint: CheckpointManager) -> None:
        if not tasks:
            return
        total = len(tasks)
        parallelism = max(1, self.config.parallelism)
        if parallelism == 1:
            for idx, task in enumerate(tasks, start=1):
                try:
                    record = self._execute_task(task)
                except RuntimeError as exc:
                    if "LLM budget exceeded" in str(exc):
                        self.stop_reason = "STOPPED_BUDGET"
                        logger.warning("Stopping run due to budget limit.")
                        break
                    raise
                checkpoint.append(record)
                logger.info("Completed %s/%s (%s)", idx, total, record.get("status"))
        else:
            with ThreadPoolExecutor(max_workers=parallelism) as executor:
                futures = {executor.submit(self._execute_task, task): task for task in tasks}
                completed = 0
                for future in as_completed(futures):
                    try:
                        record = future.result()
                    except RuntimeError as exc:
                        if "LLM budget exceeded" in str(exc):
                            self.stop_reason = "STOPPED_BUDGET"
                            logger.warning("Stopping run due to budget limit.")
                            break
                        raise
                    checkpoint.append(record)
                    completed += 1
                    logger.info("Completed %s/%s (%s)", completed, total, record.get("status"))
                if self.stop_reason:
                    return
        if self.stop_reason:
            return

    def run(self) -> Dict[str, object]:
        descriptors = self._discover_datasets()
        tasks = self._load_tasks(descriptors)
        existing_records = _load_checkpoint(self.checkpoint_path) if self.config.resume else []
        completed_ids = {str(rec.get("task_id")) for rec in existing_records}
        tasks_to_run = [task for task in tasks if str(task.get("id")) not in completed_ids]
        checkpoint = CheckpointManager(self.checkpoint_path, resume=self.config.resume)
        try:
            self._run_tasks(tasks_to_run, checkpoint)
        finally:
            checkpoint.close()
        final_records = _load_checkpoint(self.checkpoint_path)
        metadata = {
            "llm_available": self.llm_available,
            "llm_reason": self.llm_reason,
            "stop_reason": self.stop_reason or "",
            "llm_provider": self.llm_provider,
            "mock_provider": self.llm_provider.lower() == "mock",
            "raw_task_rows": self.raw_task_rows,
            "duplicate_task_count": self.duplicate_task_stats.get("duplicates_count", 0),
            "duplicate_task_ids": self.duplicate_task_stats.get("duplicate_task_ids", []),
        }
        if self.presentation:
            metadata.update(
                {
                    "presentation_mode": True,
                    "sample_size": self.sample_counts.get("total", len(tasks)),
                    "sample_strategy": self.sample_strategy,
                    "sample_seed": self.sample_seed,
                }
            )
        report_paths = generate_reports(
            self.run_id,
            self.run_dir,
            final_records,
            artifact_dir=self.artifact_dir,
            llm_usage=llm.get_usage(),
            llm_available=self.llm_available,
            metadata=metadata,
        )
        return {
            "run_id": self.run_id,
            "report_dir": self.run_dir,
            "checkpoint": self.checkpoint_path,
            "reports": report_paths,
            "total_tasks": len(tasks),
            "completed_tasks": len(final_records),
        }

    def _looks_like_coding_task(self, task: Dict[str, object]) -> bool:
        metadata = task.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("tests"):
            return True
        statement = str(task.get("problem_statement") or task.get("statement") or "").lower()
        if not statement:
            return False
        has_examples = bool(task.get("examples")) or "example" in statement or "sample" in statement
        has_constraints = "constraint" in statement or "limit" in statement
        has_io = "input" in statement and "output" in statement
        signature_markers = ["function", "method", "class", "return", "solve(", "implement"]
        has_signature = any(marker in statement for marker in signature_markers)
        return (has_examples or has_constraints) and (has_io or has_signature)


def run_topcoder_experiment(config: ExperimentConfig) -> Dict[str, object]:
    runner = _TopcoderExperiment(config)
    return runner.run()
