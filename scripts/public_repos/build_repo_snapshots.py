#!/usr/bin/env python3
"""Inspect cloned repositories and capture build/test/language metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.public_repos.snapshots import build_snapshots, load_fetch_manifest, write_snapshot_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-manifest", type=Path, default=Path("data/public_repos/repo_fetch_manifest.jsonl"))
    parser.add_argument("--repo-root", type=Path, default=Path("data/public_repos/repos"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos"))
    parser.add_argument("--max-files", type=int, default=4000)
    parser.add_argument("--max-repos", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_records = load_fetch_manifest(args.fetch_manifest)
    if args.max_repos is not None:
        manifest_records = manifest_records[: args.max_repos]
    snapshots = build_snapshots(manifest_records, args.repo_root, args.max_files)
    out_path = args.out_dir / "repo_snapshots.jsonl"
    summary_path = args.out_dir / "repo_snapshots_summary.json"
    write_snapshot_outputs(snapshots, out_path, summary_path)
    print(f"[public-repos] Snapshots generated for {len(snapshots)} repos → {out_path}")


if __name__ == "__main__":
    main()

