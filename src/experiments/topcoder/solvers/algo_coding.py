"""Solver that leverages the self-verify loop for algorithmic coding tasks."""
from __future__ import annotations

from typing import Dict, Tuple

from src.decomposition.runners.run_on_task import run_strategy_on_task
from src.decomposition.self_verify import failure_signature as build_failure_signature
from src.decomposition.self_verify import summarize_failures

from ..prompts import UNIVERSAL_AGENT_PROMPT
from ..task_router import TaskType
from ..verifiers import persist_test_results
from .base import BaseSolver, SolverContext, SolverResult


class AlgoCodingSolver:
    """Wrap the existing self-verify harness behind the universal solver contract."""

    name = "algo_coding"
    supported_types = (TaskType.ALGO_CODING,)

    def __init__(self, strategy_order: Tuple[str, ...]):
        self.strategy_order = strategy_order

    def solve(self, ctx: SolverContext) -> SolverResult:
        metadata = ctx.task.get("metadata", {}) or {}
        metadata.setdefault("universal_prompt", UNIVERSAL_AGENT_PROMPT)
        tests = metadata.get("tests") or []
        self_check_only = bool(metadata.get("self_check_only"))
        if not tests:
            return SolverResult(
                status="skipped_missing_tests",
                error_type="missing_tests",
                verifier_type="unit_tests",
                verifier_name="unit_tests",
                verifier_score=0.0,
                notes="No executable tests available after preparation.",
            )
        metadata["test_timeout_seconds"] = ctx.config.test_timeout_seconds  # type: ignore[attr-defined]
        retry_cfg = ctx.retry_config
        result = run_strategy_on_task(
            self.strategy_order[0],
            ctx.task,
            retry_config=retry_cfg,
            strategy_order=list(self.strategy_order),
        )
        metrics = result.metrics
        status_label, error_type = self._result_status(result)
        pass_rate = float(metrics.get("pass_rate", 0.0))
        attempts = float(metrics.get("attempt_count", 0.0))
        fallback_path = str(metrics.get("fallback_path", ""))
        strategy_used = str(metrics.get("strategy_used", ""))
        stagnation_events = int(float(metrics.get("stagnation_events", 0.0)))
        timed_out = bool(metrics.get("timed_out"))
        timeout_reason = str(metrics.get("timeout_reason", ""))
        attempt_logs = str(metrics.get("attempt_logs", ""))
        llm_calls_used = float(metrics.get("llm_calls_used", 0.0))
        failure_sig = ""
        failing_tests = ""
        if status_label != "success":
            failure_summary = summarize_failures(result.tests_run)
            failure_sig = build_failure_signature(failure_summary)
            failing_tests = ",".join(failure_summary.failing_tests)
        test_report_path = persist_test_results(ctx.task_id, result.tests_run or [], ctx.test_results_dir)
        artifacts = {
            "unit_test_report": str(test_report_path),
        }
        if fallback_path:
            artifacts["fallback_path"] = fallback_path
        metrics_payload: Dict[str, object] = {
            "pass_rate": pass_rate,
            "attempt_count": attempts,
            "strategy_used": strategy_used,
            "fallback_path": fallback_path,
            "stagnation_events": stagnation_events,
            "timed_out": timed_out,
            "timeout_reason": timeout_reason,
            "attempt_logs": attempt_logs,
        }
        unit_test_success = status_label == "success"
        self_check_passed = False
        if self_check_only:
            self_check_passed = pass_rate == 1.0
            metrics_payload["self_check_only"] = True
            metrics_payload["self_check_pass_rate"] = pass_rate
            metrics_payload["self_check_passed"] = self_check_passed
            metrics_payload["self_check_error_type"] = error_type
            status_label = "self_check_passed" if self_check_passed else "self_check_failed"
            error_type = "self_check" if self_check_passed else error_type
            unit_test_success = False
        metrics_payload.update({k: v for k, v in metrics.items() if k not in metrics_payload})
        return SolverResult(
            status=status_label,
            error_type=error_type,
            verifier_type="unit_tests",
            verifier_name="unit_tests",
            verifier_score=pass_rate * 100.0,
            metrics=metrics_payload,
            artifacts=artifacts,
            tests_run=result.tests_run,
            llm_calls_used=llm_calls_used,
            unit_test_success=unit_test_success,
            deliverable_success=False,
            failure_signature=failure_sig,
            failing_tests=failing_tests,
        )

    def _result_status(self, result) -> Tuple[str, str]:
        metrics = result.metrics
        tests_run = result.tests_run or []
        if str(metrics.get("final_status")).lower() == "passed" or metrics.get("pass_rate") == 1:
            return "success", "success"
        if metrics.get("timed_out") or any(test.get("status") == "timeout" for test in tests_run):
            return "timeout", "timeout"
        if any(test.get("status") in {"compile_error", "missing_entry_point"} for test in tests_run):
            return "failed_exception", "failed_exception"
        return "failed_tests", "failed_tests"
