#!/usr/bin/env python3
"""Run a tiny deterministic subset of CGCS real-repo tasks to validate trace quality."""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from src.config import PathConfig
from src.decomposition.runners.run_real_repo_benchmark import BenchmarkPaths, run_real_repo_benchmark


def _load_challenge_manifest(path: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    if not path.exists():
        raise FileNotFoundError(f"Input manifest {path} not found.")
    if path.suffix in {".jsonl", ".jsonlines"}:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                records.append(json.loads(stripped))
    else:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            if isinstance(payload, list):
                records.extend(payload)
            elif isinstance(payload, dict):
                records.append(payload)
    return records


def _build_challenge_index(task_roots: Iterable[Path]) -> Dict[str, Tuple[Path, str]]:
    index: Dict[str, Tuple[Path, str]] = {}
    for root in task_roots:
        if not root.exists():
            continue
        manifests: List[Path] = []
        if root.is_file():
            if root.name == "task.json":
                manifests = [root]
        else:
            manifests = sorted(root.rglob("task.json"))
        for manifest in manifests:
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            metadata = data.get("metadata") or {}
            challenge_id = metadata.get("challenge_id") or data.get("dataset_source") or manifest.parent.name
            task_id = data.get("task_id") or manifest.parent.name
            if challenge_id and task_id:
                index[str(challenge_id)] = (manifest.parent, str(task_id))
    return index


def _select_task_dirs(
    manifest: List[Dict[str, object]],
    challenge_index: Dict[str, Tuple[Path, str]],
    max_tasks: int,
    seed: int,
) -> List[Tuple[Path, str]]:
    candidates = [entry for entry in manifest if entry.get("challenge_id") in challenge_index]
    if not candidates:
        return []
    rng = random.Random(seed)
    rng.shuffle(candidates)
    selected_dirs: List[Tuple[Path, str]] = []
    for entry in candidates:
        challenge_id = str(entry.get("challenge_id"))
        path = challenge_index.get(challenge_id)
        if not path:
            continue
        selected_dirs.append(path)
        if len(selected_dirs) >= max_tasks:
            break
    return selected_dirs


def _summarize_traces(trace_root: Path, strategy: str, task_ids: Iterable[str]) -> Dict[str, int]:
    stats = {
        "total_rounds": 0,
        "rounds_with_contract_items": 0,
        "rounds_with_active_clause_id": 0,
        "rounds_with_witnesses": 0,
        "rounds_with_raw_payload": 0,
        "rounds_with_candidate_files": 0,
    }
    strategy_dir = trace_root / strategy
    for task_id in task_ids:
        trace_path = strategy_dir / f"{task_id}.json"
        if not trace_path.exists():
            continue
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
        for round_entry in payload.get("rounds", []):
            stats["total_rounds"] += 1
            edit_meta = round_entry.get("edit_metadata") or {}
            cgcs_state = edit_meta.get("cgcs_state") or {}
            contract_items = cgcs_state.get("contract_items") or edit_meta.get("contract_items") or []
            if contract_items:
                stats["rounds_with_contract_items"] += 1
            active_clause = (
                edit_meta.get("active_clause_id")
                or cgcs_state.get("active_clause_id")
                or cgcs_state.get("active_clause")
                or ""
            )
            if active_clause:
                stats["rounds_with_active_clause_id"] += 1
            witnesses = edit_meta.get("witnesses") or cgcs_state.get("witnesses") or []
            if witnesses:
                stats["rounds_with_witnesses"] += 1
            raw_payload = edit_meta.get("raw_edit_payload") or ""
            if str(raw_payload).strip():
                stats["rounds_with_raw_payload"] += 1
            candidate_files = edit_meta.get("candidate_files") or cgcs_state.get("candidate_files") or []
            if candidate_files:
                stats["rounds_with_candidate_files"] += 1
    return stats


def _configure_paths(output_dir: Path) -> BenchmarkPaths:
    paths = BenchmarkPaths("real_world_research")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths.root = output_dir
    paths.run_root = output_dir / "runs"
    paths.run_root.mkdir(parents=True, exist_ok=True)
    paths.csv = output_dir / "strategy_comparison.csv"
    paths.case_md = output_dir / "case_studies.md"
    paths.summary_md = output_dir / "summary.md"
    paths.preflight_json = output_dir / "preflight_report.json"
    paths.preflight_md = output_dir / "preflight_report.md"
    return paths


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Run a tiny CGCS subset to validate trace quality.")
    parser.add_argument("--input", type=Path, required=True, help="JSON/JSONL manifest of executable challenges.")
    parser.add_argument("--max-tasks", type=int, default=10, help="Maximum tasks to run.")
    parser.add_argument("--strategies", type=str, default="cgcs", help="Comma-separated strategy list.")
    parser.add_argument(
        "--task-root",
        action="append",
        type=Path,
        default=[],
        help="Directory containing repo task manifests (default: Topcoder pack).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PathConfig().reports_root / "decomposition" / "real_world" / "real_repo_tiny",
        help="Where to store run logs and traces.",
    )
    parser.add_argument("--seed", type=int, default=0, help="Deterministic seed for subset selection.")
    args = parser.parse_args()

    manifest = _load_challenge_manifest(args.input)
    task_roots = args.task_root or [PathConfig().experiments_dir / "real_repo_tasks" / "topcoder"]
    challenge_index = _build_challenge_index(task_roots)
    selected = _select_task_dirs(manifest, challenge_index, args.max_tasks, args.seed)
    if not selected:
        raise RuntimeError("No executable tasks from the manifest matched available repo tasks.")
    strategies = [token.strip() for token in args.strategies.split(",") if token.strip()]
    trace_dir = args.output_dir / "traces"
    os.environ["DECOMP_TRACE_DIR"] = str(trace_dir)
    os.environ["DECOMP_STORE_TRACES"] = "1"
    paths = _configure_paths(args.output_dir)
    run_real_repo_benchmark(
        [path for path, _ in selected],
        strategies=strategies,
        mode="real_world_research",
        paths=paths,
        include_oracle=False,
        max_tasks=len(selected),
    )
    task_ids = [task_id for _, task_id in selected]
    stats = _summarize_traces(trace_dir, strategies[0], task_ids)
    print(f"total_tasks_run={len(task_ids)}")
    for key, value in stats.items():
        print(f"{key}={value}")


if __name__ == "__main__":  # pragma: no cover
    main()
