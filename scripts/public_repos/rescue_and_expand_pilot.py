#!/usr/bin/env python3
"""Rescue fixable pilot repos and backfill replacements until enough validate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from scripts.public_repos.validate_cgcs_workspaces import ValidationSettings

from src.public_repos.pilot.rescue import PilotRescueOrchestrator, PilotRescueResult


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_validation_report(report_path: Path, results: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    lines = [
        "# Public Repo Pilot — Workspace Validation",
        "",
        f"Total repos: {summary.get('total', 0)}",
        f"Runnable: {summary.get('runnable', 0)}",
        f"Runnable without build: {summary.get('runnable_without_build', 0)}",
        "",
        "| Rank | Repo | Verdict | Failure |",
        "|---|---|---|---|",
    ]
    for record in sorted(results, key=lambda r: int(r.get("pilot_rank") or 0)):
        lines.append(
            f"| {record.get('pilot_rank', '-')} | {record.get('repo_key', '')} | {record.get('final_verdict', '')} | {record.get('failure_category', '')} |"
        )
    _write_markdown(report_path, lines)


def _write_rescue_debug(report_path: Path, result: PilotRescueResult) -> None:
    lines = [
        "# Public Repo Pilot — Rescue Summary",
        "",
        f"- Final validated repos: {result.rescue_summary.get('final_validated', 0)}",
        f"- Initial validated before rescue: {result.rescue_summary.get('initial_validated', 0)}",
        f"- Hard-blocked repos: {result.rescue_summary.get('hard_blocked', 0)}",
        "",
        "## Rescue counts",
        "| Action | Count |",
        "|---|---|",
    ]
    rescue_counts = result.rescue_summary.get("rescue_counts", {})
    if rescue_counts:
        for action, count in sorted(rescue_counts.items()):
            lines.append(f"| {action} | {count} |")
    else:
        lines.append("| (none) | 0 |")
    if result.hard_blocked_repos:
        lines += [
            "",
            "## Hard-blocked repos",
        ]
        for repo in result.hard_blocked_repos:
            lines.append(f"- {repo}")
    _write_markdown(report_path, lines)


def _write_expansion_debug(report_path: Path, result: PilotRescueResult) -> None:
    lines = [
        "# Public Repo Pilot — Expansion Summary",
        "",
        f"- Replacements added: {result.expansion_summary.get('replacements_added', 0)}",
        f"- Current subset size: {result.expansion_summary.get('current_subset_size', 0)}",
        "",
        "## Replacement log",
        "| Round | Repo | Reason |",
        "|---|---|---|",
    ]
    if result.expansion_log:
        for entry in result.expansion_log:
            lines.append(
                f"| {entry.get('pilot_round', '-')} | {entry.get('repo_key', '')} | {entry.get('reason', '')} |"
            )
    else:
        lines.append("| - | (none) | - |")
    _write_markdown(report_path, lines)


def run_rescue_and_expand(
    *,
    seed_pool_path: Path,
    workspace_manifest: Path,
    initial_subset_path: Path,
    out_dir: Path,
    report_dir: Path,
    initial_size: int,
    target_validated: int,
    max_pilot_size: int,
    max_rounds: int,
    rng_seed: int,
    bootstrap_mode: str,
    skip_build_if_missing: bool,
) -> PilotRescueResult:
    seed_pool = _load_jsonl(seed_pool_path)
    manifest_entries = _load_jsonl(workspace_manifest)
    initial_subset = _load_jsonl(initial_subset_path)

    settings = ValidationSettings(
        bootstrap_mode=bootstrap_mode,
        skip_build_if_missing=skip_build_if_missing,
        skip_install_if_prepared=False,
        timeout_seconds=240.0,
    )

    orchestrator = PilotRescueOrchestrator(
        seed_pool=seed_pool,
        manifest_entries=manifest_entries,
        initial_subset=initial_subset,
        initial_size=initial_size,
        target_validated=target_validated,
        max_pilot_size=max_pilot_size,
        max_rounds=max_rounds,
        rng_seed=rng_seed,
        validation_settings=settings,
    )
    result = orchestrator.run()

    validation_path = out_dir / "workspace_validation.jsonl"
    _write_jsonl(validation_path, result.validation_results)
    validation_summary_path = out_dir / "workspace_validation_summary.json"
    _write_json(validation_summary_path, result.validation_summary)

    attempt_log_path = out_dir / "pilot_attempt_log.jsonl"
    _write_jsonl(attempt_log_path, result.attempt_log)
    _write_json(out_dir / "pilot_rescue_summary.json", result.rescue_summary)
    _write_json(out_dir / "pilot_expansion_summary.json", result.expansion_summary)
    _write_jsonl(out_dir / "pilot_active_subset.jsonl", result.current_subset)

    _write_rescue_debug(report_dir / "rescue_debug.md", result)
    _write_expansion_debug(report_dir / "expansion_debug.md", result)
    print(f"[pilot-rescue] Validation → {validation_path}")
    print(f"[pilot-rescue] Attempt log → {attempt_log_path}")
    print(f"[pilot-rescue] Rescue summary → {report_dir / 'rescue_debug.md'}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-pool", type=Path, default=Path("data/public_repos/cgcs_seed_pool.jsonl"))
    parser.add_argument("--workspace-manifest", type=Path, default=Path("data/public_repos/workspace_manifest.jsonl"))
    parser.add_argument("--initial-subset", type=Path, default=Path("data/public_repos/pilot/cgcs_pilot_subset.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/decomposition/public_repo_pilot"))
    parser.add_argument("--initial-pilot-size", type=int, default=10)
    parser.add_argument("--target-validated-repos", type=int, default=5)
    parser.add_argument("--max-pilot-size", type=int, default=20)
    parser.add_argument("--max-rescue-rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap-mode", choices=("off", "safe"), default="safe")
    parser.add_argument("--skip-build-if-missing", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_rescue_and_expand(
        seed_pool_path=args.seed_pool,
        workspace_manifest=args.workspace_manifest,
        initial_subset_path=args.initial_subset,
        out_dir=args.out_dir,
        report_dir=args.report_dir,
        initial_size=args.initial_pilot_size,
        target_validated=args.target_validated_repos,
        max_pilot_size=args.max_pilot_size,
        max_rounds=args.max_rescue_rounds,
        rng_seed=args.seed,
        bootstrap_mode=args.bootstrap_mode,
        skip_build_if_missing=args.skip_build_if_missing,
    )


if __name__ == "__main__":
    main()
