#!/usr/bin/env python3
"""Discover public repositories for building the CGCS-ready pool."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.public_repos.discovery import (
    BENCHMARK_MANIFEST_CANDIDATES,
    DiscoveryConfig,
    discover_public_repo_candidates,
)
from src.public_repos.github_client import GitHubClient
from src.public_repos.utils import write_json, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("benchmark_seed", "github_search", "all"), default="all")
    parser.add_argument("--target-size", type=int, default=300)
    parser.add_argument("--languages", type=str, default="python,javascript,typescript,java")
    parser.add_argument("--min-stars", type=int, default=20)
    parser.add_argument("--recent-days", type=int, default=365)
    parser.add_argument("--max-per-owner", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--benchmark-manifest", action="append", dest="benchmark_manifests", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos"))
    parser.add_argument("--github-token-env", type=str, default="GITHUB_TOKEN")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/public_repos/cache"))
    return parser.parse_args()


def parse_languages(value: str) -> list[str]:
    return [language.strip() for language in value.split(",") if language.strip()]


def main() -> None:
    args = parse_args()
    sources = {"benchmark_seed", "github_search"} if args.source == "all" else {args.source}
    languages = parse_languages(args.languages)
    benchmark_manifests = args.benchmark_manifests or BENCHMARK_MANIFEST_CANDIDATES
    token = os.environ.get(args.github_token_env or "")
    client = GitHubClient(token=token, cache_dir=args.cache_dir)
    config = DiscoveryConfig(
        sources=sources,
        min_stars=args.min_stars,
        target_size=args.target_size,
        languages=languages,
        recent_days=args.recent_days,
        max_per_owner=args.max_per_owner,
        seed=args.seed,
    )
    candidates, summary = discover_public_repo_candidates(
        client=client,
        config=config,
        benchmark_manifests=benchmark_manifests,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "repo_candidates.jsonl", (candidate.as_dict() for candidate in candidates))
    write_json(args.out_dir / "repo_candidates_summary.json", summary)
    summary_path = args.out_dir / "repo_candidates_summary.json"
    print(f"[public-repos] Wrote {len(candidates)} candidates → {summary_path}")


if __name__ == "__main__":
    main()
