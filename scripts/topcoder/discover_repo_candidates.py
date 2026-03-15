#!/usr/bin/env python3
"""Discover repository candidates for Topcoder challenges."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Iterator

from src.decomposition.topcoder.discovery import (
    discover_artifact_candidates,
    filter_repo_candidates,
    iter_all_records,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=Path("data/raw/tasks.csv"))
    parser.add_argument("--pages-glob", action="append", default=None)
    parser.add_argument("--challenge-data-glob", action="append", default=None)
    parser.add_argument("--corpus-index", type=Path, default=Path("data/topcoder/corpus_index.jsonl"))
    parser.add_argument("--artifact-output", type=Path, default=Path("data/topcoder/artifact_candidates.jsonl"))
    parser.add_argument("--artifact-summary", type=Path, default=Path("data/topcoder/artifact_candidates_summary.json"))
    parser.add_argument("--output", type=Path, default=Path("data/topcoder/repo_candidates.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/topcoder/repo_candidates_summary.json"))
    parser.add_argument("--min-confidence", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--challenge-id", action="append", default=None, help="Limit to specific challenge IDs.")
    return parser.parse_args()


def _limited_records(iterator: Iterator, limit: int | None) -> Iterable:
    if limit is None:
        return iterator
    import itertools

    return itertools.islice(iterator, limit)


def main() -> None:
    args = parse_args()
    records = iter_all_records(
        tasks_csv=args.tasks,
        page_globs=args.pages_glob,
        challenge_data_globs=args.challenge_data_glob,
        corpus_index=args.corpus_index,
    )
    allowed_ids = {value.strip() for value in (args.challenge_id or []) if value and value.strip()}

    def filtered_records():
        for record in _limited_records(records, args.max_records):
            if allowed_ids and record.challenge_id not in allowed_ids:
                continue
            yield record

    artifacts, artifact_summary = discover_artifact_candidates(filtered_records())
    repo_candidates, repo_summary = filter_repo_candidates(
        artifacts,
        min_confidence=args.min_confidence,
    )
    args.artifact_output.parent.mkdir(parents=True, exist_ok=True)
    with args.artifact_output.open("w", encoding="utf-8") as handle:
        for artifact in artifacts:
            handle.write(json.dumps(artifact.to_dict()) + "\n")
    artifact_summary_dict = artifact_summary.to_dict()
    artifact_summary_dict["challenge_filter_count"] = len(allowed_ids)
    artifact_summary_dict["records_after_filter"] = artifact_summary.records_scanned
    args.artifact_summary.parent.mkdir(parents=True, exist_ok=True)
    with args.artifact_summary.open("w", encoding="utf-8") as handle:
        json.dump(artifact_summary_dict, handle, indent=2)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for candidate in repo_candidates:
            handle.write(json.dumps(candidate.to_dict()) + "\n")
    summary_dict = repo_summary.to_dict()
    summary_dict["output_candidates"] = len(repo_candidates)
    summary_dict["challenge_filter_count"] = len(allowed_ids)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    with args.summary.open("w", encoding="utf-8") as handle:
        json.dump(summary_dict, handle, indent=2)
    print(f"Artifact candidate manifest -> {args.artifact_output}")
    print(f"Artifact candidate summary -> {args.artifact_summary}")
    print(f"Repo candidate manifest -> {args.output}")
    print(f"Repo candidate summary -> {args.summary}")


if __name__ == "__main__":
    main()
