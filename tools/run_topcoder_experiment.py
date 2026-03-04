"""CLI entrypoint to run the Topcoder self-verifying experiment."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import sys
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import PathConfig
from src.experiments.topcoder import ExperimentConfig, run_topcoder_experiment
from src.experiments.topcoder.task_router import TaskType
from src.providers import llm
from src.experiments.topcoder.llm_utils import llm_available
from tools.summarize_topcoder_run import build_run_metrics, evaluate_gate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Topcoder experiment across all discovered datasets.")
    parser.add_argument("--run-id", help="Optional run identifier (default uses timestamp).")
    parser.add_argument("--max-tasks", type=int, help="Limit the number of tasks for smoke tests.")
    parser.add_argument("--resume", action="store_true", help="Reuse existing checkpoint.jsonl if present.")
    parser.add_argument("--rate-limit", type=float, default=0.0, help="Seconds to sleep between task starts.")
    parser.add_argument("--parallelism", type=int, default=1, help="Number of concurrent tasks (default 1).")
    parser.add_argument(
        "--dataset-dir",
        action="append",
        type=Path,
        dest="dataset_dirs",
        help="Additional dataset root to search (can be passed multiple times).",
    )
    parser.add_argument(
        "--include-datasets",
        action="append",
        dest="include_datasets",
        help="Only include dataset IDs matching the given glob (repeatable).",
    )
    parser.add_argument(
        "--exclude-datasets",
        action="append",
        dest="exclude_datasets",
        help="Exclude dataset IDs matching the given glob (repeatable).",
    )
    parser.add_argument("--dataset-limit", type=int, help="Stop discovery after N datasets.")
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategy_order",
        help="Override the default strategy order (can be repeated).",
    )
    parser.add_argument(
        "--force-task-type",
        choices=[t.value for t in TaskType],
        help="Force the router to treat every task as the given type (diagnostics only).",
    )
    parser.add_argument(
        "--default-non-coding-mode",
        choices=["design_doc", "architecture_doc", "skip"],
        default="design_doc",
        help="Fallback mode when encountering non-coding tasks (default: design_doc).",
    )
    parser.add_argument("--require-tests", action="store_true", help="Require embedded tests before running a task.")
    parser.add_argument(
        "--no-require-tests",
        action="store_false",
        dest="require_tests",
        help="Allow automatic synthesis/extraction when tests missing (default).",
    )
    parser.set_defaults(require_tests=False)
    parser.add_argument(
        "--use-samples-as-tests",
        action="store_true",
        default=True,
        help="Treat dataset samples/examples as executable tests (default).",
    )
    parser.add_argument(
        "--no-use-samples-as-tests",
        action="store_false",
        dest="use_samples_as_tests",
        help="Ignore samples/examples from datasets.",
    )
    parser.add_argument(
        "--synthesize-tests",
        action="store_true",
        default=True,
        help="Enable LLM-based test synthesis when tests are missing (default).",
    )
    parser.add_argument(
        "--no-synthesize-tests",
        action="store_false",
        dest="synthesize_tests",
        help="Disable LLM-based test synthesis.",
    )
    parser.add_argument(
        "--max-synthesized-tests-per-task",
        type=int,
        default=8,
        help="Maximum number of synthesized tests per task (default 8).",
    )
    parser.add_argument(
        "--max-tasks-needing-synthesis",
        type=int,
        default=200,
        help="Maximum number of tasks that will trigger synthesis (default 200).",
    )
    parser.add_argument(
        "--allow-no-llm",
        action="store_true",
        help="Allow running without an LLM provider; tasks requiring synthesis will be skipped.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["mock", "openai", "azure_openai", "anthropic"],
        help="LLM provider to use.",
    )
    parser.add_argument("--llm-model", help="Override the provider model identifier.")
    parser.add_argument("--no-cache", action="store_true", help="Disable on-disk LLM response cache.")
    parser.add_argument(
        "--cache-ok",
        action="store_true",
        help="Allow cached LLM responses even during presentation runs (default disables cache for real providers).",
    )
    parser.add_argument("--max-llm-calls", type=int, help="Maximum LLM calls before stopping.")
    parser.add_argument("--max-total-tokens", type=int, help="Maximum total tokens across the run.")
    parser.add_argument("--budget-usd", type=float, help="Approximate USD budget before stopping.")
    parser.add_argument("--presentation", action="store_true", help="Enable presentation-mode sampling.")
    parser.add_argument("--sample-size", type=int, help="Sample size for presentation mode (default 300).")
    parser.add_argument(
        "--sample-strategy",
        choices=["random", "stratified"],
        default="random",
        help="Sampling strategy used in presentation mode.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling.")
    parser.add_argument("--require-llm", action="store_true", help="Run LLM validation before starting the experiment.")
    parser.add_argument(
        "--task-timeout-seconds",
        type=float,
        default=300.0,
        help="Wall-clock timeout (seconds) for a single task before it is marked as timed out.",
    )
    parser.add_argument(
        "--attempt-timeout-seconds",
        type=float,
        default=120.0,
        help="Wall-clock timeout (seconds) for an individual attempt/repair iteration.",
    )
    parser.add_argument(
        "--llm-timeout-seconds",
        type=int,
        default=60,
        help="HTTP timeout (seconds) for individual LLM calls.",
    )
    parser.add_argument(
        "--test-timeout-seconds",
        type=float,
        default=30.0,
        help="Maximum time (seconds) a single test case is allowed to run.",
    )
    parser.add_argument(
        "--fail-if-zero-success",
        dest="fail_if_zero_success",
        action="store_true",
        help="Exit non-zero if no tasks are solved (presentation mode defaults to true).",
    )
    parser.add_argument(
        "--allow-zero-success",
        dest="fail_if_zero_success",
        action="store_false",
        help="Allow runs to complete even if zero tasks are solved.",
    )
    parser.set_defaults(fail_if_zero_success=None)
    parser.add_argument(
        "--fail-if-no-algo-success",
        dest="fail_if_no_algo_success",
        action="store_true",
        help="Exit non-zero if no algorithmic coding task succeeds.",
    )
    parser.add_argument(
        "--allow-no-algo-success",
        dest="fail_if_no_algo_success",
        action="store_false",
        help="Disable algorithmic success requirement.",
    )
    parser.add_argument(
        "--fail-if-no-deliverable-success",
        dest="fail_if_no_deliverable_success",
        action="store_true",
        help="Exit non-zero if no non-coding deliverable passes verification.",
    )
    parser.add_argument(
        "--allow-no-deliverable-success",
        dest="fail_if_no_deliverable_success",
        action="store_false",
        help="Disable deliverable success requirement.",
    )
    parser.set_defaults(fail_if_no_algo_success=None, fail_if_no_deliverable_success=None)
    parser.add_argument(
        "--min-success-count",
        type=int,
        default=None,
        help="Minimum number of successes required for a satisfactory run (auto-set to 1 when --max-tasks <= 20).",
    )
    parser.add_argument(
        "--min-llm-calls-per-attempted",
        type=float,
        default=None,
        help="Minimum average LLM calls per attempted task before declaring the run healthy (auto by provider).",
    )
    parser.add_argument(
        "--min-llm-calls-per-attempted-mock",
        type=float,
        default=0.0,
        help="Minimum average LLM calls per attempted task when provider=mock (default 0).",
    )
    return parser.parse_args()


def _auto_detect_provider() -> tuple[str, bool]:
    if os.getenv("OPENAI_API_KEY"):
        return "openai", True
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_DEPLOYMENT"):
        return "azure_openai", True
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic", True
    env_provider = os.getenv("LLM_PROVIDER") or os.getenv("DECOMP_LLM_PROVIDER")
    if env_provider:
        return env_provider, True
    return "mock", False


def apply_presentation_defaults(args: argparse.Namespace, provider_name: str) -> argparse.Namespace:
    provider = (provider_name or "").lower()
    if not getattr(args, "presentation", False):
        return args
    if provider != "mock":
        args.no_cache = True
        args.cache_ok = False
        if args.min_llm_calls_per_attempted is None:
            args.min_llm_calls_per_attempted = 1.0
    else:
        if args.min_llm_calls_per_attempted is None:
            args.min_llm_calls_per_attempted = getattr(args, "min_llm_calls_per_attempted_mock", 0.0) or 0.0
    return args


def configure_llm_from_args(args: argparse.Namespace) -> dict:
    cache_dir = PathConfig().reports_root / "cache" / "llm"
    provider = (args.llm_provider or "").lower()
    explicit = bool(args.llm_provider)
    if not provider:
        provider, explicit = _auto_detect_provider()
    provider = provider or "mock"
    llm.set_config(
        provider=provider,
        model=args.llm_model,
        cache_enabled=not args.no_cache,
        cache_dir=cache_dir,
        max_calls=args.max_llm_calls,
        max_tokens=args.max_total_tokens,
        budget_usd=args.budget_usd,
        timeout=args.llm_timeout_seconds,
    )
    os.environ["DECOMP_LLM_PROVIDER"] = provider
    os.environ["DECOMP_LLM_EXPLICIT"] = "1" if explicit else "0"
    os.environ["DECOMP_MOCK_MODE"] = "1" if provider == "mock" and explicit else "0"
    avail, reason = llm_available()
    os.environ["DECOMP_LLM_REASON"] = reason
    return {"provider": provider, "explicit": explicit, "available": avail, "reason": reason}


def enforce_sanity_checks(result: Dict[str, object], args: argparse.Namespace) -> None:
    run_dir = Path(result.get("report_dir", "")) if isinstance(result, dict) else None
    if not run_dir or not run_dir.exists():
        return
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return
    try:
        summary = json.loads(summary_path.read_text())
    except json.JSONDecodeError:
        return
    attempted = int(summary.get("actionable_attempted_total") or summary.get("attempted") or 0)
    successes = int(summary.get("completed_successfully") or 0)
    attempted_algo = int(summary.get("attempted_algo") or 0)
    solved_algo = int(summary.get("solved_algo") or 0)
    attempted_non_coding = int(summary.get("attempted_non_coding") or 0)
    completed_deliverables = int(summary.get("completed_deliverables") or 0)
    llm_calls_total = float(summary.get("llm_calls_total") or 0.0)
    llm_calls_per_attempted = llm_calls_total / attempted if attempted else 0.0
    violations: List[str] = []
    if args.fail_if_zero_success and attempted > 0 and successes == 0:
        violations.append("0 successes across attempted tasks")
    min_success_required = max(0, args.min_success_count or 0)
    if min_success_required and attempted > 0 and successes < min_success_required:
        violations.append(f"{successes} successes < required minimum {min_success_required}")
    min_llm_threshold = max(0.0, args.min_llm_calls_per_attempted or 0.0)
    if min_llm_threshold and attempted > 0 and llm_calls_per_attempted < min_llm_threshold:
        violations.append(
            f"LLM calls per attempted {llm_calls_per_attempted:.2f} < required {min_llm_threshold:.2f}"
        )
    if args.fail_if_no_algo_success and attempted_algo > 0 and solved_algo == 0:
        violations.append("0 algorithmic tasks solved")
    if args.fail_if_no_deliverable_success and attempted_non_coding > 0 and completed_deliverables == 0:
        violations.append("0 deliverables completed")
    if not violations:
        return
    print("Satisfactory run checks failed:", "; ".join(violations))
    run_id = result.get("run_id") if isinstance(result, dict) else None
    if not run_id:
        run_id = summary.get("run_id") or run_dir.name
    clusters = _summarize_failure_clusters(run_dir / "per_problem.csv")
    if clusters:
        print("Top failure clusters:")
        for line in clusters:
            print(" -", line)
    triage_script = PROJECT_ROOT / "tools" / "triage_decomposition_failures.py"
    if run_id and triage_script.exists():
        triage_cmd = [sys.executable, str(triage_script), "--run-id", str(run_id), "--recent-count", "20"]
        print("Triggering triage for", run_id)
        subprocess.run(triage_cmd, check=False)
    raise SystemExit(1)


def _build_rerun_command(provider: str) -> str:
    base = [sys.executable, str(Path(__file__).resolve())]
    existing = sys.argv[1:]
    rerun = base + existing[:]
    provider_normalized = (provider or "").lower()
    if provider_normalized != "mock" and "--no-cache" not in existing:
        rerun.append("--no-cache")
    if provider_normalized != "mock" and not any(flag.startswith("--min-llm-calls-per-attempted") for flag in existing):
        rerun.append("--min-llm-calls-per-attempted=1.0")
    return " ".join(shlex.quote(part) for part in rerun)


def _emit_gate_block(result: Dict[str, object], args: argparse.Namespace, provider: str) -> tuple[bool, List[str]]:
    run_id = result.get("run_id")
    print("=== GATE STATUS ===")
    if not run_id:
        message = "Run ID missing; unable to compute gate."
        print(message)
        return False, [message]
    try:
        metrics, _ = build_run_metrics(run_id)
    except Exception as exc:  # pragma: no cover - diagnostic printing
        message = f"Unable to evaluate gate metrics: {exc}"
        print(message)
        return False, [message]
    gate_passed, gate_reasons = evaluate_gate(metrics, presentation_mode=args.presentation)
    print(f"llm_calls_per_attempted: {metrics.get('llm_calls_per_attempted', 0.0):.2f}")
    print(
        f"algo_attempted/non_algo_attempted: "
        f"{metrics.get('attempted_algo', 0)} / {metrics.get('attempted_non_coding', 0)}"
    )
    print(f"deliverable_artifacts: {metrics.get('deliverable_artifacts', 0)}")
    if gate_passed:
        print("GATE: PASS")
        return True, []
    print("GATE: FAIL -> " + "; ".join(gate_reasons))
    rerun_cmd = _build_rerun_command(provider)
    print(f"Remediation: rerun with `{rerun_cmd}` or expand the sample until gates pass.")
    return False, gate_reasons


def _run_presentation_summary(run_id: Optional[str]) -> None:
    if not run_id:
        print("Summarizer skipped: missing run ID.")
        return
    summarizer = PROJECT_ROOT / "tools" / "summarize_topcoder_run.py"
    if not summarizer.exists():  # pragma: no cover - tooling guard
        print("Summarizer skipped: entrypoint missing.")
        return
    cmd = [sys.executable, str(summarizer), "--run-id", str(run_id)]
    print(f"=== PRESENTATION SUMMARY ({run_id}) ===")
    subprocess.run(cmd, check=False)


def _summarize_failure_clusters(per_problem_path: Path, limit: int = 5) -> List[str]:
    if not per_problem_path.exists():
        return []
    counts: Counter[str] = Counter()
    try:
        with per_problem_path.open("r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                status = (row.get("status") or "").strip()
                if not status or status.startswith("skipped") or status in {"success", "passed"}:
                    continue
                task_type = row.get("resolved_task_type") or row.get("task_type") or "unknown"
                error = row.get("error_type") or "unknown"
                key = f"{task_type}:{error}"
                counts[key] += 1
    except Exception:
        return []
    return [f"{key} ({count})" for key, count in counts.most_common(limit)]


def main() -> None:
    args = parse_args()
    if args.presentation and not args.sample_size:
        args.sample_size = 300
    if args.presentation and args.max_llm_calls is None:
        args.max_llm_calls = 5000
    if args.fail_if_zero_success is None:
        args.fail_if_zero_success = bool(args.presentation)
    if args.fail_if_no_algo_success is None:
        args.fail_if_no_algo_success = bool(args.presentation)
    if args.fail_if_no_deliverable_success is None:
        args.fail_if_no_deliverable_success = bool(args.presentation)
    if args.min_success_count is None:
        if args.max_tasks and args.max_tasks <= 20:
            args.min_success_count = 1
        else:
            args.min_success_count = 0
    provider_hint = (args.llm_provider or "").lower()
    if not provider_hint:
        provider_hint, _ = _auto_detect_provider()
    apply_presentation_defaults(args, provider_hint)
    selection = configure_llm_from_args(args)
    provider = (selection["provider"] or "mock").lower()
    apply_presentation_defaults(args, provider)
    if not args.presentation:
        if args.min_llm_calls_per_attempted is None:
            args.min_llm_calls_per_attempted = (
                0.5 if provider != "mock" else args.min_llm_calls_per_attempted_mock
            )
        if provider == "mock":
            args.min_llm_calls_per_attempted = args.min_llm_calls_per_attempted_mock
    if not selection["available"] and not args.allow_no_llm:
        raise SystemExit(
            "LLM provider not configured. Provide credentials via --llm-provider/ENV or re-run with --allow-no-llm."
        )
    if args.require_llm:
        if not selection["available"]:
            raise SystemExit(f"LLM provider '{selection['provider']}' unavailable ({selection['reason']}).")
        ok, message, latency, tokens = llm.validate_connection("ping")
        if not ok:
            raise SystemExit(f"LLM validation failed: {message}")
        print(json.dumps({"provider": selection["provider"], "latency_seconds": latency, "tokens": tokens}))
    config = ExperimentConfig(
        run_id=args.run_id,
        max_tasks=args.max_tasks,
        resume=args.resume,
        rate_limit=args.rate_limit,
        parallelism=max(1, args.parallelism),
        dataset_roots=args.dataset_dirs,
        dataset_limit=args.dataset_limit,
        strategy_order=args.strategy_order,
        require_tests=args.require_tests,
        use_samples_as_tests=args.use_samples_as_tests,
        synthesize_tests=args.synthesize_tests,
        max_synthesized_tests_per_task=args.max_synthesized_tests_per_task,
        max_tasks_needing_synthesis=args.max_tasks_needing_synthesis,
        allow_no_llm=args.allow_no_llm,
        presentation=args.presentation,
        sample_size=args.sample_size,
        sample_strategy=args.sample_strategy,
        sample_seed=args.seed,
        max_llm_calls=args.max_llm_calls,
        max_total_tokens=args.max_total_tokens,
        budget_usd=args.budget_usd,
        use_cache=not args.no_cache,
        task_timeout_seconds=float(args.task_timeout_seconds),
        attempt_timeout_seconds=float(args.attempt_timeout_seconds),
        llm_timeout_seconds=float(args.llm_timeout_seconds),
        test_timeout_seconds=float(args.test_timeout_seconds),
        include_datasets=args.include_datasets,
        exclude_datasets=args.exclude_datasets,
        force_task_type=args.force_task_type,
        default_non_coding_mode=args.default_non_coding_mode,
    )
    result = run_topcoder_experiment(config)
    print(json.dumps(result, indent=2, default=str))
    gate_passed, gate_reasons = _emit_gate_block(result, args, provider)
    if args.presentation:
        _run_presentation_summary(result.get("run_id") if isinstance(result, dict) else None)
        if not gate_passed:
            reason_text = "; ".join(gate_reasons) if gate_reasons else "presentation gate failed"
            raise SystemExit(f"Presentation gate failed: {reason_text}")
    enforce_sanity_checks(result, args)


if __name__ == "__main__":
    main()
