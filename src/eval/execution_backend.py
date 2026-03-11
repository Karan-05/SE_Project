"""Execution backend abstraction for running generated solutions."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

from src.decomposition.strategies._utils import run_tests

from .result_schema import ExecutionSummary, FinalStatus
from .task_manifest import TaskSpec


def _classify_tests(tests: List[dict]) -> FinalStatus:
    if not tests:
        return FinalStatus.NO_ASSETS
    statuses = [str(test.get("status", "")).lower() for test in tests]
    if all(status == "pass" for status in statuses):
        return FinalStatus.PASS_ALL_TESTS
    if any(status == "pass" for status in statuses):
        return FinalStatus.BUILD_PASS_TESTS_PARTIAL
    if any(status in {"compile_error", "missing_entry_point"} for status in statuses):
        return FinalStatus.BUILD_FAIL
    if any(status == "timeout" for status in statuses):
        return FinalStatus.TIMEOUT
    return FinalStatus.TEST_FAIL


@dataclass
class BackendConfig:
    """Configuration knobs shared by all execution backends."""

    test_timeout_seconds: float = 30.0


class ExecutionBackend:
    """Base interface for executing generated code on a task."""

    name = "base"

    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()

    def run(self, task: TaskSpec, solution_code: str) -> ExecutionSummary:
        raise NotImplementedError


class PythonCallBackend(ExecutionBackend):
    """Backend that evaluates Python call/IO tests using the shared utility."""

    name = "python_function"

    def run(self, task: TaskSpec, solution_code: str) -> ExecutionSummary:
        ctx = task.to_context()
        start = time.perf_counter()
        tests = run_tests(solution_code, ctx, timeout_seconds=self.config.test_timeout_seconds)
        elapsed = time.perf_counter() - start
        status = _classify_tests(tests)
        return ExecutionSummary(
            status=status,
            build_seconds=0.0,
            test_seconds=elapsed,
            build_log=[],
            test_cases=tests,
            error=None,
        )
