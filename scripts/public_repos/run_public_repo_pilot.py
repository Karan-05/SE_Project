#!/usr/bin/env python3
"""Run CGCS pilot benchmark on seeded repair tasks."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.decomposition.real_repo import RepoTaskHarness
from src.decomposition.real_repo.strict_logging import STRICT_TRACE_FILENAME
from src.decomposition.real_repo.task import RepoTaskSpec
from src.decomposition.real_repo.retrieval import rank_candidate_files
from src.decomposition.real_repo.ground_truth import load_ground_truth_files
from src.decomposition.runners.run_on_task import run_strategy_on_task
from src.providers import llm
from src.public_repos.pilot.trace_quality import validate_trace_requirements


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _load_task_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_context_snippets(
    task: RepoTaskSpec, harness: RepoTaskHarness, limit: int = 4, max_chars: int = 800
) -> List[Dict[str, str]]:
    snippets: List[Dict[str, str]] = []
    workspace = harness.workspace
    candidates: List[str] = list(task.target_files or []) + list(task.file_context or [])
    seen: set[str] = set()
    for rel in candidates:
        if rel in seen:
            continue
        seen.add(rel)
        path = workspace / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        preview = text.strip()[:max_chars]
        snippets.append({"path": rel, "preview": preview})
        if len(snippets) >= limit:
            break
    return snippets


def _prepare_task_payload(
    task: RepoTaskSpec, harness: RepoTaskHarness
) -> Dict[str, Any]:
    payload = task.to_task_dict()
    metadata = dict(payload.get("metadata") or {})
    metadata["agentic_test_runner"] = harness.evaluate_attempt
    metadata["repo_task"] = True
    metadata["test_timeout_seconds"] = task.timeout_seconds
    metadata["repo_workspace_logs"] = str(harness.logs_dir)
    try:
        retrieval = rank_candidate_files(task, harness.workspace)
    except Exception:
        retrieval = {
            "candidates": task.target_files or task.file_context or [],
            "keywords": [],
            "modes": ["fallback"],
        }
    metadata["repo_candidate_files"] = retrieval.get("candidates", [])
    metadata["repo_candidate_keywords"] = retrieval.get("keywords", [])
    metadata["repo_candidate_scores"] = retrieval.get("scores", [])
    metadata["repo_retrieval_mode"] = retrieval.get("modes", [])
    metadata["repo_setup_plan"] = harness.setup_plan.to_dict()
    metadata["repo_setup_record"] = harness.setup_record
    metadata["repo_context_snippets"] = _collect_context_snippets(task, harness)
    metadata["repo_snapshot_computed"] = harness.snapshot_record.get("computed_snapshot", "")
    metadata["repo_snapshot_verified"] = harness.snapshot_record.get("snapshot_verified", True)
    payload["metadata"] = metadata
    payload["tests"] = []
    payload["reference_solution"] = ""
    return payload


def run_task_with_strategy(
    task_json: Dict[str, Any],
    strategy_name: str,
    runs_root: Path,
) -> Dict[str, Any]:
    """Run one strategy on one task.  Returns a result dict."""
    task_id = str(task_json.get("id") or task_json.get("task_id") or "unknown")
    start = time.monotonic()

    try:
        task = RepoTaskSpec.from_dict(task_json)
    except Exception as exc:
        return {
            "task_id": task_id,
            "strategy": strategy_name,
            "status": "spec_error",
            "error": str(exc),
            "duration": round(time.monotonic() - start, 2),
        }

    try:
        harness = RepoTaskHarness(
            task=task,
            strategy_name=strategy_name,
            output_root=runs_root,
        )
    except Exception as exc:
        return {
            "task_id": task_id,
            "strategy": strategy_name,
            "status": "harness_error",
            "error": str(exc),
            "duration": round(time.monotonic() - start, 2),
        }

    if not harness.setup_ready:
        return {
            "task_id": task_id,
            "strategy": strategy_name,
            "status": "setup_failed",
            "error": harness.setup_record.get("error", "setup not ready"),
            "duration": round(time.monotonic() - start, 2),
        }

    payload = _prepare_task_payload(task, harness)

    try:
        result = run_strategy_on_task(strategy_name, payload)
        status = "ok"
        metrics = dict(result.metrics or {})
        error = None
    except Exception as exc:
        status = "strategy_error"
        metrics = {}
        error = str(exc)

    duration = round(time.monotonic() - start, 2)
    return {
        "task_id": task_id,
        "strategy": strategy_name,
        "status": status,
        "metrics": metrics,
        "error": error,
        "duration": duration,
        "logs_dir": str(harness.logs_dir),
    }


def run_pilot_benchmark(
    *,
    tasks_manifest: Path,
    runs_root: Path,
    out_dir: Path,
    strategies: Sequence[str],
    max_tasks: int = 0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    manifest = _load_jsonl(tasks_manifest)
    if max_tasks > 0:
        manifest = manifest[:max_tasks]

    print(f"[pilot-run] Tasks={len(manifest)}  strategies={strategies}")

    if dry_run:
        import os

        os.environ["LLM_PROVIDER"] = "mock"

    all_results: List[Dict[str, Any]] = []
    for entry in manifest:
        task_json_path = Path(str(entry.get("task_json_path") or ""))
        task_json = _load_task_json(task_json_path)
        if task_json is None:
            print(f"  SKIP (missing task.json): {task_json_path}")
            continue

        task_id = str(entry.get("task_id") or task_json.get("id") or "?")
        for strategy in strategies:
            print(f"  [{task_id}] strategy={strategy}", flush=True)
            result = run_task_with_strategy(task_json, strategy, runs_root)
            if result["status"] == "ok" and not dry_run:
                logs_dir = Path(result.get("logs_dir") or "")
                if logs_dir.exists():
                    strict_trace_path = logs_dir / STRICT_TRACE_FILENAME
                    strict_trace_ready = strict_trace_path.exists() and strict_trace_path.stat().st_size > 0
                    if not strict_trace_ready:
                        result["status"] = "trace_missing_fields"
                        result["error"] = f"strict trace artifact missing: {strict_trace_path}"
                    else:
                        ready, missing_fields = validate_trace_requirements(logs_dir)
                        if not ready:
                            result["status"] = "trace_missing_fields"
                            result["error"] = f"missing fields: {', '.join(missing_fields)}"
            all_results.append(result)
            print(f"     status={result['status']}  duration={result['duration']}s")

    from collections import Counter

    status_counts = Counter(result["status"] for result in all_results)
    ok = status_counts.get("ok", 0)
    summary = {
        "total_runs": len(all_results),
        "status_counts": dict(status_counts),
        "strategies": list(strategies),
        "tasks": len(manifest),
        "dry_run": dry_run,
    }
    summary_json = out_dir / "pilot_run_summary.json"
    summary_alt = out_dir / "summary.json"
    _write_json(summary_json, summary)
    _write_json(summary_alt, summary)

    md_path = out_dir / "summary.md"
    md_lines = [
        "# Public Repo Pilot — Strategy Runs",
        "",
        f"* Tasks: {len(manifest)}",
        f"* Strategies: {', '.join(strategies)}",
        f"* Total runs: {summary['total_runs']}",
        "",
        "| Status | Count |",
        "|---|---|",
    ]
    for status, count in sorted(status_counts.items()):
        md_lines.append(f"| {status} | {count} |")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"[pilot-run] Done: {ok}/{len(all_results)} successful")
    print(f"[pilot-run] Summary → {summary_json}")
    print(f"[pilot-run] Markdown → {md_path}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks-manifest", type=Path, default=Path("data/public_repos/pilot/tasks_manifest.jsonl")
    )
    parser.add_argument("--runs-root", type=Path, default=Path("reports/decomposition/public_repo_pilot/runs"))
    parser.add_argument("--out-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    parser.add_argument(
        "--strategies",
        default="contract_first,failure_mode_first,cgcs",
        help="Comma-separated list of strategy names",
    )
    parser.add_argument("--max-tasks", type=int, default=0, help="0 = no limit")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    run_pilot_benchmark(
        tasks_manifest=args.tasks_manifest,
        runs_root=args.runs_root,
        out_dir=args.out_dir,
        strategies=strategies,
        max_tasks=args.max_tasks,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
