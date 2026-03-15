#!/usr/bin/env python3
"""Clone the selected public repositories for CGCS harness testing."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.public_repos.fetcher import (
    FetchOptions,
    build_fetch_requests,
    fetch_repositories,
    load_repo_pool,
    write_fetch_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/public_repos/repo_pool_100.jsonl"))
    parser.add_argument("--repo-root", type=Path, default=Path("data/public_repos/repos"))
    parser.add_argument("--manifest", type=Path, default=Path("data/public_repos/repo_fetch_manifest.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/public_repos/repo_fetch_summary.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--retry-count", type=int, default=1)
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--max-repos", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_repo_pool(args.input)
    if args.max_repos is not None:
        records = records[: args.max_repos]
    requests = build_fetch_requests(records, args.repo_root)
    options = FetchOptions(
        dry_run=args.dry_run,
        timeout=args.timeout_seconds,
        retries=args.retry_count,
        validate_remote=not args.skip_validation,
    )
    results = fetch_repositories(requests, options, max_workers=args.max_workers)
    write_fetch_outputs(results, args.manifest, args.summary)
    print(f"[public-repos] Fetch results: {len(results)} entries → {args.manifest}")


if __name__ == "__main__":
    main()

