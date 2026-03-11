"""Self-verifying strategy execution with retries and fallback."""
from __future__ import annotations

import hashlib
import json
import os
import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.config import PathConfig
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult, TaskDecompositionStrategy
from src.decomposition.strategies._utils import build_implementation_contract, run_tests
from src.decomposition.timeline import AttemptTimeline, timeline_scope
from src.providers import llm

_MEMORY_ADAPTER = None
_MEMORY_LOADED = False


def _get_memory_adapter():
    global _MEMORY_ADAPTER, _MEMORY_LOADED
    if not _MEMORY_LOADED:
        try:
            from src.experiments.topcoder import memory as mem  # type: ignore
        except Exception:
            mem = None
        _MEMORY_ADAPTER = mem
        _MEMORY_LOADED = True
    return _MEMORY_ADAPTER


def _set_memory_adapter(adapter) -> None:
    global _MEMORY_ADAPTER, _MEMORY_LOADED
    if adapter is None:
        _MEMORY_ADAPTER = None
        _MEMORY_LOADED = False
    else:
        _MEMORY_ADAPTER = adapter
        _MEMORY_LOADED = True


@dataclass
class FailureSummary:
    failing_tests: List[str]
    brief_trace: List[str]
    assertion_msgs: List[str]
    reproduction_hint: str
    raw: List[Dict[str, str | float]]
    error_types: List[str]


@dataclass
class RetryConfig:
    """Configuration for self-verifying retries."""

    max_retries_per_strategy: int = 3
    max_strategies_to_try: Optional[int] = None
    stagnation_patience: int = 2
    store_attempt_artifacts: bool = False
    strategy_order: Optional[List[str]] = None
    max_total_attempts: int = 10
    run_id: Optional[str] = None
    llm_available: bool = True
    task_timeout_seconds: float = 300.0
    attempt_timeout_seconds: float = 120.0
    test_timeout_seconds: float = 30.0
    llm_timeout_seconds: float = 60.0

    @staticmethod
    def from_env() -> "RetryConfig":
        def _read_int(name: str, default: Optional[int]) -> Optional[int]:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _read_float(name: str, default: Optional[float]) -> Optional[float]:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return RetryConfig(
            max_retries_per_strategy=_read_int("DECOMP_MAX_RETRIES", 3) or 3,
            max_strategies_to_try=_read_int("DECOMP_MAX_STRATEGIES", None),
            stagnation_patience=_read_int("DECOMP_STAGNATION_PATIENCE", 2) or 2,
            store_attempt_artifacts=os.getenv("DECOMP_STORE_ARTIFACTS", "0").lower() in {"1", "true", "yes"},
            max_total_attempts=_read_int("DECOMP_MAX_TOTAL_ATTEMPTS", 10) or 10,
            run_id=os.getenv("DECOMP_RUN_ID") or None,
            task_timeout_seconds=_read_float("DECOMP_TASK_TIMEOUT_SECONDS", 300.0) or 300.0,
            attempt_timeout_seconds=_read_float("DECOMP_ATTEMPT_TIMEOUT_SECONDS", 120.0) or 120.0,
            test_timeout_seconds=_read_float("DECOMP_TEST_TIMEOUT_SECONDS", 30.0) or 30.0,
            llm_timeout_seconds=_read_int("DECOMP_LLM_TIMEOUT_SECONDS", 60) or 60,
        )


def ensure_testing_subtasks(plan: DecompositionPlan, ctx: Optional[DecompositionContext] = None) -> DecompositionPlan:
    """Append verification subtasks if the plan omitted them."""

    required = [
        "Generate minimal unit tests for critical behaviors",
        "Add adversarial/edge-case tests",
        "Run tests and interpret failures",
        "Repair implementation and re-run tests",
    ]
    for step in required:
        if step not in plan.subtasks:
            plan.subtasks.append(step)
    if not plan.tests:
        plan.tests.extend(["critical unit tests", "edge-case probes"])
    if ctx and isinstance(ctx.metadata, dict):
        repo_files = ctx.metadata.get("repo_target_files")
        if repo_files and not plan.target_files:
            plan.target_files = list(repo_files)
        candidates = ctx.metadata.get("repo_candidate_files") or []
        if candidates and not plan.candidate_files:
            plan.candidate_files = list(candidates)
        if plan.candidate_files and not plan.subtask_file_map and plan.subtasks:
            mapping: Dict[str, List[str]] = {}
            for idx, subtask in enumerate(plan.subtasks):
                if idx < len(plan.candidate_files):
                    mapping[subtask] = [plan.candidate_files[idx]]
            plan.subtask_file_map = mapping
            plan.repair_target_files = mapping
    return plan


