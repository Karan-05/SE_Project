#!/usr/bin/env python3
"""Select a runnable Topcoder subset for CGCS repair experiments."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import load_jsonl, write_jsonl  # noqa: E402

DEFAULT_TRACKS = ("development", "qa", "quality assurance")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter the Topcoder corpus to runnable challenges.")
    parser.add_argument(
        "--index-file",
        "--input",
        dest="index_file",
        type=Path,
        default=Path("data/topcoder/corpus_index.jsonl"),
        help="Path to corpus_index.jsonl",
    )
    parser.add_argument("--output", type=Path, default=Path("data/topcoder/executable_subset.jsonl"))
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/topcoder/executable_subset_summary.json"),
    )
    parser.add_argument(
        "--rejections-output",
        type=Path,
        default=Path("data/topcoder/executable_subset_rejections.jsonl"),
    )
    parser.add_argument(
        "--min-submissions",
        type=int,
        default=1,
        help="Require at least this many submissions (0=disable).",
    )
    parser.add_argument(
        "--min-prize",
        type=float,
        default=0.0,
        help="Minimum prize in USD (0 to disable).",
    )
    parser.add_argument(
        "--require-tests",
        dest="require_tests",
        action="store_true",
        default=True,
        help="Require task to mention tests (default).",
    )
    parser.add_argument(
        "--allow-missing-tests",
        dest="require_tests",
        action="store_false",
        help="Allow challenges without explicit test signals.",
    )
    parser.add_argument(
        "--tracks",
        nargs="*",
        default=list(DEFAULT_TRACKS),
        help="Allowed tracks (default Development/QA). Empty list disables track filtering.",
    )
    parser.add_argument(
        "--include-technologies",
        nargs="*",
        default=None,
        help="Require at least one of these technologies (case-insensitive).",
    )
    parser.add_argument(
        "--include-tags",
        nargs="*",
        default=None,
        help="Require at least one of these tags.",
    )
    parser.add_argument(
        "--posted-after",
        type=str,
        default="",
        help="ISO timestamp (YYYY-MM-DD) to require posted_time >= value.",
    )
    return parser.parse_args()


def _to_lower_set(values: Optional[Sequence[str]]) -> Set[str]:
    if not values:
        return set()
    return {v.strip().lower() for v in values if v and v.strip()}


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _coerce_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _has_intersection(values: Sequence[str] | None, allowed: Set[str]) -> bool:
    if not allowed or not values:
        return True
    lowered = {str(v).strip().lower() for v in values if str(v).strip()}
    return bool(lowered & allowed)


def _evaluate_record(
    record: Dict[str, Any],
    *,
    min_submissions: int,
    min_prize: float,
    require_tests: bool,
    allowed_tracks: Set[str],
    tech_filter: Set[str],
    tag_filter: Set[str],
    posted_after: Optional[datetime],
) -> List[str]:
    reasons: List[str] = []
    if not record.get("has_repo"):
        reasons.append("missing_repo")
    if require_tests and not record.get("has_tests"):
        reasons.append("missing_test_signal")
    if not record.get("likely_executable"):
        reasons.append("weak_executable_signal")
    submissions = _coerce_int(record.get("num_submissions"))
    if min_submissions and submissions < min_submissions:
        reasons.append("weak_executable_signal")
    prize = _coerce_float(record.get("prize"))
    if min_prize and prize < min_prize:
        reasons.append("prize_filter")
    track = str(record.get("track") or "").strip().lower()
    if allowed_tracks and track and track not in allowed_tracks:
        reasons.append("track_filter")
    if not _has_intersection(record.get("technologies"), tech_filter):
        reasons.append("technology_filter")
    if not _has_intersection(record.get("tags"), tag_filter):
        reasons.append("tag_filter")
    if posted_after:
        posted_time = _parse_timestamp(record.get("posted_time"))
        if not posted_time or posted_time < posted_after:
            reasons.append("date_filter")
    return reasons


def select_subset(args: argparse.Namespace) -> Dict[str, Any]:
    rows = load_jsonl(args.index_file)
    seen_ids: Set[str] = set()
    seen_groups: Set[str] = set()
    subset: List[Dict[str, Any]] = []
    rejections: List[Dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    allowed_tracks = _to_lower_set(args.tracks)
    tech_filter = _to_lower_set(args.include_technologies)
    tag_filter = _to_lower_set(args.include_tags)
    posted_after = _parse_timestamp(args.posted_after) if args.posted_after else None

    for row in rows:
        challenge_id = str(row.get("challenge_id") or row.get("task_id") or "").strip()
        if not challenge_id or challenge_id in seen_ids:
            continue
        reasons = _evaluate_record(
            row,
            min_submissions=args.min_submissions,
            min_prize=args.min_prize,
            require_tests=args.require_tests,
            allowed_tracks=allowed_tracks,
            tech_filter=tech_filter,
            tag_filter=tag_filter,
            posted_after=posted_after,
        )
        dup_key = str(row.get("duplicate_group_key") or "").strip()
        if dup_key and dup_key in seen_groups:
            reasons.append("duplicate")
        if reasons:
            for reason in reasons:
                rejection_counts[reason] += 1
            rejections.append(
                {
                    "challenge_id": challenge_id,
                    "title": row.get("title"),
                    "reasons": reasons,
                }
            )
            continue
        if dup_key:
            seen_groups.add(dup_key)
        subset.append(row)
        seen_ids.add(challenge_id)

    write_jsonl(args.output, subset)
    write_jsonl(args.rejections_output, rejections)
    summary = {
        "input_rows": len(rows),
        "selected_rows": len(subset),
        "rejections": dict(rejection_counts),
        "filters": {
            "min_submissions": args.min_submissions,
            "min_prize": args.min_prize,
            "require_tests": args.require_tests,
            "tracks": sorted(allowed_tracks) if allowed_tracks else [],
            "technologies": sorted(tech_filter),
            "tags": sorted(tag_filter),
            "posted_after": args.posted_after,
        },
        "output_file": str(args.output),
        "rejections_file": str(args.rejections_output),
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        "Executable subset built | "
        f"selected={len(subset)} | rejected={sum(rejection_counts.values())} | "
        f"output={args.output}"
    )
    return summary


def main() -> None:
    args = parse_args()
    select_subset(args)


if __name__ == "__main__":
    main()
