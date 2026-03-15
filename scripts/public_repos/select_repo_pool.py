#!/usr/bin/env python3
"""Score and select the 100-repo pool for CGCS harness testing."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.public_repos.selection import (
    SelectionConfig,
    build_selection_summary,
    load_candidate_file,
    parse_language_targets,
    select_pool,
    write_selection_outputs,
)
from src.public_repos.utils import normalize_language


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/public_repos/repo_candidates.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos"))
    parser.add_argument("--target-size", type=int, default=100)
    parser.add_argument("--languages", type=str, default="python,javascript,typescript,java")
    parser.add_argument("--per-language-target", type=str, default=None)
    parser.add_argument("--min-stars", type=int, default=20)
    parser.add_argument("--max-stars", type=int, default=None)
    parser.add_argument("--exclude-archived", action="store_true")
    parser.add_argument("--require-tests", action="store_true")
    parser.add_argument("--require-build-files", action="store_true")
    parser.add_argument("--max-per-owner", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def parse_overrides(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    overrides: dict[str, int] = {}
    for part in raw.split(","):
        if ":" not in part:
            continue
        language, value = part.split(":", 1)
        language = normalize_language(language)
        try:
            overrides[language] = int(value)
        except ValueError:
            continue
    return overrides


def parse_language_list(raw: str) -> list[str]:
    return [normalize_language(language.strip()) for language in raw.split(",") if language.strip()]


def main() -> None:
    args = parse_args()
    overrides = parse_overrides(args.per_language_target)
    languages = parse_language_list(args.languages)
    per_language_targets = parse_language_targets(languages, args.target_size, overrides)
    candidates = load_candidate_file(args.input)
    config = SelectionConfig(
        target_size=args.target_size,
        min_stars=args.min_stars,
        max_stars=args.max_stars,
        exclude_archived=args.exclude_archived,
        require_tests=args.require_tests,
        require_build_files=args.require_build_files,
        max_per_owner=args.max_per_owner,
        seed=args.seed,
        languages=languages,
        per_language_targets=per_language_targets,
    )
    selected, filtered, filter_counts = select_pool(candidates, config)
    summary = build_selection_summary(
        input_candidates=candidates,
        filtered_candidates=filtered,
        selected=selected,
        config=config,
        filter_counts=filter_counts,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_selection_outputs(selected, args.out_dir, args.target_size, summary)
    print(f"[public-repos] Selected {len(selected)} repos → {args.out_dir}")


if __name__ == "__main__":
    main()