def summarize_failures(tests_run: List[Dict[str, str | float]], max_items: int = 5) -> FailureSummary:
    failures = [tr for tr in tests_run if tr.get("status") != "pass"]
    failing_tests = [tr.get("name", f"test_{idx}") for idx, tr in enumerate(failures[:max_items])]
    brief_trace = [str(tr.get("error", ""))[:160] for tr in failures[:max_items]]
    assertion_msgs = [
        f"{tr.get('name', f'test_{idx}')} expected {tr.get('expected')} but saw {tr.get('output')}"
        for idx, tr in enumerate(failures[:max_items])
    ]
    error_types = [
        f"{tr.get('status')}::{(tr.get('error') or '')[:80]}"
        for tr in failures[:max_items]
    ]
    reproduction_hint = ""
    if failures:
        reproduction_hint = f"inputs={failures[0].get('input', '')} kwargs={failures[0].get('kwargs', '')}"
    return FailureSummary(
        failing_tests=failing_tests,
        brief_trace=brief_trace,
        assertion_msgs=assertion_msgs,
        reproduction_hint=reproduction_hint,
        raw=failures,
        error_types=error_types,
    )


def failure_signature(summary: FailureSummary) -> str:
    payload = {
        "tests": summary.failing_tests,
        "trace": summary.brief_trace,
        "errors": summary.error_types,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_repair_prompt(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    summary: FailureSummary,
    current_code: str,
    contract: str,
) -> str:
    plan_desc = "\n".join(plan.subtasks[:6])
    pitfall_info = plan.diagnostics.get("pitfalls", "")
    return (
        f"You are repairing code produced by strategy '{strategy_name}'.\n"
        f"Problem statement: {ctx.problem_statement[:400]}\n"
        f"Implementation contract: {contract}\n"
        f"Plan highlights:\n{plan_desc}\nPitfalls:{pitfall_info}\n"
        f"Current code:\n{current_code[:800]}\n"
        f"Failing tests: {summary.failing_tests}\n"
        f"Assertion messages: {summary.assertion_msgs}\n"
        f"Trace excerpt: {summary.brief_trace}\n"
        f"Reproduction hint: {summary.reproduction_hint}\n"
        "Produce a minimal patch to fix only the failing behavior. "
        "Keep public APIs identical and do not refactor unrelated sections. "
        "Return the full updated implementation without commentary."
    )


def _extract_code_block(payload: str) -> str:
    fence = "```"
    if fence not in payload:
        return payload
    parts = payload.split(fence)
    if len(parts) < 3:
        return payload
    # When present, second element may include language tag.
    code = parts[2] if parts[1].strip() else parts[1]
    return code.strip()


def request_repair_patch(
    strategy_name: str,
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    summary: FailureSummary,
    current_code: str,
) -> Tuple[str, Dict[str, str]]:
    contract = build_implementation_contract(ctx)
    prompt = build_repair_prompt(strategy_name, ctx, plan, summary, current_code, contract)
    response = llm.call(
        prompt,
        model="repair-loop",
        max_tokens=512,
        temperature=0.2,
        caller=f"{strategy_name}:repair",
    )
    new_code = _extract_code_block(response.content.strip()) or current_code
    metadata = {
        "prompt_excerpt": prompt[-200:],
        "llm_tokens": str(response.tokens),
    }
    return new_code, metadata


def _artifact_dir(run_id: Optional[str]) -> Path:
    path = PathConfig().artifacts_dir / "self_verifying"
    if run_id:
        path = path / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.-]")


