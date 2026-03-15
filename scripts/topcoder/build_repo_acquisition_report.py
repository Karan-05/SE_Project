#!/usr/bin/env python3
"""Aggregate repo acquisition pipeline metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE_ARTIFACT_TYPES = {"git_repo", "git_host_repo_page", "source_archive"}
SUCCESS_FETCH_STATUSES = {"cloned", "updated", "archive_downloaded"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-candidates", type=Path, default=Path("data/topcoder/artifact_candidates.jsonl"))
    parser.add_argument("--candidates", type=Path, default=Path("data/topcoder/repo_candidates.jsonl"))
    parser.add_argument("--fetch-manifest", type=Path, default=Path("data/topcoder/repo_fetch_manifest.jsonl"))
    parser.add_argument("--snapshots", type=Path, default=Path("data/topcoder/repo_snapshots.jsonl"))
    parser.add_argument("--workspaces", type=Path, default=Path("data/topcoder/workspace_manifest.jsonl"))
    parser.add_argument("--json-output", type=Path, default=Path("data/topcoder/source_acquisition_report.json"))
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("reports/ase2026_aegis/source_acquisition_snapshot.md"),
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def build_markdown(report: dict) -> str:
    lines = ["# Topcoder Repo Acquisition Snapshot", ""]
    for section, metrics in report.items():
        lines.append(f"## {section.replace('_', ' ').title()}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| --- | --- |")
        for key, value in metrics.items():
            if isinstance(value, dict):
                value_str = json.dumps(value)
            else:
                value_str = value
            lines.append(f"| {key} | {value_str} |")
        lines.append("")
    lines.append("The report reflects machine-readable manifests only; missing rows indicate upstream stages did not run.")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    artifact_candidates = load_jsonl(args.artifact_candidates)
    candidates = load_jsonl(args.candidates)
    fetch_entries = load_jsonl(args.fetch_manifest)
    snapshots = load_jsonl(args.snapshots)
    workspaces = load_jsonl(args.workspaces)
    artifact_type_counts: dict[str, int] = {}
    artifact_strategy_counts: dict[str, int] = {}
    for entry in artifact_candidates:
        artifact_type = entry.get("artifact_type") or "unknown"
        artifact_type_counts[artifact_type] = artifact_type_counts.get(artifact_type, 0) + 1
        strategy = entry.get("acquisition_strategy") or "unknown"
        artifact_strategy_counts[strategy] = artifact_strategy_counts.get(strategy, 0) + 1
    repo_like_artifacts = sum(artifact_type_counts.get(artifact_type, 0) for artifact_type in SOURCE_ARTIFACT_TYPES)
    artifact_stage = {
        "total_artifact_candidates": len(artifact_candidates),
        "artifact_type_counts": artifact_type_counts,
        "artifact_strategy_counts": artifact_strategy_counts,
        "repo_like_artifact_candidates": repo_like_artifacts,
        "rejected_non_source_candidates": len(artifact_candidates) - repo_like_artifacts,
    }

    repo_keys = {entry.get("normalized_repo_key") for entry in candidates if entry.get("normalized_repo_key")}
    repo_strategy_counts: dict[str, int] = {}
    repo_host_counts: dict[str, int] = {}
    for entry in candidates:
        strategy = entry.get("acquisition_strategy") or "unknown"
        repo_strategy_counts[strategy] = repo_strategy_counts.get(strategy, 0) + 1
        host = entry.get("repo_host") or "unknown"
        repo_host_counts[host] = repo_host_counts.get(host, 0) + 1
    repo_candidate_stage = {
        "repo_candidate_count": len(candidates),
        "unique_repo_candidates": len(repo_keys),
        "strategy_counts": repo_strategy_counts,
        "host_counts": repo_host_counts,
    }

    status_counts: dict[str, int] = {}
    fetch_origin_counts: dict[str, int] = {}
    clone_attempted = 0
    clone_success = 0
    clone_failed = 0
    archive_attempted = 0
    archive_success = 0
    archive_failed = 0
    rejected_count = 0
    for entry in fetch_entries:
        status = entry.get("clone_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        origin = entry.get("source_origin")
        if origin:
            fetch_origin_counts[origin] = fetch_origin_counts.get(origin, 0) + 1
        if status == "rejected":
            rejected_count += 1
            continue
        if status == "dry_run":
            continue
        source_origin = origin or ("clone" if status in {"cloned", "updated"} else "archive")
        if source_origin == "clone":
            clone_attempted += 1
            if status in {"cloned", "updated"}:
                clone_success += 1
            elif status == "failed":
                clone_failed += 1
        if source_origin == "archive":
            archive_attempted += 1
            if status == "archive_downloaded":
                archive_success += 1
            elif status == "failed":
                archive_failed += 1
    fetch_stage = {
        "fetch_manifest_count": len(fetch_entries),
        "clone_attempted_count": clone_attempted,
        "clone_success_count": clone_success,
        "clone_failed_count": clone_failed,
        "archive_download_attempted_count": archive_attempted,
        "archive_download_success_count": archive_success,
        "archive_download_failed_count": archive_failed,
        "rejected_fetch_entries": rejected_count,
        "fetch_status_counts": status_counts,
        "fetch_source_origin_counts": fetch_origin_counts,
    }

    snapshot_origin_counts: dict[str, int] = {}
    runnable_snapshots = 0
    for entry in snapshots:
        if entry.get("likely_runnable"):
            runnable_snapshots += 1
        origin = entry.get("source_origin") or "unknown"
        snapshot_origin_counts[origin] = snapshot_origin_counts.get(origin, 0) + 1
    snapshot_stage = {
        "snapshot_count": len(snapshots),
        "likely_runnable_snapshot_count": runnable_snapshots,
        "snapshot_source_origin_counts": snapshot_origin_counts,
    }

    runnable_workspaces = sum(1 for entry in workspaces if entry.get("runnable_confidence") in {"medium", "high"})
    synthetic_workspaces = sum(1 for entry in workspaces if entry.get("synthetic_workspace"))
    workspace_origin_counts: dict[str, int] = {}
    for entry in workspaces:
        origin = entry.get("source_origin") or "unknown"
        workspace_origin_counts[origin] = workspace_origin_counts.get(origin, 0) + 1
    workspace_stage = {
        "workspace_manifest_count": len(workspaces),
        "likely_runnable_workspace_count": runnable_workspaces,
        "synthetic_workspace_count": synthetic_workspaces,
        "workspace_source_origin_counts": workspace_origin_counts,
    }

    report = {
        "artifact_stage": artifact_stage,
        "repo_candidate_stage": repo_candidate_stage,
        "fetch_stage": fetch_stage,
        "snapshot_stage": snapshot_stage,
        "workspace_stage": workspace_stage,
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    with args.json_output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    markdown = build_markdown(report)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    with args.markdown_output.open("w", encoding="utf-8") as handle:
        handle.write(markdown)
    print(f"Repo acquisition report -> {args.json_output}")
    print(f"Repo acquisition snapshot -> {args.markdown_output}")


if __name__ == "__main__":
    main()
