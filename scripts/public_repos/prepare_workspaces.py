#!/usr/bin/env python3
"""Generate workspace manifests and CGCS-ready subsets from repo snapshots."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.public_repos.workspaces import (
    build_workspaces,
    load_snapshots,
    write_cgcs_seed_pool,
    write_workspace_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=Path("data/public_repos/repo_snapshots.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos"))
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshots = load_snapshots(args.snapshots)
    workspaces = build_workspaces(snapshots)
    manifest_path = args.out_dir / "workspace_manifest.jsonl"
    cgcs_seed_path = args.out_dir / "cgcs_seed_pool.jsonl"
    write_workspace_outputs(workspaces, manifest_path)
    write_cgcs_seed_pool(workspaces, cgcs_seed_path, args.confidence_threshold)
    print(f"[public-repos] Workspace manifest contains {len(workspaces)} entries → {manifest_path}")


if __name__ == "__main__":
    main()

