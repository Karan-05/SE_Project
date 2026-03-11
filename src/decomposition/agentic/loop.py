"""Iterative solve-test-repair controller."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import PathConfig
from src.decomposition.agentic.executor import ExecutionResult, execute_attempt
from src.decomposition.agentic.semantic import SemanticVariantConfig, get_semantic_config
from src.decomposition.agentic.solver import generate_initial_code, generate_repair_code
from src.decomposition.real_repo.contracts import evaluate_contract_coverage, render_unsatisfied_details
from src.decomposition.agentic.traces import write_round_traces
from src.decomposition.interfaces import DecompositionContext, DecompositionPlan, StrategyResult
from src.decomposition.strategies._utils import BudgetTracker

TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class AgenticExecutionConfig:
    """Config for the per-strategy agentic loop."""

    max_repair_rounds: int = 2
    trace_dir: Path = field(default_factory=lambda: PathConfig().reports_root / "decomposition" / "traces")
    store_traces: bool = True
    test_timeout_seconds: Optional[float] = None

    @staticmethod
    def from_env() -> "AgenticExecutionConfig":
        def _int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _float(name: str, default: Optional[float]) -> Optional[float]:
            raw = os.getenv(name)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        trace_dir_env = os.getenv("DECOMP_TRACE_DIR")
        trace_dir = Path(trace_dir_env) if trace_dir_env else PathConfig().reports_root / "decomposition" / "traces"
        store_traces = str(os.getenv("DECOMP_STORE_TRACES", "1")).strip().lower() in TRUTHY
        timeout = _float("DECOMP_AGENT_TEST_TIMEOUT", None)
        return AgenticExecutionConfig(
            max_repair_rounds=max(0, _int("DECOMP_MAX_REPAIR_ROUNDS", 2)),
            trace_dir=trace_dir,
            store_traces=store_traces,
            test_timeout_seconds=timeout,
        )


@dataclass
class RepairPolicy:
    """How a strategy prefers to repair failing implementations."""

    localized: bool = True
    allow_monolithic_fallback: bool = True
    description: str = "subtasks_first"


@dataclass
class RoundTrace:
    """Structured per-round trace for reporting."""

    index: int
    phase: str
    subtask: str
    localized: bool
    pass_rate: float
    status: str
    duration: float
    failing_tests: List[str] = field(default_factory=list)
    error_types: List[str] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)
    inspected_files: List[str] = field(default_factory=list)
    proposed_files: List[str] = field(default_factory=list)
    edit_metadata: Dict[str, object] = field(default_factory=dict)
    file_count: int = 0
    multi_file_attempt: bool = False

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "round": self.index,
            "phase": self.phase,
            "subtask": self.subtask,
            "localized": self.localized,
            "pass_rate": self.pass_rate,
            "status": self.status,
            "duration": self.duration,
            "failing_tests": self.failing_tests,
            "error_types": self.error_types,
            "file_count": self.file_count,
            "multi_file_attempt": self.multi_file_attempt,
        }
        if self.files_touched:
            payload["files_touched"] = self.files_touched
        if self.inspected_files:
            payload["inspected_files"] = self.inspected_files
        if self.proposed_files:
            payload["proposed_files"] = self.proposed_files
        if self.edit_metadata:
            payload["edit_metadata"] = self.edit_metadata
        return payload


def _default_policy(strategy_name: str, plan: DecompositionPlan) -> RepairPolicy:
    if strategy_name == "direct_baseline" or not plan.subtasks:
        return RepairPolicy(localized=False, allow_monolithic_fallback=True, description="monolithic")
    return RepairPolicy(localized=True, allow_monolithic_fallback=True, description="subtasks_first")


def _next_focus(
    queue: List[str],
    policy: RepairPolicy,
    round_index: int,
) -> Tuple[str, bool]:
    if not policy.localized:
        return "global", False
    if queue:
        return queue.pop(0), True
    if policy.allow_monolithic_fallback:
        return "global", False
    # Localised repairs exhausted but fallback disabled; keep last known focus.
    last = queue[-1] if queue else "global"
    return last, False


def _round_entry(index: int, phase: str, subtask: str, localized: bool, result: ExecutionResult) -> RoundTrace:
    summary = result.summary
    failing = summary.failing_tests if summary else []
    errors = summary.error_types if summary else []
    file_count = len(set(result.edited_files or []))
    return RoundTrace(
        index=index,
        phase=phase,
        subtask=subtask,
        localized=localized,
        pass_rate=result.pass_rate,
        status=result.status,
        duration=result.duration,
        failing_tests=failing,
        error_types=errors,
        files_touched=result.edited_files,
        inspected_files=result.inspected_files,
        proposed_files=result.proposed_files,
        edit_metadata=result.edit_metadata,
        file_count=file_count,
        multi_file_attempt=file_count > 1,
    )


def execute_plan_with_repair(
    ctx: DecompositionContext,
    plan: DecompositionPlan,
    *,
    strategy_name: str,
    policy: Optional[RepairPolicy] = None,
    config: Optional[AgenticExecutionConfig] = None,
    semantic_config: Optional[SemanticVariantConfig] = None,
    extra_metrics: Optional[Dict[str, float | str]] = None,
) -> StrategyResult:
    """Run the iterative loop for a plan and return the final result."""

    cfg = config or AgenticExecutionConfig.from_env()
    policy = policy or _default_policy(strategy_name, plan)
    tracker = BudgetTracker(f"{strategy_name}:agentic_loop")
    semantic_cfg = semantic_config or get_semantic_config(strategy_name)
    round_traces: List[RoundTrace] = []
    localized_attempts = 0
    monolithic_attempts = 0
    subtasks_touched: List[str] = []
    total_tests = 0
    edited_files_acc: set[str] = set()
    inspected_files_acc: set[str] = set()
    proposed_files_acc: set[str] = set()
    attempt_file_counts: List[int] = []
    build_failures = 0
    test_failures = 0
    timeout_events = 0
    candidate_files = set(plan.candidate_files or plan.target_files or [])

    runner_callable = None
    metadata = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    candidate_runner = metadata.get("agentic_test_runner")
    if callable(candidate_runner):
        runner_callable = candidate_runner

    def _run_attempt(code: str, focus: Optional[str]) -> ExecutionResult:
        if runner_callable:
            return runner_callable(code=code, ctx=ctx, subtask_focus=focus)
        return execute_attempt(code, ctx, timeout_seconds=cfg.test_timeout_seconds)

    current_code, _ = generate_initial_code(strategy_name, ctx, plan, tracker, semantic_cfg)
    result = _run_attempt(current_code, None)
    contract_state = evaluate_contract_coverage(ctx.metadata if isinstance(ctx.metadata, dict) else {}, result.tests)
    result.edit_metadata["contract_coverage"] = contract_state.coverage
    result.edit_metadata["contract_satisfied"] = contract_state.satisfied_ids
    result.edit_metadata["contract_unsatisfied"] = contract_state.unsatisfied_ids
    result.edit_metadata["contract_failure_categories"] = contract_state.categories
    result.edit_metadata["contract_unsatisfied_details"] = render_unsatisfied_details(
        ctx.metadata if isinstance(ctx.metadata, dict) else {},
        contract_state.unsatisfied_ids,
    )
    result.edit_metadata["contract_fail_cases"] = contract_state.failing_cases
    last_contract_state = contract_state
    total_tests += len(result.tests)
    edited_files_acc.update(result.edited_files)
    implementation_targets = metadata.get("implementation_target_files") if isinstance(metadata, dict) else []
    implementation_target_set = {str(path) for path in (implementation_targets or []) if str(path)}
    implementation_touched: set[str] = {path for path in result.edited_files if path in implementation_target_set}
    inspected_files_acc.update(result.inspected_files)
    proposed_files_acc.update(result.proposed_files)
    attempt_file_counts.append(len(set(result.edited_files or [])))
    build_failures += sum(1 for record in result.tests if record.get("name") == "build" and record.get("status") != "pass")
    test_failures += sum(1 for record in result.tests if record.get("name") == "tests" and record.get("status") != "pass")
    timeout_events += sum(1 for record in result.tests if record.get("status") == "timeout")
    round_traces.append(_round_entry(0, "initial", "plan", False, result))
    initial_pass = result.pass_rate == 1.0
    compile_failed = result.compile_failed
    repairs_performed = 0
    localized_queue = list(plan.subtasks)
    last_summary = result.summary

    while (
        result.pass_rate < 1.0
        and repairs_performed < cfg.max_repair_rounds
        and last_summary is not None
    ):
        repairs_performed += 1
        pending_impl_targets = [path for path in implementation_target_set if path not in implementation_touched]
        forced_focus = f"implementation::{pending_impl_targets[0]}" if pending_impl_targets else None
        if forced_focus:
            focus = forced_focus
            localized = True
        else:
            focus, localized = _next_focus(localized_queue, policy, repairs_performed)
        new_code, _ = generate_repair_code(
            strategy_name,
            ctx,
            plan,
            last_summary,
            current_code,
            focus,
            result,
            tracker,
            semantic_cfg,
        )
        if localized and focus not in subtasks_touched:
            subtasks_touched.append(focus)
        localized_attempts += 1 if localized else 0
        monolithic_attempts += 0 if localized else 1
        current_code = new_code
        result = _run_attempt(current_code, focus if localized else "global")
        contract_state = evaluate_contract_coverage(ctx.metadata if isinstance(ctx.metadata, dict) else {}, result.tests)
        result.edit_metadata["contract_coverage"] = contract_state.coverage
        result.edit_metadata["contract_satisfied"] = contract_state.satisfied_ids
        result.edit_metadata["contract_unsatisfied"] = contract_state.unsatisfied_ids
        result.edit_metadata["contract_failure_categories"] = contract_state.categories
        result.edit_metadata["contract_unsatisfied_details"] = render_unsatisfied_details(
            ctx.metadata if isinstance(ctx.metadata, dict) else {},
            contract_state.unsatisfied_ids,
        )
        result.edit_metadata["contract_fail_cases"] = contract_state.failing_cases
        last_contract_state = contract_state
        total_tests += len(result.tests)
        edited_files_acc.update(result.edited_files)
        implementation_touched.update(path for path in result.edited_files if path in implementation_target_set)
        inspected_files_acc.update(result.inspected_files)
        proposed_files_acc.update(result.proposed_files)
        attempt_file_counts.append(len(set(result.edited_files or [])))
        build_failures += sum(1 for record in result.tests if record.get("name") == "build" and record.get("status") != "pass")
        test_failures += sum(1 for record in result.tests if record.get("name") == "tests" and record.get("status") != "pass")
        timeout_events += sum(1 for record in result.tests if record.get("status") == "timeout")
        round_traces.append(_round_entry(repairs_performed, "repair", focus, localized, result))
        last_summary = result.summary
        if result.pass_rate == 1.0:
            break

    final_pass = result.pass_rate == 1.0
    if initial_pass:
        final_status = "passed_initial"
    elif final_pass:
        final_status = "passed_after_repair"
    elif repairs_performed >= cfg.max_repair_rounds and result.pass_rate < 1.0:
        final_status = "exhausted_repairs"
    elif compile_failed and repairs_performed == 0:
        final_status = "failed_compile"
    else:
        final_status = "failed_tests"

    planning_tokens = float(plan.diagnostics.get("planning_tokens", 0) or 0.0)
    planning_time = float(plan.diagnostics.get("planning_time", 0.0) or 0.0)
    total_tokens = planning_tokens + float(tracker.tokens)
    total_time = planning_time + tracker.time_spent

    traces_payload = [trace.to_dict() for trace in round_traces]
    trace_path = None
    if cfg.store_traces:
        trace_path = write_round_traces(
            task_id=ctx.task_id,
            strategy_name=strategy_name,
            plan=plan,
            rounds=traces_payload,
            output_dir=cfg.trace_dir,
        )

    edited_set = set(edited_files_acc)
    proposed_set = set(proposed_files_acc)
    candidate_hits = len(candidate_files & edited_set) if candidate_files else 0
    localization_precision = (candidate_hits / len(edited_set)) if edited_set else 0.0
    localization_recall = (candidate_hits / len(candidate_files)) if candidate_files else 0.0
    proposed_hits = len(candidate_files & proposed_set) if candidate_files else 0
    candidate_overlap_rate = (proposed_hits / len(proposed_set)) if proposed_set else 0.0
    ground_truth_files = set()
    gt_list = metadata.get("repo_ground_truth_files") if metadata else None
    if isinstance(gt_list, list):
        ground_truth_files = {str(item) for item in gt_list}
    ground_truth_hits = len(ground_truth_files & edited_set) if ground_truth_files else 0
    ground_truth_precision = (ground_truth_hits / len(edited_set)) if edited_set else 0.0
    ground_truth_recall = (ground_truth_hits / len(ground_truth_files)) if ground_truth_files else 0.0
    oracle_files = set()
    oracle_list = metadata.get("oracle_patch_files") if isinstance(metadata, dict) else None
    if isinstance(oracle_list, list):
        oracle_files = {str(item) for item in oracle_list if str(item)}
    if not oracle_files:
        oracle_files = set(ground_truth_files)
    oracle_hits = len(oracle_files & edited_set) if oracle_files else 0
    oracle_precision = (oracle_hits / len(edited_set)) if edited_set else 0.0
    oracle_recall = (oracle_hits / len(oracle_files)) if oracle_files else 0.0
    timeout_rate = (timeout_events / total_tests) if total_tests else 0.0
    full_regen_rate = (monolithic_attempts / max(1, localized_attempts + monolithic_attempts))
    repo_target_files = metadata.get("repo_target_files") if isinstance(metadata, dict) else []
    target_set = {str(f) for f in (repo_target_files or []) if str(f)}
    implementation_source = metadata.get("implementation_target_files") if isinstance(metadata, dict) else None
    implementation_files = {str(f) for f in (implementation_source or []) if str(f)} if implementation_source else set()
    if implementation_files:
        target_set = set(implementation_files)
    else:
        implementation_files = set(target_set)
    implementation_hits = len(implementation_files & edited_set) if implementation_files else 0
    implementation_precision = (implementation_hits / len(edited_set)) if edited_set else 0.0
    implementation_recall = (implementation_hits / len(implementation_files)) if implementation_files else 0.0
    missing_implementation_files = sorted(implementation_files - edited_set)
    implementation_multi_expected = 1.0 if len(implementation_files) > 1 else 0.0
    implementation_multi_edit = 1.0 if len(implementation_files & edited_set) > 1 else 0.0
    implementation_under_localized = 1.0 if missing_implementation_files else 0.0
    target_hits = len(target_set & edited_set) if target_set else 0
    target_precision = (target_hits / len(edited_set)) if edited_set else 0.0
    target_recall = (target_hits / len(target_set)) if target_set else 0.0
    missing_target_files = sorted(target_set - edited_set)
    expected_files = metadata.get("expected_files") if isinstance(metadata, dict) else None
    if not expected_files:
        expected_files = list(target_set if target_set else implementation_files)
    expected_set = {str(f) for f in (expected_files or []) if str(f)}
    missing_expected_files = sorted(expected_set - edited_set)
    expected_multi_flag = bool(metadata.get("multi_file_localization")) or len(expected_set) > 1
    expected_multi_file = 1.0 if expected_multi_flag else 0.0
    multi_file_edit = 1.0 if len(edited_files_acc) > 1 else 0.0
    under_localized_targets = 1.0 if expected_set and missing_expected_files else 0.0
    under_localized_ground_truth = 1.0 if ground_truth_files and ground_truth_hits < len(ground_truth_files) else 0.0
    total_patch_attempts = len(attempt_file_counts)
    multi_attempts = sum(1 for count in attempt_file_counts if count > 1)
    avg_attempt_file_count = (sum(attempt_file_counts) / total_patch_attempts) if total_patch_attempts else 0.0
    multi_file_attempt_rate = (multi_attempts / total_patch_attempts) if total_patch_attempts else 0.0

    metrics: Dict[str, float | str] = {
        "pass_rate": result.pass_rate,
        "num_tests": len(result.tests),
        "initial_pass": 1.0 if initial_pass else 0.0,
        "final_pass": 1.0 if final_pass else 0.0,
        "repair_rounds": float(repairs_performed),
        "total_tests_run": float(total_tests),
        "decomposition_depth": float(len(plan.subtasks)),
        "subtasks_repaired": float(len(subtasks_touched)),
        "localized_repairs": float(localized_attempts),
        "monolithic_repairs": float(monolithic_attempts),
        "localized_repair_rate": (localized_attempts / repairs_performed) if repairs_performed else 0.0,
        "compile_failed": compile_failed,
        "final_status": final_status,
        "round_trace_path": str(trace_path) if trace_path else "",
        "tokens_used": total_tokens,
        "planning_time": total_time,
        "repair_gain": (1.0 if final_pass else 0.0) - (1.0 if initial_pass else 0.0),
        "subtasks_targeted": ";".join(subtasks_touched),
        "edited_file_count": float(len(edited_files_acc)),
        "edited_files": ";".join(sorted(edited_files_acc)),
        "files_inspected_count": float(len(inspected_files_acc)),
        "files_inspected": ";".join(sorted(inspected_files_acc)),
        "files_proposed_count": float(len(proposed_files_acc)),
        "proposed_files": ";".join(sorted(proposed_files_acc)),
        "candidate_files": ";".join(plan.candidate_files or []),
        "localization_precision": localization_precision,
        "localization_recall": localization_recall,
        "target_file_precision": target_precision,
        "target_file_recall": target_recall,
        "missing_target_files": ";".join(missing_target_files),
        "missing_expected_files": ";".join(missing_expected_files),
        "expected_file_count": float(len(expected_set)),
        "candidate_overlap_rate": candidate_overlap_rate,
        "ground_truth_precision": ground_truth_precision,
        "ground_truth_recall": ground_truth_recall,
        "ground_truth_file_count": float(len(ground_truth_files)),
        "under_localized_ground_truth": under_localized_ground_truth,
        "under_localized_targets": under_localized_targets,
        "oracle_file_precision": oracle_precision,
        "oracle_file_recall": oracle_recall,
        "oracle_file_count": float(len(oracle_files)),
        "missing_oracle_files": ";".join(sorted(oracle_files - edited_set)),
        "implementation_precision": implementation_precision,
        "implementation_recall": implementation_recall,
        "implementation_file_count": float(len(implementation_files)),
        "missing_implementation_files": ";".join(missing_implementation_files),
        "implementation_under_localized": implementation_under_localized,
        "implementation_multi_file_expected": implementation_multi_expected,
        "implementation_multi_file_edit": implementation_multi_edit,
        "multi_file_edit": multi_file_edit,
        "expected_multi_file": expected_multi_file,
        "multi_file_attempt_rate": multi_file_attempt_rate,
        "avg_attempt_file_count": avg_attempt_file_count,
        "timeout_rate": timeout_rate,
        "full_regeneration_rate": full_regen_rate,
        "build_failures": float(build_failures),
        "test_failures": float(test_failures),
    }
    if last_contract_state:
        metrics["contract_coverage"] = last_contract_state.coverage
        metrics["contract_satisfied"] = ";".join(last_contract_state.satisfied_ids)
        metrics["contract_unsatisfied"] = ";".join(last_contract_state.unsatisfied_ids)
        metrics["contract_failure_categories"] = ";".join(
            f"{category}:{count}" for category, count in last_contract_state.categories.items()
        )
        metrics["contract_failure_cases"] = ";".join(last_contract_state.failing_cases)
        metrics["dominant_semantic_failure"] = (
            max(last_contract_state.categories, key=last_contract_state.categories.get)
            if last_contract_state.categories
            else ""
        )
    else:
        metrics["contract_coverage"] = 0.0
        metrics["contract_satisfied"] = ""
        metrics["contract_unsatisfied"] = ""
        metrics["contract_failure_categories"] = ""
        metrics["contract_failure_cases"] = ""
        metrics["dominant_semantic_failure"] = ""
    metrics.setdefault("decomposition_steps", float(len(plan.subtasks) or len(plan.contract) or 1))
    if extra_metrics:
        metrics.update(extra_metrics)
    failing_test_names = [
        str(record.get("name") or record.get("cmd") or f"test_{idx}")
        for idx, record in enumerate(result.tests)
        if record.get("status") not in {"pass", "passed"}
    ]
    metrics["failing_tests_after_run"] = ",".join(failing_test_names[:8])
    if result.summary:
        metrics["dominant_failing_tests"] = ",".join(result.summary.failing_tests[:6])
        metrics["dominant_failure_modes"] = ",".join(result.summary.error_types[:4])
        metrics["dominant_failure_category"] = (
            result.summary.error_types[0] if result.summary.error_types else result.status
        )
    else:
        metrics["dominant_failure_category"] = result.status

    strategy_result = StrategyResult(
        plan=plan,
        solution_code=current_code,
        tests_run=result.tests,
        metrics=metrics,
        round_traces=traces_payload,
    )
    return strategy_result


__all__ = [
    "AgenticExecutionConfig",
    "RepairPolicy",
    "RoundTrace",
    "execute_plan_with_repair",
]