def _sanitize_task_id(task_id: str) -> str:
    safe = _SAFE_ID_PATTERN.sub("_", task_id)
    return safe[:80] or "task"


def store_attempt_trace(
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    strategy_name: str,
    attempt_idx: int,
    tests_run: List[Dict[str, str | float]],
    pass_rate: float,
    summary: Optional[FailureSummary],
    metadata: Dict[str, str],
    run_id: Optional[str],
    timeline: Optional[Dict[str, object]] = None,
    llm_calls: int = 0,
    solution_code: Optional[str] = None,
) -> None:
    payload = {
        "task_id": ctx.task_id,
        "strategy": strategy_name,
        "attempt": attempt_idx,
        "pass_rate": pass_rate,
        "plan_subtasks": plan.subtasks[:6],
        "plan_tests": plan.tests[:6],
        "plan_diagnostics": plan.diagnostics,
        "patch_summary": metadata,
    }
    if summary:
        payload.update(
            {
                "failing_tests": summary.failing_tests,
                "trace": summary.brief_trace,
                "feedback": summary.assertion_msgs,
                "reproduction": summary.reproduction_hint,
            }
        )
    payload["tests_run"] = tests_run
    payload["llm_calls"] = llm_calls
    if timeline:
        payload["timeline"] = timeline
    if solution_code:
        preview = "\n".join(solution_code.splitlines()[:80])
        payload["solution_preview"] = preview
    safe_id = _sanitize_task_id(ctx.task_id)
    target = _artifact_dir(run_id) / f"{safe_id}_{attempt_idx:02d}_{strategy_name}.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_memory_hint(ctx: DecompositionContext, hint: str) -> None:
    if not hint:
        return
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    hints = metadata.setdefault("memory_hints", [])
    if hint in hints:
        return
    hints.append(hint)
    ctx.problem_statement = f"{ctx.problem_statement}\n\nMemory Hint:\n- {hint}".strip()
    metadata["memory_hint_count"] = len(hints)


def _record_memory_reflection(
    ctx: DecompositionContext,
    strategy_name: str,
    attempt_idx: int,
    summary: Optional[FailureSummary],
    plan: DecompositionPlan,
) -> None:
    if not summary:
        return
    memory = _get_memory_adapter()
    if memory is None:
        return
    failing = ", ".join(summary.failing_tests) or "unknown tests"
    trace = "; ".join(summary.brief_trace[:2]) or "; ".join(summary.assertion_msgs[:2])
    plan_hint = ", ".join(plan.subtasks[:2]) or plan.strategy_name
    reproduction = summary.reproduction_hint or "Reproduce the failing input described in logs."
    reflection = (
        f"Why it failed: Attempt {attempt_idx} using {strategy_name} could not satisfy tests [{failing}] because {trace or 'tests still failed'}.\n"
        f"Next steps: refine plan focus on {plan_hint} and specifically handle reproduction hint {reproduction}."
    )
    metadata = {
        "task_text": ctx.problem_statement[:800],
        "task_type": ctx.metadata.get("task_type") or ctx.metadata.get("resolved_task_type") or "",
        "strategy": strategy_name,
        "attempt": attempt_idx,
    }
    memory.store(ctx.task_id, reflection, failure_signature(summary), metadata)
    _append_memory_hint(ctx, reflection)


def _pass_rate(tests_run: List[Dict[str, str | float]]) -> float:
    total = len(tests_run)
    if total == 0:
        return 0.0
    passed = sum(1 for tr in tests_run if tr.get("status") == "pass")
    return passed / total


