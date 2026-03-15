#!/usr/bin/env python3
"""Aggregate Topcoder funnel metrics into machine-readable reports."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import load_jsonl  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Topcoder funnel report.")
    parser.add_argument("--tasks-csv", type=Path, default=Path("data/raw/tasks.csv"))
    parser.add_argument("--corpus-index", type=Path, default=Path("data/topcoder/corpus_index.jsonl"))
    parser.add_argument(
        "--executable-subset",
        type=Path,
        default=Path("data/topcoder/executable_subset.jsonl"),
    )
    parser.add_argument("--cgcs-dir", type=Path, default=Path("data/cgcs"))
    parser.add_argument(
        "--eval-items",
        type=Path,
        default=Path("openai_artifacts/eval_items_test.jsonl"),
    )
    parser.add_argument(
        "--batch-requests",
        type=Path,
        default=Path("openai_artifacts/batch_requests.jsonl"),
    )
    parser.add_argument(
        "--skipped-eval",
        type=Path,
        default=Path("openai_artifacts/skipped_eval_items.jsonl"),
    )
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=Path("openai_artifacts/normalized"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("data/topcoder/funnel_report.json"),
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=Path("reports/ase2026_aegis/funnel_snapshot.md"),
    )
    return parser.parse_args()


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        count = sum(1 for _ in reader)
    return max(0, count - 1)


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return len(load_jsonl(path))


def _count_cgcs_rows(cgcs_dir: Path) -> int:
    total = 0
    for split in ("train", "dev", "test"):
        total += _count_jsonl(cgcs_dir / f"{split}.jsonl")
    return total


def _rejection_counts(path: Path, field: str) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return {}
    for row in load_jsonl(path):
        for reason in row.get(field, []) or []:
            counts[str(reason)] += 1
    return dict(counts)


def _top_batch_errors(normalized_dir: Path) -> Dict[str, int]:
    errors_path = normalized_dir / "latest_errors.jsonl"
    if not errors_path.exists():
        return {}
    counts: Counter[str] = Counter()
    for row in load_jsonl(errors_path):
        counts[row.get("error_code", "unknown")] += 1
    return dict(counts)


def _batch_success_count(normalized_dir: Path) -> int:
    latest = normalized_dir / "latest.jsonl"
    return _count_jsonl(latest)


def _solved_count(normalized_dir: Path) -> int:
    latest = normalized_dir / "latest.jsonl"
    if not latest.exists():
        return 0
    solved = 0
    for row in load_jsonl(latest):
        payload = row.get("payload") or {}
        if isinstance(payload, dict) and payload.get("status") in {"solved", "success"}:
            solved += 1
    return solved


def _skipped_eval_counts(path: Path) -> Dict[str, int]:
    if not path.exists():
        return {}
    counter: Counter[str] = Counter()
    for row in load_jsonl(path):
        counter[row.get("reason", "unknown")] += 1
    return dict(counter)


def _write_markdown(path: Path, stages: Dict[str, int], details: Dict[str, Dict[str, int]]) -> None:
    lines: List[str] = [
        "# Topcoder Funnel Snapshot",
        "",
        "| Stage | Count |",
        "| --- | ---: |",
    ]
    for label, value in stages.items():
        lines.append(f"| {label} | {value} |")
    lines.append("")
    if details.get("cgcs_rejections"):
        lines.append("## CGCS rejection reasons")
        for reason, count in sorted(details["cgcs_rejections"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- **{reason}**: {count}")
        lines.append("")
    if details.get("skipped_eval_items"):
        lines.append("## Skipped eval items")
        for reason, count in sorted(details["skipped_eval_items"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- **{reason}**: {count}")
        lines.append("")
    if details.get("batch_errors"):
        lines.append("## Batch error codes")
        for reason, count in sorted(details["batch_errors"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- **{reason}**: {count}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    raw_count = _count_csv_rows(args.tasks_csv)
    index_count = _count_jsonl(args.corpus_index)
    likely_executable = 0
    for row in load_jsonl(args.corpus_index):
        if row.get("likely_executable"):
            likely_executable += 1
    subset_count = _count_jsonl(args.executable_subset)
    cgcs_rows = _count_cgcs_rows(args.cgcs_dir)
    eval_count = _count_jsonl(args.eval_items)
    batch_request_count = _count_jsonl(args.batch_requests)
    batch_success = _batch_success_count(args.normalized_dir)
    solved = _solved_count(args.normalized_dir)
    skipped_eval = _skipped_eval_counts(args.skipped_eval)
    cgcs_rejections = _rejection_counts(args.cgcs_dir / "rejected.jsonl", "row_errors")
    batch_errors = _top_batch_errors(args.normalized_dir)

    stages = {
        "raw_corpus_count": raw_count,
        "indexed_count": index_count,
        "likely_executable_count": likely_executable,
        "executable_subset_count": subset_count,
        "usable_cgcs_row_count": cgcs_rows,
        "eval_item_count": eval_count,
        "batch_request_count": batch_request_count,
        "batch_success_count": batch_success,
        "solved_count": solved,
    }
    details = {
        "cgcs_rejections": cgcs_rejections,
        "skipped_eval_items": skipped_eval,
        "batch_errors": batch_errors,
    }
    payload = {
        "stages": stages,
        "details": details,
        "paths": {
            "corpus_index": str(args.corpus_index),
            "executable_subset": str(args.executable_subset),
            "cgcs_dir": str(args.cgcs_dir),
            "eval_items": str(args.eval_items),
            "batch_requests": str(args.batch_requests),
            "normalized_dir": str(args.normalized_dir),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(args.output_markdown, stages, details)
    print(f"Funnel report saved to {args.output_json} and {args.output_markdown}")
    return payload


def main() -> None:
    args = parse_args()
    build_report(args)


if __name__ == "__main__":
    main()
