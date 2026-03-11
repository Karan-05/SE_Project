"""Benchmark decomposition strategies on repository-backed tasks."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import types
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd

from src.config import PathConfig
from src.decomposition.real_repo import RepoTaskHarness, RepoTaskSpec, load_repo_tasks
from src.decomposition.real_repo.ground_truth import load_ground_truth_files
from src.decomposition.real_repo.preflight import run_preflight_checks, write_preflight_report
from src.decomposition.real_repo.retrieval import rank_candidate_files
from src.decomposition.registry import STRATEGIES
from src.decomposition.runners.run_on_task import run_strategy_on_task
from src.providers import llm


def _strategy_list(raw: str | None) -> Sequence[str]:
    if not raw:
        return list(STRATEGIES.keys())
    return [item.strip() for item in raw.split(",") if item.strip()]


def _split_csv(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class BenchmarkPaths:
    """Resolve output paths for the requested run mode."""

    mode: str
    base_root: Path = PathConfig().reports_root / "decomposition"

    def __post_init__(self) -> None:
        suffix = "real_world" if self.mode == "real_world_research" else "development"
        self.root = self.base_root / suffix / "real_repo"
        self.root.mkdir(parents=True, exist_ok=True)
        self.run_root = self.root / "runs"
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.csv = self.root / "strategy_comparison.csv"
        self.case_md = self.root / "case_studies.md"
        self.summary_md = self.root / "summary.md"
        self.preflight_json = self.root / "preflight_report.json"
        self.preflight_md = self.root / "preflight_report.md"


def _collect_context_snippets(task: RepoTaskSpec, harness: RepoTaskHarness, limit: int = 4, max_chars: int = 800) -> List[Dict[str, str]]:
    snippets: List[Dict[str, str]] = []
    workspace = harness.workspace
    candidates: List[str] = []
    for source in (
        task.target_files,
        task.file_context,
        getattr(task, "metadata", {}).get("related_tests"),
    ):
        if not source:
            continue
        for entry in source:
            entry_str = str(entry).strip()
            if entry_str and entry_str not in candidates:
                candidates.append(entry_str)
    for rel in candidates:
        path = workspace / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        preview = text.strip()
        if len(preview) > max_chars:
            preview = preview[:max_chars].rstrip() + "..."
        snippets.append({"path": rel, "preview": preview})
        if len(snippets) >= limit:
            break
    return snippets


def _prepare_task_payload(task: RepoTaskSpec, harness: RepoTaskHarness) -> Dict[str, object]:
    payload = task.to_task_dict()
    metadata = dict(payload.get("metadata") or {})
    metadata["agentic_test_runner"] = harness.evaluate_attempt
    metadata["repo_task"] = True
    metadata["test_timeout_seconds"] = task.timeout_seconds
    metadata["repo_workspace_logs"] = str(harness.logs_dir)
    try:
        retrieval = rank_candidate_files(task, harness.workspace)
    except Exception:
        retrieval = {"candidates": task.target_files or task.file_context or [], "keywords": [], "modes": ["fallback"]}
    metadata["repo_candidate_files"] = retrieval.get("candidates", [])
    metadata["repo_candidate_keywords"] = retrieval.get("keywords", [])
    metadata["repo_candidate_scores"] = retrieval.get("scores", [])
    metadata["repo_retrieval_mode"] = retrieval.get("modes", [])
    metadata["repo_retrieval_scanned"] = retrieval.get("scanned_files", 0)
    metadata["repo_retrieval_content_scanned"] = retrieval.get("content_inspected", 0)
    metadata["repo_candidate_reasons"] = retrieval.get("reasons", {})
    gt_patch = metadata.get("ground_truth_patch")
    if gt_patch:
        metadata["repo_ground_truth_files"] = load_ground_truth_files(gt_patch)
        metadata.setdefault("oracle_patch_files", list(metadata.get("repo_ground_truth_files", [])))
    metadata["repo_setup_plan"] = harness.setup_plan.to_dict()
    metadata["repo_setup_record"] = harness.setup_record
    metadata["repo_context_snippets"] = _collect_context_snippets(task, harness)
    metadata["repo_snapshot_expected"] = harness.snapshot_record.get("expected_snapshot", "")
    metadata["repo_snapshot_computed"] = harness.snapshot_record.get("computed_snapshot", "")
    metadata["repo_snapshot_verified"] = harness.snapshot_record.get("snapshot_verified", True)
    metadata["repo_snapshot_log"] = harness.snapshot_record.get("log_path", "")
    payload["metadata"] = metadata
    payload["tests"] = []
    payload["reference_solution"] = ""
    return payload


def _write_case_studies(entries: List[Dict[str, object]], paths: BenchmarkPaths, *, provider: str, model: str) -> None:
    lines = [
        f"# Real Repository Case Studies ({paths.mode})",
        "",
        f"- Provider: {provider}",
        f"- Model: {model}",
        "",
    ]
    if not entries:
        lines.append("No tasks evaluated.")
        paths.case_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    for entry in entries:
        task: RepoTaskSpec = entry["task"]
        strategy = entry["strategy"]
        result = entry.get("result")
        setup_record = entry.get("setup") or {}
        metadata = entry.get("metadata") or {}
        plan = result.plan if result and getattr(result, "plan", None) else None
        lines.append(f"## {task.task_id} — {strategy}")
        lines.append(f"- Repo: `{task.repo_path}` ({task.dataset}/{task.dataset_source})")
        lines.append(f"- Task flags: reportable={task.reportable} fixture={task.task_is_fixture} real_world={task.task_is_real_world}")
        lines.append(f"- Prompt: {task.prompt.strip()}")
        setup_status = setup_record.get("status", "unknown")
        setup_plan = setup_record.get("plan", {})
        setup_strategy = setup_plan.get("strategy", "")
        setup_log = setup_record.get("last_log", "")
        lines.append(f"- Workspace setup: {setup_status} (strategy={setup_strategy})")
        if setup_log:
            lines.append(f"- Setup log: `{setup_log}`")
        if not result:
            lines.append("- Benchmark skipped due to workspace setup failure.")
            lines.append("")
            continue
        target_files = plan.target_files if plan and plan.target_files else task.target_files or task.file_context
        target_line = ", ".join(target_files)
        candidate_files = plan.candidate_files if plan and plan.candidate_files else metadata.get("repo_candidate_files", [])
        expected_files = metadata.get("expected_files") or target_files
        ground_truth_files = metadata.get("repo_ground_truth_files") or []
        lines.append(f"- Target files: {target_line or 'unspecified'}")
        if expected_files:
            lines.append(f"- Expected files (per spec): {', '.join(expected_files[:6])}")
        impl_targets = metadata.get("implementation_target_files") or expected_files or target_files
        if impl_targets:
            lines.append(f"- Implementation target files: {', '.join(impl_targets[:6])}")
        support_files = metadata.get("support_files") or []
        if support_files:
            lines.append(f"- Support files: {', '.join(support_files[:6])}")
        lines.append(f"- Candidate files: {', '.join(candidate_files[:8]) if candidate_files else 'n/a'}")
        test_files = metadata.get("test_files") or metadata.get("related_tests") or []
        if test_files:
            lines.append(f"- Test files: {', '.join(test_files[:6])}")
        oracle_files = metadata.get("oracle_patch_files") or ground_truth_files
        if oracle_files:
            lines.append(f"- Oracle patch files: {', '.join(oracle_files[:6])}")
        edit_policy = metadata.get("allowed_editable_files")
        if isinstance(edit_policy, dict) and edit_policy:
            policy_bits = []
            for scope, entries in edit_policy.items():
                if not entries:
                    continue
                preview = ", ".join(entries[:3])
                policy_bits.append(f"{scope}: {preview}")
            if policy_bits:
                lines.append(f"- Allowed edit policy: {'; '.join(policy_bits)}")
        plan_subtasks = plan.subtasks if plan else []
        lines.append(f"- Subtasks: {', '.join(plan_subtasks[:6]) if plan_subtasks else 'n/a'}")
        lines.append(
            f"- Final status: {result.metrics.get('final_status', 'unknown')} "
            f"(pass_rate={result.metrics.get('pass_rate', 0.0):.2f})"
        )
        edited_files = [part for part in (result.metrics.get("edited_files", "") or "").split(";") if part]
        lines.append(f"- Edited files: {', '.join(edited_files) if edited_files else 'none'}")
        if ground_truth_files:
            lines.append(f"- Ground-truth files: {', '.join(ground_truth_files)}")
        mf_note = "multi-file" if result.metrics.get("multi_file_edit", 0.0) else "single-file"
        lines.append(f"- Edit shape: {mf_note} (expected multi-file={bool(result.metrics.get('expected_multi_file', 0.0))})")
        missing_impl = result.metrics.get("missing_implementation_files", "")
        if missing_impl:
            lines.append(f"- Untouched implementation files: {missing_impl}")
        missing_targets = result.metrics.get("missing_target_files", "")
        if missing_targets:
            lines.append(f"- Untouched target files: {missing_targets}")
        missing_expected = result.metrics.get("missing_expected_files", "")
        if missing_expected and missing_expected != missing_targets:
            lines.append(f"- Untouched expected files: {missing_expected}")
        lines.append(f"- Build/test failures: build={result.metrics.get('build_failures', 0)} tests={result.metrics.get('test_failures', 0)}")
        lines.append(
            f"- Localization precision/recall: "
            f"{result.metrics.get('localization_precision', 0.0):.2f} / "
            f"{result.metrics.get('localization_recall', 0.0):.2f}"
        )
        lines.append(
            f"- Target precision/recall: "
            f"{result.metrics.get('target_file_precision', 0.0):.2f} / "
            f"{result.metrics.get('target_file_recall', 0.0):.2f}"
        )
        lines.append(
            f"- Implementation precision/recall: "
            f"{result.metrics.get('implementation_precision', 0.0):.2f} / "
            f"{result.metrics.get('implementation_recall', 0.0):.2f}"
        )
        lines.append(
            f"- Repair attempt multi-file rate: {result.metrics.get('multi_file_attempt_rate', 0.0):.2f} "
            f"(avg files/attempt={result.metrics.get('avg_attempt_file_count', 0.0):.2f})"
        )
        contract_cov = result.metrics.get("contract_coverage")
        if contract_cov is not None:
            lines.append(
                f"- Contract coverage: {contract_cov:.2f} "
                f"(satisfied={result.metrics.get('contract_satisfied', '') or 'n/a'}, "
                f"unsatisfied={result.metrics.get('contract_unsatisfied', '') or 'n/a'})"
            )
        if result.metrics.get("contract_failure_categories"):
            lines.append(
                f"- Semantic failure categories: {result.metrics.get('contract_failure_categories')}"
            )
        if result.metrics.get("dominant_semantic_failure"):
            lines.append(
                f"- Dominant semantic gap: {result.metrics.get('dominant_semantic_failure')}"
            )
        if result.metrics.get("localization_precision", 0.0) >= 0.5:
            loc_note = "Most edits aligned with planned targets."
        elif result.metrics.get("localization_precision", 0.0) == 0:
            loc_note = "Edits missed all planned targets."
        else:
            loc_note = "Localization partially overlapped with edits."
        lines.append(f"- Localization note: {loc_note}")
        gt_files = result.metrics.get("oracle_file_count", 0.0) or result.metrics.get("ground_truth_file_count", 0.0)
        if gt_files:
            lines.append(
                f"- Oracle overlap: precision={result.metrics.get('oracle_file_precision', result.metrics.get('ground_truth_precision', 0.0)):.2f} "
                f"recall={result.metrics.get('oracle_file_recall', result.metrics.get('ground_truth_recall', 0.0)):.2f} files={gt_files:.0f}"
            )
        if result.metrics.get("implementation_under_localized", 0.0):
            lines.append("- Under-localized implementation: required product files remained untouched.")
        if result.metrics.get("under_localized_ground_truth", 0.0):
            lines.append("- Under-localized: fewer files edited than the ground-truth patch requires.")
        elif result.metrics.get("under_localized_targets", 0.0):
            lines.append("- Under-localized: expected multi-file target list was not fully edited.")
        impl_multi_expected = result.metrics.get("implementation_multi_file_expected", 0.0)
        if impl_multi_expected:
            lines.append(
                f"- Implementation multi-file coverage: {result.metrics.get('implementation_multi_file_edit', 0.0):.2f}/"
                f"{impl_multi_expected:.2f}"
            )
        failing_tests = entry.get("tests") or result.tests_run or []
        failing_names = [
            str(record.get("name") or record.get("cmd") or f"test_{idx}")
            for idx, record in enumerate(failing_tests)
            if record.get("status") not in {"pass", "passed"}
        ]
        if failing_names:
            lines.append(f"- Failing tests after run: {', '.join(failing_names[:6])}")
        dom_mode = result.metrics.get("dominant_failure_category", "")
        if dom_mode and result.metrics.get("final_pass", 0.0) < 1.0:
            dom_tests = result.metrics.get("dominant_failing_tests", "") or "n/a"
            lines.append(f"- Dominant failure mode: {dom_mode} (tests: {dom_tests})")
        traces = result.round_traces or []
        if traces:
            lines.append("### Repair rounds")
            for trace in traces:
                files = trace.get("files_touched") or []
                proposed = trace.get("proposed_files") or []
                lines.append(
                    f"* Round {trace.get('round')} ({trace.get('phase')} focus={trace.get('subtask')} localized={trace.get('localized')}): "
                    f"status={trace.get('status')} proposed={', '.join(proposed)} files={', '.join(files)}"
                )
        lines.append("")
    paths.case_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_summary(df: pd.DataFrame, paths: BenchmarkPaths) -> None:
    if df.empty:
        paths.summary_md.write_text(f"# Real Repo Summary ({paths.mode})\n\nNo runs recorded.\n", encoding="utf-8")
        return
    agg = (
        df.groupby("strategy")
        .agg(
            task_count=("task_id", "count"),
            pass_rate=("pass_rate", "mean"),
            initial_success_rate=("initial_pass", "mean"),
            final_success_rate=("final_pass", "mean"),
            repair_gain=("repair_gain", "mean"),
            avg_repair_rounds=("repair_rounds", "mean"),
            avg_files_touched=("edited_file_count", "mean"),
            avg_files_inspected=("files_inspected_count", "mean"),
            avg_files_proposed=("files_proposed_count", "mean"),
            localized_edit_rate=("localized_repair_rate", "mean"),
            avg_build_failures=("build_failures", "mean"),
            avg_test_failures=("test_failures", "mean"),
            avg_localization_precision=("localization_precision", "mean"),
            avg_localization_recall=("localization_recall", "mean"),
            avg_impl_precision=("implementation_precision", "mean"),
            avg_impl_recall=("implementation_recall", "mean"),
            avg_ground_truth_precision=("ground_truth_precision", "mean"),
            avg_ground_truth_recall=("ground_truth_recall", "mean"),
            avg_oracle_precision=("oracle_file_precision", "mean"),
            avg_oracle_recall=("oracle_file_recall", "mean"),
            avg_multi_file_edit=("multi_file_edit", "mean"),
            expected_multi_file_rate=("expected_multi_file", "mean"),
            avg_impl_multi_edit=("implementation_multi_file_edit", "mean"),
            expected_impl_multi_rate=("implementation_multi_file_expected", "mean"),
            avg_timeout_rate=("timeout_rate", "mean"),
            avg_full_regen_rate=("full_regeneration_rate", "mean"),
            avg_subtasks_touched=("avg_subtasks_touched", "mean"),
            avg_target_precision=("target_file_precision", "mean"),
            avg_target_recall=("target_file_recall", "mean"),
            under_localized_ground_truth_rate=("under_localized_ground_truth", "mean"),
            under_localized_targets_rate=("under_localized_targets", "mean"),
            implementation_under_localized_rate=("implementation_under_localized", "mean"),
            avg_multi_file_attempt_rate=("multi_file_attempt_rate", "mean"),
            avg_attempt_file_count=("avg_attempt_file_count", "mean"),
            avg_contract_coverage=("contract_coverage", "mean"),
        )
        .reset_index()
    )
    agg["final_success_rate"] = agg["final_success_rate"].fillna(0.0)
    oracle_final = agg.loc[agg["strategy"] == "oracle_teacher", "final_success_rate"].iloc[0] if "oracle_teacher" in agg["strategy"].values else 0.0
    oracle_pass_rate = agg.loc[agg["strategy"] == "oracle_teacher", "pass_rate"].iloc[0] if "oracle_teacher" in agg["strategy"].values else 0.0

    def _top_tokens(series: pd.Series, limit: int = 2) -> str:
        counter: Counter[str] = Counter()
        for value in series.fillna(""):
            for token in str(value).split(","):
                token = token.strip()
                if token:
                    counter[token] += 1
        return ", ".join(name for name, _ in counter.most_common(limit))

    lines = [f"# Real Repo Summary ({paths.mode})", ""]
    for _, row in agg.iterrows():
        strat_df = df[df["strategy"] == row["strategy"]]
        fail_tests = _top_tokens(strat_df["dominant_failing_tests"])
        fail_modes = _top_tokens(strat_df["dominant_failure_modes"])
        semantic_fail = _top_tokens(strat_df["dominant_semantic_failure"])
        vs_oracle = row["final_success_rate"] - oracle_final if row["strategy"] != "oracle_teacher" else 0.0
        lines.append(
            f"- **{row['strategy']}** tasks={int(row['task_count'])} "
            f"initial={row['initial_success_rate']:.2f} final={row['final_success_rate']:.2f} "
            f"gain={row['repair_gain']:.2f} files={row['avg_files_touched']:.2f} "
            f"localized={row['localized_edit_rate']:.2f} repair_rounds={row['avg_repair_rounds']:.2f} "
            f"inspected={row['avg_files_inspected']:.2f} proposed={row['avg_files_proposed']:.2f} "
            f"precision={row['avg_localization_precision']:.2f} recall={row['avg_localization_recall']:.2f} "
            f"impl={row['avg_impl_precision']:.2f}/{row['avg_impl_recall']:.2f} "
            f"oracle={row['avg_oracle_precision']:.2f}/{row['avg_oracle_recall']:.2f} "
            f"multi_file={row['avg_multi_file_edit']:.2f}/{row['expected_multi_file_rate']:.2f} "
            f"impl_multi={row['avg_impl_multi_edit']:.2f}/{row['expected_impl_multi_rate']:.2f} "
            f"subtasks_touched={row['avg_subtasks_touched']:.2f} "
            f"target_hit={row['avg_target_precision']:.2f}/{row['avg_target_recall']:.2f} "
            f"multi_file_attempt={row['avg_multi_file_attempt_rate']:.2f} "
            f"attempt_file_count={row['avg_attempt_file_count']:.2f} "
            f"uloc_gt={row['under_localized_ground_truth_rate']:.2f} "
            f"uloc_targets={row['under_localized_targets_rate']:.2f} "
            f"uloc_impl={row['implementation_under_localized_rate']:.2f} "
            f"timeout={row['avg_timeout_rate']:.2f} regen={row['avg_full_regen_rate']:.2f} "
            f"contract={row['avg_contract_coverage']:.2f} "
            f"fail_tests={fail_tests or 'n/a'} fail_modes={fail_modes or 'n/a'} "
            f"semantic_fail={semantic_fail or 'n/a'} "
            f"vs_oracle={vs_oracle:.2f}"
        )
    lines.append("")
    if "oracle_teacher" in agg["strategy"].values:
        lines.append(
            f"Oracle_teacher final success={oracle_final:.2f}, pass_rate={oracle_pass_rate:.2f}. "
            f"Use it as solvability upper-bound."
        )
    paths.summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _collect_specs(sources: Sequence[Path]) -> List[RepoTaskSpec]:
    seen: Dict[str, RepoTaskSpec] = {}
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(f"Task source {source} not found.")
        for spec in load_repo_tasks(source):
            seen[spec.task_id] = spec
    return list(seen.values())


def _filter_specs(
    specs: Sequence[RepoTaskSpec],
    *,
    include_datasets: Sequence[str],
    exclude_datasets: Sequence[str],
    mode: str,
    require_reportable: bool,
    exclude_fixtures: bool,
) -> List[RepoTaskSpec]:
    include_norm = {token.lower() for token in include_datasets}
    exclude_norm = {token.lower() for token in exclude_datasets}
    filtered: List[RepoTaskSpec] = []
    for spec in specs:
        dataset_tokens = {spec.dataset.lower(), spec.dataset_source.lower()}
        if include_norm and not (dataset_tokens & include_norm):
            continue
        if exclude_norm and (dataset_tokens & exclude_norm):
            continue
        if mode == "real_world_research":
            if not spec.task_is_real_world or spec.task_is_fixture:
                continue
            if not spec.reportable:
                continue
        else:
            if exclude_fixtures and spec.task_is_fixture:
                continue
            if require_reportable and not spec.reportable:
                continue
        filtered.append(spec)
    return filtered


def _build_metrics_row(
    *,
    task: RepoTaskSpec,
    strategy: str,
    metrics: Dict[str, object],
    metadata: Dict[str, object],
    repo_metrics: Dict[str, object],
    provider: str,
    model: str,
    provider_is_mock: bool,
    mode: str,
) -> Dict[str, object]:
    return {
        "task_id": task.task_id,
        "dataset": task.dataset,
        "dataset_source": task.dataset_source,
        "strategy": strategy,
        "repo": str(task.repo_path),
        "run_mode": mode,
        "reportable": task.reportable,
        "task_is_fixture": task.task_is_fixture,
        "task_is_real_world": task.task_is_real_world,
        "provider": provider,
        "model": model,
        "provider_is_mock": provider_is_mock,
        "pass_rate": metrics.get("pass_rate", 0.0),
        "initial_pass": metrics.get("initial_pass", 0.0),
        "final_pass": metrics.get("final_pass", 0.0),
        "final_status": metrics.get("final_status", ""),
        "repair_rounds": metrics.get("repair_rounds", 0.0),
        "repair_gain": metrics.get("repair_gain", 0.0),
        "edited_file_count": metrics.get("edited_file_count", 0.0),
        "edited_files": metrics.get("edited_files", ""),
        "files_inspected_count": metrics.get("files_inspected_count", 0.0),
        "files_inspected": metrics.get("files_inspected", ""),
        "files_proposed_count": metrics.get("files_proposed_count", 0.0),
        "proposed_files": metrics.get("proposed_files", ""),
        "candidate_files": metrics.get("candidate_files", ""),
        "localized_repair_rate": metrics.get("localized_repair_rate", 0.0),
        "localization_precision": metrics.get("localization_precision", 0.0),
        "localization_recall": metrics.get("localization_recall", 0.0),
        "target_file_precision": metrics.get("target_file_precision", 0.0),
        "target_file_recall": metrics.get("target_file_recall", 0.0),
        "implementation_precision": metrics.get("implementation_precision", 0.0),
        "implementation_recall": metrics.get("implementation_recall", 0.0),
        "missing_target_files": metrics.get("missing_target_files", ""),
        "missing_expected_files": metrics.get("missing_expected_files", ""),
        "missing_implementation_files": metrics.get("missing_implementation_files", ""),
        "expected_file_count": metrics.get("expected_file_count", 0.0),
        "implementation_file_count": metrics.get("implementation_file_count", 0.0),
        "ground_truth_precision": metrics.get("ground_truth_precision", 0.0),
        "ground_truth_recall": metrics.get("ground_truth_recall", 0.0),
        "ground_truth_file_count": metrics.get("ground_truth_file_count", 0.0),
        "oracle_file_precision": metrics.get("oracle_file_precision", 0.0),
        "oracle_file_recall": metrics.get("oracle_file_recall", 0.0),
        "oracle_file_count": metrics.get("oracle_file_count", 0.0),
        "missing_oracle_files": metrics.get("missing_oracle_files", ""),
        "under_localized_ground_truth": metrics.get("under_localized_ground_truth", 0.0),
        "under_localized_targets": metrics.get("under_localized_targets", 0.0),
        "implementation_under_localized": metrics.get("implementation_under_localized", 0.0),
        "candidate_overlap_rate": metrics.get("candidate_overlap_rate", 0.0),
        "tokens_used": metrics.get("tokens_used", 0.0),
        "planning_time": metrics.get("planning_time", 0.0),
        "build_failures": metrics.get("build_failures", 0.0),
        "test_failures": metrics.get("test_failures", 0.0),
        "timeout_rate": metrics.get("timeout_rate", 0.0),
        "full_regeneration_rate": metrics.get("full_regeneration_rate", 0.0),
        "avg_subtasks_touched": metrics.get("subtasks_repaired", 0.0),
        "multi_file_attempt_rate": metrics.get("multi_file_attempt_rate", 0.0),
        "avg_attempt_file_count": metrics.get("avg_attempt_file_count", 0.0),
        "dominant_failing_tests": metrics.get("dominant_failing_tests", ""),
        "dominant_failure_modes": metrics.get("dominant_failure_modes", ""),
        "dominant_failure_category": metrics.get("dominant_failure_category", ""),
        "dominant_semantic_failure": metrics.get("dominant_semantic_failure", ""),
        "contract_coverage": metrics.get("contract_coverage", 0.0),
        "contract_satisfied": metrics.get("contract_satisfied", ""),
        "contract_unsatisfied": metrics.get("contract_unsatisfied", ""),
        "contract_failure_categories": metrics.get("contract_failure_categories", ""),
        "contract_failure_cases": metrics.get("contract_failure_cases", ""),
        "failing_tests_after_run": metrics.get("failing_tests_after_run", ""),
        "retrieval_mode": ",".join(metadata.get("repo_retrieval_mode", [])),
        "retrieval_candidate_count": len(metadata.get("repo_candidate_files", [])),
        "retrieval_scanned_files": metadata.get("repo_retrieval_scanned", 0),
        "retrieval_content_inspected": metadata.get("repo_retrieval_content_scanned", 0),
        "round_trace_path": metrics.get("round_trace_path", ""),
        "setup_status": repo_metrics.get("setup_status", "unknown"),
        "setup_duration": repo_metrics.get("setup_duration", 0.0),
        "setup_plan_strategy": repo_metrics.get("setup_plan_strategy", ""),
        "setup_requires_network": repo_metrics.get("setup_requires_network", 0.0),
        "setup_last_log": repo_metrics.get("setup_last_log", ""),
        "setup_summary_path": repo_metrics.get("setup_summary_path", ""),
        "multi_file_edit": metrics.get("multi_file_edit", 0.0),
        "expected_multi_file": metrics.get("expected_multi_file", 0.0),
        "implementation_multi_file_edit": metrics.get("implementation_multi_file_edit", 0.0),
        "implementation_multi_file_expected": metrics.get("implementation_multi_file_expected", 0.0),
    }


def _run_oracle_baseline(
    task: RepoTaskSpec,
    *,
    metadata: Dict[str, object],
    paths: BenchmarkPaths,
    provider: str,
    model: str,
) -> Dict[str, object] | None:
    patch_ref = metadata.get("ground_truth_patch")
    if not patch_ref:
        return None
    harness = RepoTaskHarness(task, "oracle_teacher", paths.run_root)
    payload = _prepare_task_payload(task, harness)
    merged_metadata = payload.get("metadata", metadata)
    applied_files: List[str] = []
    try:
        applied_files = harness.apply_patch_file(Path(patch_ref))
    except Exception as exc:
        tests = [
            {
                "name": "apply_patch",
                "status": "fail",
                "error": str(exc),
                "stdout": "",
                "stderr": "",
            }
        ]
        status = "patch_failed"
        pass_rate = 0.0
        compile_failed = True
    else:
        run = harness.run_build_and_tests()
        tests = run["tests"]
        status = run["status"]
        pass_rate = run["pass_rate"]
        compile_failed = run["compile_failed"]
    gt_file_count = float(len(applied_files)) if isinstance(applied_files, list) else 0.0
    multi_file_edit = 1.0 if len(applied_files) > 1 else 0.0
    expected_multi = 1.0 if len(task.target_files) > 1 else 0.0
    metrics: Dict[str, float | str] = {
        "pass_rate": pass_rate,
        "num_tests": len(tests),
        "initial_pass": pass_rate,
        "final_pass": pass_rate,
        "repair_rounds": 0.0,
        "total_tests_run": float(len(tests)),
        "decomposition_depth": 0.0,
        "subtasks_repaired": 0.0,
        "localized_repairs": 0.0,
        "monolithic_repairs": 0.0,
        "localized_repair_rate": 0.0,
        "compile_failed": compile_failed,
        "final_status": "passed_initial" if pass_rate == 1.0 else status,
        "round_trace_path": "",
        "tokens_used": 0.0,
        "planning_time": 0.0,
        "repair_gain": 0.0,
        "subtasks_targeted": "",
        "edited_file_count": float(len(applied_files)),
        "edited_files": ";".join(applied_files),
        "files_inspected_count": float(len(task.file_context or task.target_files)),
        "files_inspected": ";".join(task.file_context or task.target_files),
        "files_proposed_count": float(len(applied_files)),
        "proposed_files": ";".join(applied_files),
        "candidate_files": ";".join(merged_metadata.get("repo_candidate_files", [])),
        "localization_precision": 1.0 if applied_files else 0.0,
        "localization_recall": 1.0 if applied_files else 0.0,
        "candidate_overlap_rate": 1.0 if applied_files else 0.0,
        "ground_truth_precision": 1.0 if applied_files else 0.0,
        "ground_truth_recall": 1.0 if applied_files else 0.0,
        "ground_truth_file_count": gt_file_count,
        "multi_file_edit": multi_file_edit,
        "expected_multi_file": expected_multi,
        "timeout_rate": 0.0,
        "full_regeneration_rate": 0.0,
        "build_failures": float(sum(1 for rec in tests if rec.get("name", "").startswith("build") and rec.get("status") != "pass")),
        "test_failures": float(sum(1 for rec in tests if rec.get("name", "").startswith("tests") and rec.get("status") != "pass")),
        "avg_subtasks_touched": 0.0,
    }
    repo_metrics = harness.repo_metrics()
    row = _build_metrics_row(
        task=task,
        strategy="oracle_teacher",
        metrics=metrics,
        metadata=merged_metadata,
        repo_metrics=repo_metrics,
        provider=provider,
        model=model,
        provider_is_mock=False,
        mode=paths.mode,
    )
    dummy_result = types.SimpleNamespace(plan=None, metrics=metrics, round_traces=[], tests_run=tests)
    case_entry = {
        "task": task,
        "strategy": "oracle_teacher",
        "result": dummy_result,
        "setup": harness.setup_record,
        "metadata": merged_metadata,
        "tests": tests,
    }
    return {"row": row, "case": case_entry}


def run_real_repo_benchmark(
    task_sources: Sequence[Path],
    *,
    strategies: Sequence[str],
    mode: str = "dev",
    include_datasets: Sequence[str] | None = None,
    exclude_datasets: Sequence[str] | None = None,
    max_tasks: Optional[int] = None,
    require_reportable: bool = False,
    exclude_fixtures: bool = False,
    include_oracle: bool = False,
    paths: Optional[BenchmarkPaths] = None,
) -> pd.DataFrame:
    paths = paths or BenchmarkPaths(mode)
    provider = str(llm.CONFIG.provider or "unknown")
    model = str(llm.CONFIG.model or "")
    provider_is_mock = provider.startswith("mock") or "mock" in provider.lower()
    model_is_mock = model.startswith("mock")
    specs = _collect_specs(task_sources)
    include = include_datasets or []
    exclude = exclude_datasets or []
    specs = _filter_specs(
        specs,
        include_datasets=include,
        exclude_datasets=exclude,
        mode=mode,
        require_reportable=require_reportable,
        exclude_fixtures=exclude_fixtures,
    )
    if not specs:
        raise RuntimeError("No tasks remain after filtering; provide real-world repo tasks.")
    preflight_report = run_preflight_checks(specs, task_sources=task_sources, mode=mode, provider=provider, model=model)
    write_preflight_report(preflight_report, paths.preflight_json, paths.preflight_md)
    if not preflight_report.ok:
        raise RuntimeError(f"Preflight failed; see {paths.preflight_md}")
    if max_tasks is not None:
        specs = specs[:max_tasks]
    rows: List[Dict[str, object]] = []
    case_entries: List[Dict[str, object]] = []
    include_oracle = include_oracle and paths.mode == "real_world_research"
    for task in specs:
        base_metadata = dict(getattr(task, "metadata", {}) or {})
        shared_metadata: Optional[Dict[str, object]] = base_metadata or None
        for strategy in strategies:
            harness = RepoTaskHarness(task, strategy, paths.run_root)
            task_payload = _prepare_task_payload(task, harness)
            metadata = task_payload.get("metadata", {})
            if shared_metadata is None:
                shared_metadata = metadata
            repo_metrics = harness.repo_metrics()
            if not harness.setup_ready:
                metrics = {
                    "pass_rate": 0.0,
                    "initial_pass": 0.0,
                    "final_pass": 0.0,
                    "final_status": "setup_failed",
                    "repair_rounds": 0.0,
                    "repair_gain": 0.0,
                    "edited_file_count": 0.0,
                    "edited_files": "",
                    "files_inspected_count": 0.0,
                    "files_inspected": "",
                    "files_proposed_count": 0.0,
                    "proposed_files": "",
                    "candidate_files": ";".join(metadata.get("repo_candidate_files", [])),
                    "localized_repair_rate": 0.0,
                    "localization_precision": 0.0,
                    "localization_recall": 0.0,
                    "ground_truth_precision": 0.0,
                    "ground_truth_recall": 0.0,
                    "ground_truth_file_count": 0.0,
                    "candidate_overlap_rate": 0.0,
                    "tokens_used": 0.0,
                    "planning_time": 0.0,
                    "build_failures": 0.0,
                    "test_failures": 0.0,
                    "timeout_rate": 0.0,
                    "full_regeneration_rate": 0.0,
                    "subtasks_repaired": 0.0,
                    "round_trace_path": "",
                    "multi_file_edit": 0.0,
                    "expected_multi_file": 1.0 if len(task.target_files) > 1 else 0.0,
                }
                metrics.update(repo_metrics)
                rows.append(
                    _build_metrics_row(
                        task=task,
                        strategy=strategy,
                        metrics=metrics,
                        metadata=metadata,
                        repo_metrics=repo_metrics,
                        provider=provider,
                        model=model,
                        provider_is_mock=provider_is_mock or model_is_mock,
                        mode=mode,
                    )
                )
                case_entries.append(
                    {
                        "task": task,
                        "strategy": strategy,
                        "result": None,
                        "setup": harness.setup_record,
                        "metadata": metadata,
                        "tests": [],
                    }
                )
                continue
            result = run_strategy_on_task(strategy, task_payload)
            metrics = dict(result.metrics)
            metrics.update(repo_metrics)
            rows.append(
                _build_metrics_row(
                    task=task,
                    strategy=strategy,
                    metrics=metrics,
                    metadata=metadata,
                    repo_metrics=repo_metrics,
                    provider=provider,
                    model=model,
                    provider_is_mock=provider_is_mock or model_is_mock,
                    mode=mode,
                )
            )
            case_entries.append(
                {
                    "task": task,
                    "strategy": strategy,
                    "result": result,
                    "setup": harness.setup_record,
                    "metadata": metadata,
                    "tests": result.tests_run,
                }
            )
        if include_oracle and shared_metadata:
            oracle_output = _run_oracle_baseline(
                task,
                metadata=shared_metadata,
                paths=paths,
                provider=provider,
                model=model,
            )
            if oracle_output:
                rows.append(oracle_output["row"])
                case_entries.append(oracle_output["case"])
    df = pd.DataFrame(rows)
    df.to_csv(paths.csv, index=False)
    _write_case_studies(case_entries, paths, provider=provider, model=model)
    _write_summary(df, paths)
    return df


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run repository-backed decomposition benchmark.")
    parser.add_argument(
        "--tasks-file",
        action="append",
        type=Path,
        default=[],
        help="JSON/JSONL manifest of repo tasks (can be supplied multiple times).",
    )
    parser.add_argument(
        "--task-root",
        action="append",
        type=Path,
        default=[],
        help="Directory containing per-task metadata (task.json).",
    )
    parser.add_argument("--strategies", type=str, default=None, help="Comma-separated list of strategies.")
    parser.add_argument("--mode", type=str, choices=["dev", "real_world_research"], default="dev")
    parser.add_argument("--datasets", type=str, default=None, help="Comma-separated dataset/dataset_source allowlist.")
    parser.add_argument("--exclude-datasets", type=str, default=None, help="Comma-separated blocklist.")
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--require-reportable", action="store_true", help="Filter tasks to reportable ones.")
    parser.add_argument("--exclude-fixtures", action="store_true", help="Drop fixture tasks from dev runs.")
    parser.add_argument("--provider", type=str, default=None, help="Override LLM provider label.")
    parser.add_argument("--model", type=str, default=None, help="Override model label.")
    parser.add_argument("--skip-oracle", action="store_true", help="Skip teacher/oracle baseline runs.")
    args = parser.parse_args()

    if args.provider or args.model:
        llm.set_config(provider=args.provider, model=args.model)

    default_root = PathConfig().experiments_dir / "real_repo_tasks" / "dev"
    default_topcoder = PathConfig().experiments_dir / "real_repo_tasks" / "topcoder"
    legacy_manifest = PathConfig().experiments_dir / "decomposition" / "real_repo_tasks.jsonl"
    sources: List[Path] = []
    sources.extend(args.tasks_file)
    sources.extend(args.task_root)
    if not sources:
        if args.mode == "real_world_research" and default_topcoder.exists():
            sources.append(default_topcoder)
        elif default_root.exists():
            sources.append(default_root)
        elif legacy_manifest.exists():
            sources.append(legacy_manifest)
    paths = BenchmarkPaths(args.mode)
    df = run_real_repo_benchmark(
        sources,
        strategies=_strategy_list(args.strategies),
        mode=args.mode,
        include_datasets=_split_csv(args.datasets),
        exclude_datasets=_split_csv(args.exclude_datasets),
        max_tasks=args.max_tasks,
        require_reportable=args.require_reportable,
        exclude_fixtures=args.exclude_fixtures,
        include_oracle=not args.skip_oracle,
        paths=paths,
    )
    print(f"Wrote reports to {paths.csv}")


if __name__ == "__main__":  # pragma: no cover
    main()
