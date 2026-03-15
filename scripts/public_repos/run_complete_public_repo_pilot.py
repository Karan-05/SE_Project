#!/usr/bin/env python3
"""Run the entire public-repo pilot pipeline with rescue, seeding, runs, and strict dataset build."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from scripts.public_repos.generate_seeded_repair_tasks import generate_tasks
from scripts.public_repos.rescue_and_expand_pilot import run_rescue_and_expand
from scripts.public_repos.run_public_repo_pilot import run_pilot_benchmark


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_subprocess(cmd: List[str]) -> None:
    print(f"[pilot-orchestrator] Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def run_strict_dataset(*, runs_root: Path, output_dir: Path) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/build_cgcs_dataset.py",
        "--strict",
        "--pilot-run-root",
        str(runs_root),
        "--output-dir",
        str(output_dir),
    ]
    _run_subprocess(cmd)
    summary_path = output_dir / "dataset_summary.json"
    return _load_json(summary_path)


def build_eval_pack(input_dir: Path, out_dir: Path) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/public_repos/build_public_repo_eval_pack.py",
        "--input-dir",
        str(input_dir),
        "--out-dir",
        str(out_dir),
    ]
    _run_subprocess(cmd)
    return _load_json(out_dir / "public_repo_eval_summary.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-pool", type=Path, default=Path("data/public_repos/cgcs_seed_pool.jsonl"))
    parser.add_argument("--workspace-manifest", type=Path, default=Path("data/public_repos/workspace_manifest.jsonl"))
    parser.add_argument("--initial-subset", type=Path, default=Path("data/public_repos/pilot/cgcs_pilot_subset.jsonl"))
    parser.add_argument("--pilot-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    parser.add_argument("--ase-report", type=Path, default=Path("reports/ase2026_aegis/complete_public_repo_pilot.md"))
    parser.add_argument("--initial-pilot-size", type=int, default=10)
    parser.add_argument("--target-validated-repos", type=int, default=5)
    parser.add_argument("--max-pilot-size", type=int, default=20)
    parser.add_argument("--max-seeded-tasks", type=int, default=20)
    parser.add_argument("--max-rescue-rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap-mode", choices=("off", "safe"), default="safe")
    parser.add_argument("--skip-build-if-missing", action="store_true")
    parser.add_argument("--strict-output-dir", type=Path, default=Path("data/cgcs"))
    parser.add_argument("--eval-output-dir", type=Path, default=Path("openai_artifacts"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.pilot_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)

    rescue_result = run_rescue_and_expand(
        seed_pool_path=args.seed_pool,
        workspace_manifest=args.workspace_manifest,
        initial_subset_path=args.initial_subset,
        out_dir=args.pilot_dir,
        report_dir=args.report_dir,
        initial_size=args.initial_pilot_size,
        target_validated=args.target_validated_repos,
        max_pilot_size=args.max_pilot_size,
        max_rounds=args.max_rescue_rounds,
        rng_seed=args.seed,
        bootstrap_mode=args.bootstrap_mode,
        skip_build_if_missing=args.skip_build_if_missing,
    )

    validation_path = args.pilot_dir / "workspace_validation.jsonl"
    tasks_summary = generate_tasks(
        validated_path=validation_path,
        out_dir=args.pilot_dir,
        mutations_per_task=1,
        max_tasks=args.max_seeded_tasks,
        seed=args.seed,
        dry_run=False,
        allow_runnable_without_build=True,
    )

    tasks_manifest = args.pilot_dir / "tasks_manifest.jsonl"
    if not tasks_manifest.exists():
        raise SystemExit("Task manifest missing; seeding may have failed.")

    strategies = ["contract_first", "failure_mode_first", "cgcs"]
    pilot_run_summary = run_pilot_benchmark(
        tasks_manifest=tasks_manifest,
        runs_root=args.report_dir / "runs",
        out_dir=args.report_dir,
        strategies=strategies,
        max_tasks=0,
        dry_run=False,
    )

    dataset_summary = run_strict_dataset(runs_root=args.report_dir / "runs", output_dir=args.strict_output_dir)
    if dataset_summary.get("usable_rows", 0) <= 0:
        blocker_report = args.report_dir / "strict_dataset_blocker.md"
        lines = [
            "# Strict Dataset Blocker",
            "",
            f"Usable rows: {dataset_summary.get('usable_rows', 0)}",
            "",
            "Rejection reasons:",
        ]
        for reason, count in sorted(dataset_summary.get("rejection_reasons", {}).items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- {reason}: {count}")
        blocker_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        raise SystemExit("Strict dataset produced 0 usable rows; see strict_dataset_blocker.md for details.")

    eval_summary = build_eval_pack(args.strict_output_dir, args.eval_output_dir)

    complete_summary = {
        "validated_repos": rescue_result.rescue_summary.get("final_validated", 0),
        "runnable_initial": rescue_result.rescue_summary.get("initial_validated", 0),
        "hard_blocked": rescue_result.rescue_summary.get("hard_blocked", 0),
        "tasks_generated": tasks_summary.get("tasks_generated", 0),
        "pilot_runs": pilot_run_summary.get("total_runs", 0),
        "strict_dataset": dataset_summary,
        "eval_pack": eval_summary,
    }
    summary_path = args.pilot_dir / "complete_pilot_summary.json"
    _write_json(summary_path, complete_summary)

    md_lines = [
        "# Complete Public Repo Pilot",
        "",
        f"- Validated repos: {complete_summary['validated_repos']}",
        f"- Seeded tasks: {complete_summary['tasks_generated']}",
        f"- Strategy runs: {complete_summary['pilot_runs']}",
        f"- Strict usable rows: {dataset_summary.get('usable_rows', 0)}",
        f"- Eval items: {eval_summary.get('total_eval_items', 0)}",
    ]
    args.ase_report.parent.mkdir(parents=True, exist_ok=True)
    args.ase_report.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"[pilot-orchestrator] Complete summary → {summary_path}")
    print(f"[pilot-orchestrator] Report → {args.ase_report}")


if __name__ == "__main__":
    main()
