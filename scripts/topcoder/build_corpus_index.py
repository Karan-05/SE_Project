#!/usr/bin/env python3
"""Build a Topcoder corpus index + summary for the funnel."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import glob
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Sequence, Tuple

TECH_SPLIT_RE = re.compile(r"[;,]")
REPO_PATTERN = re.compile(r"(https?://[A-Za-z0-9_\-./]+|git@[^\\s]+)")
TEST_KEYWORDS = (
    "test",
    "unit test",
    "qa",
    "spec",
    "mocha",
    "jest",
    "junit",
    "pytest",
    "cypress",
)
CODE_KEYWORDS = (
    "implement",
    "fix",
    "bug",
    "patch",
    "api",
    "service",
    "feature",
    "code",
    "repo",
    "git",
)
REPO_FIELD_CANDIDATES = (
    "repo_url",
    "repoUrl",
    "gitRepoUrl",
    "githubRepoUrl",
    "taskRepoUrl",
    "repositoryUrl",
    "sourceRepoUrl",
    "codeRepoUrl",
    "repo",
)


@dataclass
class CorpusSummary:
    raw_rows_seen: int = 0
    tasks_csv_rows: int = 0
    json_rows: int = 0
    repo_count: int = 0
    test_count: int = 0
    likely_executable_count: int = 0
    duplicate_group_count: int = 0
    duplicate_groups: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self, indexed_rows: int) -> Dict[str, Any]:
        return {
            "raw_rows_seen": self.raw_rows_seen,
            "tasks_csv_rows": self.tasks_csv_rows,
            "json_rows": self.json_rows,
            "indexed_rows": indexed_rows,
            "repo_count": self.repo_count,
            "test_count": self.test_count,
            "likely_executable_count": self.likely_executable_count,
            "duplicate_group_count": self.duplicate_group_count,
            "duplicate_groups": self.duplicate_groups,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Topcoder corpus index.")
    parser.add_argument(
        "--tasks-csv",
        "--tasks",
        dest="tasks_csv",
        type=Path,
        default=Path("data/raw/tasks.csv"),
        help="Path to tasks.csv (default data/raw/tasks.csv).",
    )
    parser.add_argument(
        "--pages-glob",
        action="append",
        default=None,
        help="Glob(s) for archived API windows (page*.json*).",
    )
    parser.add_argument(
        "--challenge-glob",
        action="append",
        default=None,
        help="Glob(s) for challenge_data exports.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/topcoder/corpus_index.jsonl"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/topcoder/corpus_summary.json"),
    )
    parser.add_argument(
        "--parquet-output",
        type=Path,
        default=Path("data/topcoder/corpus_index.parquet"),
    )
    return parser.parse_args()


def parse_tags(value: str | None) -> List[str]:
    if not value:
        return []
    return [token.strip() for token in TECH_SPLIT_RE.split(value) if token.strip()]


def _coerce_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace(",", "").strip()
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _sanitize_repo_url(url: str | None) -> str:
    if not url:
        return ""
    cleaned = url.strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return cleaned.rstrip("/").lower()


def _extract_repo_url(payload: Dict[str, Any], description: str) -> Tuple[str, List[str]]:
    heuristics: List[str] = []
    for field in REPO_FIELD_CANDIDATES:
        value = payload.get(field)
        if isinstance(value, str):
            match = REPO_PATTERN.search(value)
            if match:
                heuristics.append(f"{field}_field")
                return _sanitize_repo_url(match.group(0)), heuristics
    match = REPO_PATTERN.search(description)
    if match:
        heuristics.append("description_repo_url")
        return _sanitize_repo_url(match.group(0)), heuristics
    return "", heuristics


def _infer_tests(description: str, tags: Iterable[str], technologies: Iterable[str]) -> Tuple[bool, List[str]]:
    haystack = " ".join([description, " ".join(tags), " ".join(technologies)]).lower()
    hits: List[str] = []
    for keyword in TEST_KEYWORDS:
        if keyword in haystack:
            hits.append(f"test_keyword:{keyword}")
    return bool(hits), hits


def _infer_code_signals(description: str) -> List[str]:
    desc = description.lower()
    matches = []
    for keyword in CODE_KEYWORDS:
        if keyword in desc:
            matches.append(f"code_keyword:{keyword}")
    return matches


def _duplicate_key(challenge_id: str, title: str, track: str, repo_url: str) -> str:
    if repo_url:
        return repo_url
    normalized_title = re.sub(r"\s+", " ", title.strip().lower())
    return f"{normalized_title}|{track.strip().lower()}"


def _iter_tasks_csv(path: Path) -> Iterator[Tuple[Dict[str, Any], str]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row, str(path)


def _iter_json_payloads(patterns: Sequence[str] | None) -> Iterator[Tuple[Dict[str, Any], str]]:
    if not patterns:
        return
    seen_paths: set[Path] = set()
    for pattern in patterns:
        for path_str in glob.glob(pattern, recursive=True):
            path = Path(path_str)
            if not path.is_file() or path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                if path.suffix == ".gz":
                    with gzip.open(path, "rt", encoding="utf-8") as handle:
                        payload = json.load(handle)
                else:
                    payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, list):
                for record in payload:
                    if isinstance(record, dict):
                        yield record, str(path)
            elif isinstance(payload, dict):
                yield payload, str(path)


def build_record(payload: Dict[str, Any], source_file: str) -> Dict[str, Any]:
    challenge_id = str(payload.get("task_id") or payload.get("challengeId") or payload.get("id") or "").strip()
    if not challenge_id:
        return {}
    title = str(payload.get("title") or payload.get("name") or "").strip()
    difficulty = str(payload.get("difficulty") or payload.get("trackType") or payload.get("track") or "").strip()
    technologies = parse_tags(payload.get("tech_stack") or payload.get("technologies"))
    tags = parse_tags(payload.get("tags"))
    description = str(payload.get("description") or "")
    repo_url, repo_signals = _extract_repo_url(payload, description)
    has_repo = bool(repo_url)
    has_tests, test_signals = _infer_tests(description, tags, technologies)
    code_signals = _infer_code_signals(description)
    num_submissions = _coerce_int(payload.get("num_submissions") or payload.get("numOfSubmissions"))
    prize = _coerce_float(payload.get("prize") or payload.get("totalPrizeCost"))
    track = str(payload.get("track") or payload.get("trackType") or "").strip()
    heuristics = repo_signals + test_signals + code_signals
    if num_submissions > 0:
        heuristics.append("submissions_gt_zero")
    likely_executable = has_repo and (has_tests or bool(code_signals) or num_submissions > 0)
    record = {
        "challenge_id": challenge_id,
        "title": title,
        "difficulty": difficulty,
        "technologies": technologies,
        "tags": tags,
        "repo_url": repo_url,
        "has_repo": has_repo,
        "has_tests": has_tests,
        "likely_executable": likely_executable,
        "track": track,
        "prize": prize,
        "num_submissions": num_submissions,
        "posted_time": payload.get("posted_time") or payload.get("registrationStartDate") or payload.get("startDate"),
        "deadline": payload.get("deadline") or payload.get("submissionEndDate") or payload.get("endDate"),
        "source_files": [source_file],
        "source_file": source_file,
        "heuristics_used": heuristics,
        "notes": "; ".join(heuristics),
        "duplicate_group_key": _duplicate_key(challenge_id, title, track, repo_url),
    }
    return record


def merge_record(existing: Dict[str, Any], new_record: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in new_record.items():
        if key in {"source_files", "heuristics_used"}:
            continue
        if not existing.get(key) and value not in (None, "", []):
            existing[key] = value
    existing.setdefault("source_files", [])
    existing["source_files"].extend(new_record.get("source_files", []))
    existing.setdefault("heuristics_used", [])
    existing["heuristics_used"].extend(new_record.get("heuristics_used", []))
    existing["has_repo"] = existing.get("has_repo") or new_record.get("has_repo", False)
    existing["has_tests"] = existing.get("has_tests") or new_record.get("has_tests", False)
    existing["likely_executable"] = existing.get("likely_executable") or new_record.get("likely_executable", False)
    existing["repo_url"] = existing.get("repo_url") or new_record.get("repo_url")
    existing["num_submissions"] = max(existing.get("num_submissions", 0), new_record.get("num_submissions", 0))
    existing["prize"] = max(existing.get("prize", 0.0), new_record.get("prize", 0.0))
    return existing


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def try_write_parquet(path: Path, rows: List[Dict[str, Any]]) -> None:
    try:
        import pandas as pd  # type: ignore

        df = pd.DataFrame(rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
    except Exception:
        return


def build_index(args: argparse.Namespace) -> Dict[str, Any]:
    records: Dict[str, Dict[str, Any]] = {}
    summary = CorpusSummary()

    for row, source in _iter_tasks_csv(args.tasks_csv):
        summary.raw_rows_seen += 1
        summary.tasks_csv_rows += 1
        record = build_record(row, source)
        key = record.get("challenge_id")
        if not key:
            continue
        if key in records:
            records[key] = merge_record(records[key], record)
        else:
            records[key] = record

    page_patterns = (
        args.pages_glob
        if args.pages_glob is not None
        else ["data/raw/page*.json", "data/raw/page*.json.gz"]
    )
    challenge_patterns = (
        args.challenge_glob
        if args.challenge_glob is not None
        else [
            "challenge_data/challengeData_*/*.json",
            "challenge_data/challengeData_*/*.json.gz",
        ]
    )
    combined_json_patterns = page_patterns + challenge_patterns
    for payload, source in _iter_json_payloads(combined_json_patterns):
        summary.raw_rows_seen += 1
        summary.json_rows += 1
        record = build_record(payload, source)
        key = record.get("challenge_id")
        if not key:
            continue
        if key in records:
            records[key] = merge_record(records[key], record)
        else:
            records[key] = record

    rows: List[Dict[str, Any]] = []
    duplicate_groups: Dict[str, List[str]] = defaultdict(list)
    for record in records.values():
        record["source_files"] = sorted(set(record.get("source_files", [])))
        record["source_file"] = record["source_files"][0] if record["source_files"] else ""
        heuristics = sorted(set(record.get("heuristics_used", [])))
        record["heuristics_used"] = heuristics
        record["notes"] = "; ".join(heuristics)
        record["duplicate_group_key"] = _duplicate_key(
            record["challenge_id"],
            record.get("title", ""),
            record.get("track", ""),
            record.get("repo_url", ""),
        )
        duplicate_groups[record["duplicate_group_key"]].append(record["challenge_id"])
        summary.repo_count += 1 if record.get("has_repo") else 0
        summary.test_count += 1 if record.get("has_tests") else 0
        summary.likely_executable_count += 1 if record.get("likely_executable") else 0
        rows.append(record)

    dup_map = {key: ids for key, ids in duplicate_groups.items() if len(ids) > 1}
    summary.duplicate_group_count = len(dup_map)
    # Keep the first 50 duplicate groups (size only) to avoid bloating the summary.
    limited_dup = {
        key: ids[:10]
        for key, ids in list(dup_map.items())[:50]
    }
    summary.duplicate_groups = {key: value for key, value in limited_dup.items()}

    write_jsonl(args.output, rows)
    try_write_parquet(args.parquet_output, rows)
    summary_payload = summary.to_dict(len(rows))
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    print(
        "Corpus index built | "
        f"raw_rows_seen={summary.raw_rows_seen} | indexed_rows={len(rows)} | "
        f"repo_count={summary.repo_count} | likely_executable_count={summary.likely_executable_count}"
    )
    return summary_payload


def main() -> None:
    args = parse_args()
    build_index(args)


if __name__ == "__main__":
    main()
