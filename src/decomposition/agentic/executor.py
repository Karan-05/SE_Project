"""Execute generated solutions and summarise failures."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.decomposition.interfaces import DecompositionContext
from src.decomposition.self_verify import FailureSummary, summarize_failures
from src.decomposition.strategies._utils import run_tests


@dataclass
class ExecutionResult:
    """Result bundle for a single solve/repair attempt."""

    code: str
    tests: List[Dict[str, str | float]]
    pass_rate: float
    status: str
    duration: float
    summary: Optional[FailureSummary]
    compile_failed: bool
    edited_files: List[str] = field(default_factory=list)
    inspected_files: List[str] = field(default_factory=list)
    proposed_files: List[str] = field(default_factory=list)
    logs: Dict[str, str] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    edit_metadata: Dict[str, object] = field(default_factory=dict)


def execute_attempt(
    code: str,
    ctx: DecompositionContext,
    *,
    timeout_seconds: Optional[float] = None,
) -> ExecutionResult:
    """Run unit tests for the provided code blob and collect metadata."""

    start = time.perf_counter()
    tests_run = run_tests(code, ctx, timeout_seconds=timeout_seconds)
    elapsed = time.perf_counter() - start
    total = len(tests_run)
    if total:
        passes = sum(1 for record in tests_run if record.get("status") == "pass")
        pass_rate = passes / total
    else:
        pass_rate = 0.0
    first_status = tests_run[0].get("status") if tests_run else ""
    compile_failed = first_status in {"compile_error", "missing_entry_point"}
    if compile_failed:
        status = "compile_error"
    elif pass_rate == 1.0:
        status = "passed"
    elif total == 0:
        status = "no_tests"
    else:
        status = "failed_tests"
    summary = summarize_failures(tests_run) if pass_rate < 1.0 else None
    return ExecutionResult(
        code=code,
        tests=tests_run,
        pass_rate=pass_rate,
        status=status,
        duration=elapsed,
        summary=summary,
        compile_failed=compile_failed,
    )


__all__ = ["ExecutionResult", "execute_attempt"]
