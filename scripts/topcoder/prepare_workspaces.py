#!/usr/bin/env python3
"""Prepare workspace manifests for Topcoder repository snapshots."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import List

from src.decomposition.topcoder.workspaces import WorkspaceManifestEntry, infer_workspace_commands


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=Path("data/topcoder/repo_snapshots.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/topcoder/workspace_manifest.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/topcoder/workspace_summary.json"))
    parser.add_argument("--run-install", action="store_true", help="Optionally run install commands (default: disabled).")
    parser.add_argument("--install-timeout", type=int, default=900)
    parser.add_argument("--max-workspaces", type=int, default=None)
    return parser.parse_args()


def load_snapshots(path: Path, limit: int | None) -> List[dict]:
    entries: List[dict] = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if limit is not None and idx >= limit:
                break
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def maybe_run_install(entry: WorkspaceManifestEntry, timeout: int) -> WorkspaceManifestEntry:
    if not entry.install_command:
        entry.notes = ";".join(filter(None, [entry.notes, "no_install_command"]))
        return entry
    try:
        subprocess.run(
            entry.install_command,
            shell=True,
            check=True,
            cwd=entry.local_path,
            timeout=timeout,
        )
        entry.prep_status = "install_completed"
    except subprocess.CalledProcessError as exc:
        entry.prep_status = "install_failed"
        entry.prep_error = f"install_failed:{exc.returncode}"
    except subprocess.TimeoutExpired:
        entry.prep_status = "install_failed"
        entry.prep_error = "install_timeout"
    return entry


def main() -> None:
    args = parse_args()
    snapshots = load_snapshots(args.snapshots, args.max_workspaces)
    manifests: List[WorkspaceManifestEntry] = []
    confidence_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    synthetic_count = 0
    for snapshot in snapshots:
        manifest = infer_workspace_commands(snapshot)
        if args.run_install:
            manifest = maybe_run_install(manifest, args.install_timeout)
        manifests.append(manifest)
        confidence_counts[manifest.runnable_confidence] = confidence_counts.get(manifest.runnable_confidence, 0) + 1
        status_counts[manifest.prep_status] = status_counts.get(manifest.prep_status, 0) + 1
        origin_counts[manifest.source_origin] = origin_counts.get(manifest.source_origin, 0) + 1
        if manifest.synthetic_workspace:
            synthetic_count += 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for manifest in manifests:
            handle.write(json.dumps(manifest.to_dict()) + "\n")
    summary = {
        "workspace_count": len(manifests),
        "runnable_confidence": confidence_counts,
        "prep_status_counts": status_counts,
        "install_attempted": args.run_install,
        "source_origin_counts": origin_counts,
        "synthetic_workspace_count": synthetic_count,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with args.summary.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"Workspace manifest -> {args.output}")
    print(f"Workspace summary -> {args.summary}")


if __name__ == "__main__":
    main()
