"""Convert normalized challenge JSON into data/raw tables for the research stack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _iter_challenge_payloads(challenge_paths: Iterable[Path]) -> Iterable[Dict[str, Any]]:
    seen_ids: Dict[str, Dict[str, Any]] = {}
    for base in challenge_paths:
        if base.is_file() and base.suffix == ".json":
            files = [base]
        else:
            files = sorted(base.glob("challengeData_*/*.json"))
        for json_path in files:
            with json_path.open("r", encoding="utf-8") as fh:
                try:
                    payload = json.load(fh)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Failed to parse {json_path}: {exc}") from exc
            for record in payload:
                challenge_id = record.get("challengeId") or record.get("id")
                if not challenge_id:
                    continue
                seen_ids[challenge_id] = record
    return seen_ids.values()


def _to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    try:
        text = str(value).strip()
        if not text:
            return default
        return int(float(text))
    except ValueError:
        return default


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in (DATE_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _skill_vector(worker_id: str, dimensions: int = 8) -> str:
    digest = hashlib.sha256(worker_id.encode("utf-8")).digest()
    values: List[str] = []
    for idx in range(dimensions):
        chunk = digest[idx] / 255.0  # 0-1
        value = (chunk * 2.0) - 1.0
        values.append(f"{value:.3f}")
    return ";".join(values)


def _split_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def _challenge_status_flags(status: Optional[str], submissions: int, registrants: int) -> Tuple[int, int, int]:
    normalized = (status or "").lower()
    has_winner = 1 if submissions > 0 or "completed" in normalized else 0
    starved = 1 if submissions == 0 else 0
    dropped = 1 if registrants > 0 and submissions == 0 else 0
    return has_winner, starved, dropped


def export_real_tables(
    challenge_dirs: List[Path],
    output_dir: Path,
    *,
    registrant_cap: int = 200,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks_rows: List[Dict[str, Any]] = []
    interactions_rows: List[Dict[str, Any]] = []
    worker_profiles: Dict[str, Dict[str, Any]] = {}
    worker_tags: Dict[str, set[str]] = defaultdict(set)
    worker_counter = 0

    def next_worker_id() -> str:
        nonlocal worker_counter
        worker_counter += 1
        return f"legacy_worker_{worker_counter:06d}"

    for challenge in _iter_challenge_payloads(challenge_dirs):
        challenge_id = challenge.get("challengeId")
        if not challenge_id:
            continue
        name = challenge.get("name") or "Topcoder Challenge"
        description = challenge.get("description") or ""
        tags = challenge.get("technologies") or ""
        tag_list = _split_tags(tags)
        prize = float(_to_int(challenge.get("totalPrizeCost")))
        track = challenge.get("trackType") or "Development"
        company = str(challenge.get("directProjectId") or "Topcoder")
        posted_time = _parse_datetime(
            challenge.get("registrationStartDate") or challenge.get("submissionStartDate") or challenge.get("startDate")
        )
        deadline = _parse_datetime(
            challenge.get("submissionEndDate")
            or challenge.get("registrationEndDate")
            or challenge.get("endDate")
            or challenge.get("startDate")
        )
        if posted_time and deadline and deadline < posted_time:
            deadline = posted_time + timedelta(days=5)
        if not posted_time and deadline:
            posted_time = deadline - timedelta(days=5)
        if not posted_time:
            posted_time = datetime(2015, 1, 1)
        if not deadline:
            deadline = posted_time + timedelta(days=7)

        duration_days = max(0, int((deadline - posted_time).days))
        registrants = _to_int(challenge.get("numOfRegistrants"))
        submissions = _to_int(challenge.get("numOfSubmissions"))
        winner_handles = [token for token in _split_tags(challenge.get("winners")) if token]
        registrants = max(registrants, submissions, len(winner_handles))
        registrants = min(registrants, registrant_cap)
        has_winner, starved, dropped = _challenge_status_flags(challenge.get("status"), submissions, registrants)
        failed = 1 if "cancelled" in (challenge.get("status") or "").lower() else 0
        winning_score = 100.0 if submissions > 0 else 0.0

        tasks_rows.append(
            {
                "task_id": challenge_id,
                "title": name,
                "description": description,
                "tags": tags,
                "tech_stack": tags,
                "prize": prize,
                "difficulty": 3 if prize < 1500 else 4 if prize > 5000 else 2,
                "duration": duration_days,
                "posted_time": _format_timestamp(posted_time),
                "deadline": _format_timestamp(deadline),
                "platform": "Topcoder",
                "track": track or "Unknown",
                "company": company,
                "num_registrants": registrants,
                "num_submissions": submissions,
                "has_winner": has_winner,
                "starved": starved,
                "dropped": dropped,
                "failed": failed,
                "winning_score": winning_score,
            }
        )

        # Build interactions (synthetic registrants + submissions)
        worker_ids: List[str] = []
        for handle in winner_handles[:registrants]:
            if handle not in worker_profiles:
                worker_profiles[handle] = {
                    "worker_id": handle,
                    "skill_vector": _skill_vector(handle),
                    "past_tasks_count": 0,
                    "past_wins": 0,
                }
            worker_ids.append(handle)

        while len(worker_ids) < registrants:
            worker_ids.append(next_worker_id())

        timestamp = posted_time
        for idx, worker_id in enumerate(worker_ids):
            submitted = 1 if idx < submissions else 0
            scored = submitted
            rank = idx + 1 if submitted else 0
            interactions_rows.append(
                {
                    "worker_id": worker_id,
                    "task_id": challenge_id,
                    "registered": 1,
                    "submitted": submitted,
                    "scored": scored,
                    "score": 100.0 - idx if submitted else 0.0,
                    "rank": rank,
                    "timestamp": _format_timestamp(timestamp + timedelta(hours=idx)),
                }
            )

            profile = worker_profiles.setdefault(
                worker_id,
                {
                    "worker_id": worker_id,
                    "skill_vector": _skill_vector(worker_id),
                    "past_tasks_count": 0,
                    "past_wins": 0,
                },
            )
            profile["past_tasks_count"] += 1
            if submitted and rank == 1:
                profile["past_wins"] += 1
            worker_tags[worker_id].update(tag_list)

    workers_rows = []
    for worker_id, profile in worker_profiles.items():
        domain_tags = ",".join(sorted(worker_tags.get(worker_id, set())))
        workers_rows.append(
            {
                "worker_id": worker_id,
                "skill_vector": profile["skill_vector"],
                "past_tasks_count": profile["past_tasks_count"],
                "past_wins": profile["past_wins"],
                "domain_tags": domain_tags,
            }
        )

    def _write_csv(filename: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        path = output_dir / filename
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    _write_csv("tasks.csv", tasks_rows)
    _write_csv("workers.csv", workers_rows)
    _write_csv("interactions.csv", interactions_rows)
    print(f"Wrote {len(tasks_rows)} tasks, {len(workers_rows)} workers, {len(interactions_rows)} interactions to {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export challenge JSON to data/raw tables.")
    parser.add_argument(
        "--challenge-dir",
        action="append",
        required=True,
        type=Path,
        help="Path(s) to challenge_data directories containing challengeData_*/pageN.json files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory to write tasks.csv/workers.csv/interactions.csv (default data/raw).",
    )
    parser.add_argument(
        "--registrant-cap",
        type=int,
        default=200,
        help="Maximum synthetic registrants per challenge to avoid exploding dataset size (default 200).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_real_tables(args.challenge_dir, args.output_dir, registrant_cap=args.registrant_cap)


if __name__ == "__main__":
    main()