def execute_with_self_verification(
    ctx: DecompositionContext,
    strategy_candidates: Sequence[str],
    config: Optional[RetryConfig] = None,
    registry: Optional[Dict[str, TaskDecompositionStrategy]] = None,
) -> StrategyResult:
    if not strategy_candidates and not (config and config.strategy_order):
        raise ValueError("strategy_candidates must not be empty")
    cfg = config or RetryConfig()
    order = list(cfg.strategy_order or strategy_candidates)
    if not order:
        raise ValueError("No strategies configured for execution")
    if registry is None:
        from src.decomposition.registry import STRATEGIES as _REGISTRY

        registry_ref = _REGISTRY
    else:
        registry_ref = registry
    max_strategies = cfg.max_strategies_to_try or len(order)
    fallback_path: List[str] = []
    pass_rate_history: List[float] = []
    attempt_logs: List[Dict[str, object]] = []
    total_attempts = 0
    run_id = cfg.run_id or f"{ctx.task_id}_{int(time.time())}"
    final_result: Optional[StrategyResult] = None
    last_summary: Optional[FailureSummary] = None
    stagnation_events = 0
    task_start = time.perf_counter()
    timed_out = False
    timeout_reason = ""
    task_llm_start = llm.total_calls()

    for strategy_name in order[:max_strategies]:
        strategy = registry_ref[strategy_name]
        fallback_path.append(strategy_name)
        attempt_idx = total_attempts + 1
        timeline = AttemptTimeline(attempt=attempt_idx, strategy=strategy_name, phase="initial")
        timeline.start("decompose")
        plan = ensure_testing_subtasks(strategy.decompose(ctx), ctx)
        timeline.end("decompose")
        attempt_timer = time.perf_counter()
        attempt_llm_start = llm.total_calls()
        with timeline_scope(timeline):
            timeline.start("solve")
            result = strategy.solve(ctx, plan)
            timeline.end("solve")
        final_result = result
        total_attempts += 1
        pass_rate = _pass_rate(result.tests_run)
        pass_rate_history.append(pass_rate)
        attempt_llm_calls = max(0, llm.total_calls() - attempt_llm_start)
        timeline.metadata["llm_calls"] = str(attempt_llm_calls)
        attempt_elapsed = time.perf_counter() - attempt_timer
        attempt_logs.append(
            {
                "strategy": strategy_name,
                "attempt": total_attempts,
                "pass_rate": pass_rate,
                "phase": "initial",
                "llm_calls": attempt_llm_calls,
                "timeline": timeline.to_dict(),
            }
        )
        attempt_summary = summarize_failures(result.tests_run) if pass_rate < 1.0 else None
        if attempt_summary:
            _record_memory_reflection(ctx, strategy_name, total_attempts, attempt_summary, plan)
        if cfg.store_attempt_artifacts:
            store_metadata = {"phase": "initial"}
            store_attempt_trace(
                ctx,
                plan,
                strategy_name,
                total_attempts,
                result.tests_run,
                pass_rate,
                attempt_summary,
                store_metadata,
                run_id,
                timeline=timeline.to_dict(),
                llm_calls=attempt_llm_calls,
                solution_code=result.solution_code,
            )
        if pass_rate == 1.0:
            last_summary = None
            break
        last_summary = attempt_summary
        signature = failure_signature(last_summary)
        stagnation = 1
        strategy_attempts = 1
        if attempt_elapsed >= cfg.attempt_timeout_seconds:
            timed_out = True
            timeout_reason = "attempt"
            break
        if time.perf_counter() - task_start >= cfg.task_timeout_seconds:
            timed_out = True
            timeout_reason = "task"
            break

        while (
            strategy_attempts < cfg.max_retries_per_strategy
            and total_attempts < cfg.max_total_attempts
            and cfg.llm_available
            and not timed_out
        ):
            strategy_attempts += 1
            total_attempts += 1
            attempt_idx = total_attempts
            attempt_llm_start = llm.total_calls()
            timeline = AttemptTimeline(attempt=attempt_idx, strategy=strategy_name, phase="repair")
            attempt_timer = time.perf_counter()
            with timeline_scope(timeline):
                timeline.start("repair")
                new_code, repair_meta = request_repair_patch(strategy_name, ctx, plan, last_summary, result.solution_code)
                timeline.end("repair")
                timeline.metadata.update(repair_meta)
                tests_run = run_tests(new_code, ctx, timeout_seconds=cfg.test_timeout_seconds)
            result.solution_code = new_code
            result.tests_run = tests_run
            pass_rate = _pass_rate(tests_run)
            pass_rate_history.append(pass_rate)
            attempt_llm_calls = max(0, llm.total_calls() - attempt_llm_start)
            timeline.metadata["llm_calls"] = str(attempt_llm_calls)
            attempt_logs.append(
                {
                    "strategy": strategy_name,
                    "attempt": total_attempts,
                    "pass_rate": pass_rate,
                    "phase": "repair",
                    "llm_calls": attempt_llm_calls,
                    "timeline": timeline.to_dict(),
                }
            )
            result.metrics["pass_rate"] = pass_rate
            result.metrics["num_tests"] = len(tests_run)
            attempt_summary = summarize_failures(tests_run) if pass_rate < 1.0 else None
            if attempt_summary:
                _record_memory_reflection(ctx, strategy_name, total_attempts, attempt_summary, plan)
            if cfg.store_attempt_artifacts:
                store_metadata = {"phase": "repair"}
                store_metadata.update(repair_meta)
                store_attempt_trace(
                    ctx,
                    plan,
                    strategy_name,
                    total_attempts,
                    tests_run,
                    pass_rate,
                    attempt_summary,
                    store_metadata,
                    run_id,
                    timeline=timeline.to_dict(),
                    llm_calls=attempt_llm_calls,
                    solution_code=new_code,
                )
            if pass_rate == 1.0 or not cfg.llm_available:
                last_summary = None
                break
            last_summary = attempt_summary
            if not last_summary:
                break
            new_signature = failure_signature(last_summary)
            stagnation = stagnation + 1 if new_signature == signature else 1
            signature = new_signature
            if stagnation >= cfg.stagnation_patience:
                stagnation_events += 1
                break
            attempt_elapsed = time.perf_counter() - attempt_timer
            if attempt_elapsed >= cfg.attempt_timeout_seconds:
                timed_out = True
                timeout_reason = "attempt"
                break
            if time.perf_counter() - task_start >= cfg.task_timeout_seconds:
                timed_out = True
                timeout_reason = "task"
                break
        if final_result and _pass_rate(final_result.tests_run) == 1.0:
            break
        if total_attempts >= cfg.max_total_attempts:
            break
        if timed_out:
            break
    if time.perf_counter() - task_start >= cfg.task_timeout_seconds and not timed_out:
        timed_out = True
        timeout_reason = "task"

    if final_result is None:
        raise RuntimeError("Strategy execution produced no results")

    final_pass_rate = _pass_rate(final_result.tests_run)
    final_result.metrics["pass_rate"] = final_pass_rate
    final_result.metrics["num_tests"] = len(final_result.tests_run)
    final_result.metrics["attempt_count"] = float(total_attempts)
    final_result.metrics["pass_rate_history"] = ",".join(f"{value:.3f}" for value in pass_rate_history)
    final_result.metrics["strategy_used"] = fallback_path[-1] if fallback_path else ""
    final_result.metrics["fallback_path"] = "->".join(fallback_path)
    if "final_status" not in final_result.metrics:
        final_result.metrics["final_status"] = "passed" if final_pass_rate == 1.0 else "failed"
    else:
        final_result.metrics["self_verify_final_status"] = "passed" if final_pass_rate == 1.0 else "failed"
    if last_summary:
        final_result.metrics["failing_tests"] = ",".join(last_summary.failing_tests)
        final_result.metrics["last_failure_feedback"] = "; ".join(last_summary.assertion_msgs or last_summary.brief_trace)
    final_result.metrics["attempt_logs"] = json.dumps(attempt_logs)
    final_result.metrics["stagnation_events"] = float(stagnation_events)
    final_result.metrics["timed_out"] = timed_out
    final_result.metrics["timeout_reason"] = timeout_reason
    final_result.metrics["llm_calls_used"] = float(max(0, llm.total_calls() - task_llm_start))
    return final_result


__all__ = [
    "FailureSummary",
    "RetryConfig",
    "ensure_testing_subtasks",
    "summarize_failures",
    "failure_signature",
    "build_repair_prompt",
    "request_repair_patch",
    "store_attempt_trace",
    "execute_with_self_verification",
]
