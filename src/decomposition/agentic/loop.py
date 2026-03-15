"""Iterative solve-test-repair controller."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.config import PathConfig
from src.decomposition.agentic.executor import ExecutionResult, execute_attempt
from src.decomposition.agentic.semantic import SemanticVariantConfig, get_semantic_config
from src.decomposition.agentic.solver import generate_initial_code, generate_repair_code
from src.decomposition.real_repo.contracts import (
    ContractCoverageResult,
    contract_items_to_dicts,
    evaluate_contract_coverage,
    get_contract_items,
    render_unsatisfied_details,
)
from src.decomposition.real_repo.cgcs_logging import build_cgcs_round_trace
from src.decomposition.real_repo.contract_graph import build_contract_graph, choose_next_clause, update_from_run
from src.decomposition.real_repo.witnesses import SemanticWitness, extract_mocha_witnesses
from src.decomposition.real_repo.strict_logging import persist_strict_trace_entry
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
    clause_driven: bool = False


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


def _normalize_file_list(*sources: Optional[List[str]]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for source in sources:
        if not source:
            continue
        for entry in source:
            entry_str = str(entry).strip()
            if not entry_str or entry_str in seen:
                continue
            seen.add(entry_str)
            ordered.append(entry_str)
    return ordered


def _select_active_clause_id(
    active_clause_id: str,
    contract_items: Sequence[Dict[str, object]],
    strategy_name: str,
) -> str:
    normalized = str(active_clause_id or "").strip()
    if normalized:
        return normalized
    for item in contract_items:
        candidate = str(item.get("id") or "").strip()
        if candidate:
            return candidate
    return f"{strategy_name}_default_clause"


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

    contract_items = get_contract_items(metadata)
    contract_item_dicts = contract_items_to_dicts(contract_items)
    if contract_item_dicts and not plan.contract_items:
        plan.contract_items = contract_item_dicts
    cgcs_graph = build_contract_graph(contract_items) if contract_items else None
    candidate_files_raw = _normalize_file_list(
        metadata.get("repo_candidate_files"),
        metadata.get("repo_target_files"),
        metadata.get("expected_files"),
        plan.candidate_files,
    )
    candidate_files_filtered = _normalize_file_list(
        plan.candidate_files,
        metadata.get("implementation_target_files"),
        metadata.get("expected_files"),
        metadata.get("repo_target_files"),
    )
    if not candidate_files_filtered:
        candidate_files_filtered = candidate_files_raw or _normalize_file_list(metadata.get("repo_target_files"))
    strategy_mode_label = policy.description if policy else strategy_name

    def _run_attempt(code: str, focus: Optional[str]) -> ExecutionResult:
        if runner_callable:
            return runner_callable(code=code, ctx=ctx, subtask_focus=focus)
        return execute_attempt(code, ctx, timeout_seconds=cfg.test_timeout_seconds)

    def _annotate_contract_state(
        result: ExecutionResult,
        attempt_index: int,
        active_clause_id: str,
        clause_reason: str,
    ) -> ContractCoverageResult:
        contract_state_local = evaluate_contract_coverage(metadata, result.tests)
        result.edit_metadata["contract_coverage"] = contract_state_local.coverage
        result.edit_metadata["contract_satisfied"] = contract_state_local.satisfied_ids
        result.edit_metadata["contract_unsatisfied"] = contract_state_local.unsatisfied_ids
        result.edit_metadata["contract_failure_categories"] = contract_state_local.categories
        result.edit_metadata["contract_unsatisfied_details"] = render_unsatisfied_details(
            metadata,
            contract_state_local.unsatisfied_ids,
        )
        result.edit_metadata["contract_fail_cases"] = contract_state_local.failing_cases
        result.edit_metadata.setdefault("candidate_files_raw", candidate_files_raw)
        result.edit_metadata.setdefault("candidate_files_filtered", candidate_files_filtered)
        if "candidate_files" not in result.edit_metadata:
            result.edit_metadata["candidate_files"] = candidate_files_filtered or candidate_files_raw
        result.edit_metadata["contract_items"] = contract_item_dicts
        witnesses = extract_mocha_witnesses(result.tests)
        result.edit_metadata["witness_count"] = len(witnesses)
        if witnesses:
            result.edit_metadata["witness_samples"] = [
                {
                    "test_case": witness.test_case,
                    "message": (witness.message or "")[:160],
                    "category": witness.category,
                    "expected": witness.expected,
                    "actual": witness.actual,
                    "contracts": witness.linked_contract_ids,
                }
                for witness in witnesses[:6]
            ]
        raw_payload = str(result.edit_metadata.get("raw_edit_payload") or "")
        payload_parse_ok = bool(result.edit_metadata.get("payload_parse_ok", bool(raw_payload)))
        payload_parse_error = str(result.edit_metadata.get("payload_parse_error") or "")
        regression_guards = list(cgcs_graph.regression_guard_ids) if cgcs_graph else []
        lint_errors = result.edit_metadata.get("lint_errors") or []
        skipped_targets = result.edit_metadata.get("skipped_targets") or []
        outcome_metrics = {
            "status": result.status,
            "pass_rate": result.pass_rate,
            "duration": result.duration,
            "failing_tests": result.summary.failing_tests if result.summary else [],
            "error_types": result.summary.error_types if result.summary else [],
        }
        resolved_clause = _select_active_clause_id(active_clause_id, contract_item_dicts, strategy_name)
        cgcs_trace = build_cgcs_round_trace(
            task_id=ctx.task_id,
            strategy=strategy_name,
            round_index=attempt_index,
            contract_items=contract_item_dicts,
            active_clause_id=resolved_clause,
            regression_guard_ids=regression_guards,
            witnesses=witnesses,
            raw_edit_payload=raw_payload,
            payload_parse_ok=payload_parse_ok,
            payload_parse_error=payload_parse_error or None,
            candidate_files_raw=candidate_files_raw,
            candidate_files_filtered=candidate_files_filtered,
            clause_selection_reason=clause_reason,
            lint_errors=lint_errors,
            skipped_targets=skipped_targets,
            outcome_metrics=outcome_metrics,
            strategy_mode=strategy_mode_label,
            used_fallback=bool(result.edit_metadata.get("fallback_requested")),
        )
        strict_payload = cgcs_trace.to_dict()
        if cgcs_graph:
            update_from_run(cgcs_graph, contract_state_local, witnesses, attempt_index)
            cgcs_payload = dict(strict_payload)
            cgcs_payload["coverage"] = contract_state_local.coverage
            cgcs_payload["satisfied_ids"] = contract_state_local.satisfied_ids
            cgcs_payload["unsatisfied_ids"] = contract_state_local.unsatisfied_ids
            cgcs_payload["regressed_ids"] = list(cgcs_graph.regressed_ids)
            cgcs_payload["witness_counts"] = {
                cid: len(cgcs_graph.witness_index.get(cid, [])) for cid in cgcs_graph.nodes
            }
            cgcs_payload["witness_sample"] = cgcs_trace.witnesses[:6]
            cgcs_payload["regression_guards"] = regression_guards
            cgcs_payload.setdefault("active_clause", cgcs_trace.active_clause_id)
            strict_payload = cgcs_payload
            choose_next_clause(cgcs_graph)
        artifacts = result.artifacts if isinstance(result.artifacts, dict) else {}
        result.edit_metadata["cgcs_state"] = strict_payload
        result.edit_metadata["witnesses"] = cgcs_trace.witnesses
        result.edit_metadata["row_quality"] = cgcs_trace.row_quality
        result.edit_metadata["regression_guard_ids"] = strict_payload.get("regression_guard_ids", regression_guards)
        result.edit_metadata["candidate_files"] = cgcs_trace.candidate_files
        result.edit_metadata["candidate_files_raw"] = cgcs_trace.candidate_files_raw
        result.edit_metadata["candidate_files_filtered"] = cgcs_trace.candidate_files_filtered
        result.edit_metadata["active_clause_id"] = cgcs_trace.active_clause_id
        result.edit_metadata["strict_trace"] = strict_payload
        persist_strict_trace_entry(
            logs_dir=artifacts.get("logs_dir"),
            edit_log_path=artifacts.get("edit_log"),
            strict_entry=strict_payload,
        )
        return contract_state_local

    def _populate_cgcs_metrics(metrics_dict: Dict[str, float | str]) -> None:
        if not cgcs_graph or not cgcs_graph.nodes:
            metrics_dict.setdefault("clause_discharge_rate", 0.0)
            metrics_dict.setdefault("clauses_regressed_count", 0.0)
            metrics_dict.setdefault("witness_count", 0.0)
            metrics_dict.setdefault("witness_unique_count", 0.0)
            metrics_dict.setdefault("time_to_first_discharge", -1.0)
            metrics_dict.setdefault("rounds_to_full_discharge", -1.0)
            return
        total = len(cgcs_graph.nodes)
        satisfied_rounds = [
            node.satisfied_round for node in cgcs_graph.nodes.values() if node.satisfied_round is not None
        ]
        witness_count = sum(len(witnesses or []) for witnesses in cgcs_graph.witness_index.values())
        unique_signatures = {
            signature for node in cgcs_graph.nodes.values() for signature in node.witness_signatures
        }
        first_discharge = min(satisfied_rounds) if satisfied_rounds else -1
        full_discharge = (
            max(satisfied_rounds)
            if satisfied_rounds and len(satisfied_rounds) == total and not cgcs_graph.unsatisfied_ids and not cgcs_graph.regressed_ids
            else -1
        )
        metrics_dict["clause_discharge_rate"] = (len(cgcs_graph.regression_guard_ids) / total) if total else 0.0
        metrics_dict["clauses_regressed_count"] = float(len(cgcs_graph.regressed_ids))
        metrics_dict["witness_count"] = float(witness_count)
        metrics_dict["witness_unique_count"] = float(len(unique_signatures))
        metrics_dict["time_to_first_discharge"] = float(first_discharge)
        metrics_dict["rounds_to_full_discharge"] = float(full_discharge)

    current_code, _ = generate_initial_code(strategy_name, ctx, plan, tracker, semantic_cfg)
    result = _run_attempt(current_code, None)
    initial_clause_id = cgcs_graph.active_clause_id if cgcs_graph else ""
    initial_clause_reason = ""
    if cgcs_graph:
        initial_clause_reason = cgcs_graph.last_clause_reason or "initial_clause_seed"
    else:
        initial_clause_reason = "no_contract_graph"
    contract_state = _annotate_contract_state(result, 0, initial_clause_id, initial_clause_reason)
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
        elif policy.clause_driven and cgcs_graph and cgcs_graph.active_clause_id:
            focus = f"contract::{cgcs_graph.active_clause_id}"
            localized = True
        else:
            focus, localized = _next_focus(localized_queue, policy, repairs_performed)
        clause_id_for_round = cgcs_graph.active_clause_id if cgcs_graph else ""
        clause_reason_for_round = ""
        if not cgcs_graph:
            clause_reason_for_round = "no_contract_graph"
        elif forced_focus:
            clause_reason_for_round = "implementation_target_guard"
        elif localized and focus and str(focus).startswith("implementation::"):
            clause_reason_for_round = "implementation_focus"
        elif localized and focus and str(focus).startswith("contract::"):
            clause_reason_for_round = cgcs_graph.last_clause_reason or "clause_queue"
        elif localized and focus:
            clause_reason_for_round = f"subtask_focus::{focus}"
        else:
            clause_reason_for_round = "global_default"
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
        contract_state = _annotate_contract_state(result, repairs_performed, clause_id_for_round, clause_reason_for_round)
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
    _populate_cgcs_metrics(metrics)
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
