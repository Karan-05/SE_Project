from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
import csv

from scripts.topcoder import build_corpus_index, select_executable_subset, build_funnel_report
from src.decomposition.openai_ops import load_jsonl


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _build_sample_corpus(tmp_path: Path) -> None:
    tasks_csv = tmp_path / "tasks.csv"
    _write_csv(
        tasks_csv,
        [
            {
                "task_id": "alpha",
                "title": "Alpha Challenge",
                "description": "Fix bug https://github.com/foo/bar includes tests",
                "tags": "JavaScript,QA",
                "tech_stack": "Node",
                "prize": "500",
                "difficulty": "2",
                "track": "Development",
                "num_submissions": "5",
                "posted_time": "2023-01-01T01:00:00Z",
                "deadline": "2023-01-05T01:00:00Z",
            },
            {
                "task_id": "beta",
                "title": "Spec Work",
                "description": "Write a report, no repo",
                "tags": "",
                "tech_stack": "",
                "prize": "50",
                "difficulty": "1",
                "track": "Design",
                "num_submissions": "0",
                "posted_time": "2023-01-01T01:00:00Z",
                "deadline": "2023-01-05T01:00:00Z",
            },
        ],
    )
    page_payload = [
        {
            "challengeId": "alpha-dup",
            "name": "Alpha Duplicate",
            "description": "See https://github.com/foo/bar and add tests",
            "trackType": "Development",
            "totalPrizeCost": 100,
            "numOfSubmissions": 3,
        }
    ]
    page_path = tmp_path / "page1.json"
    _write_json(page_path, page_payload)
    args = SimpleNamespace(
        tasks_csv=tasks_csv,
        pages_glob=[str(page_path)],
        challenge_glob=[],
        output=tmp_path / "index.jsonl",
        summary_output=tmp_path / "summary.json",
        parquet_output=tmp_path / "index.parquet",
    )
    summary = build_corpus_index.build_index(args)
    assert summary["indexed_rows"] == 3


def test_corpus_index_summary(tmp_path: Path) -> None:
    _build_sample_corpus(tmp_path)
    rows = load_jsonl(tmp_path / "index.jsonl")
    repo_rows = [row for row in rows if row["challenge_id"] == "alpha"]
    assert repo_rows and repo_rows[0]["has_repo"] is True
    assert "duplicate_group_key" in repo_rows[0]
    assert repo_rows[0]["source_file"]
    assert repo_rows[0]["heuristics_used"], "expected heuristic annotations"


def test_select_executable_subset_records_rejections(tmp_path: Path) -> None:
    _build_sample_corpus(tmp_path)
    args = SimpleNamespace(
        index_file=tmp_path / "index.jsonl",
        output=tmp_path / "subset.jsonl",
        summary_output=tmp_path / "subset_summary.json",
        rejections_output=tmp_path / "subset_rejections.jsonl",
        min_submissions=1,
        min_prize=0.0,
        require_tests=True,
        tracks=["development"],
        include_technologies=None,
        include_tags=None,
        posted_after="",
    )
    summary = select_executable_subset.select_subset(args)
    subset = load_jsonl(tmp_path / "subset.jsonl")
    assert len(subset) == 1
    rejections = load_jsonl(tmp_path / "subset_rejections.jsonl")
    reasons = {reason for row in rejections for reason in row["reasons"]}
    assert "missing_repo" in reasons
    assert "duplicate" in reasons
    assert summary["rejections"]["missing_repo"] >= 1
    assert summary["rejections"]["duplicate"] >= 1


def test_build_funnel_report_counts(tmp_path: Path) -> None:
    _build_sample_corpus(tmp_path)
    cgcs_dir = tmp_path / "cgcs"
    _write_jsonl(cgcs_dir / "train.jsonl", [{"task_id": "alpha"}])
    _write_jsonl(cgcs_dir / "dev.jsonl", [])
    _write_jsonl(cgcs_dir / "test.jsonl", [])
    _write_jsonl(
        cgcs_dir / "rejected.jsonl",
        [
            {"task_id": "beta", "row_errors": ["missing_active_clause_id"]},
            {"task_id": "gamma", "row_errors": ["missing_active_clause_id", "empty_contract_items"]},
        ],
    )
    _write_jsonl(tmp_path / "eval.jsonl", [{"task_id": "alpha"}])
    _write_jsonl(tmp_path / "batch.jsonl", [{"custom_id": "alpha"}])
    skipped = tmp_path / "skipped.jsonl"
    _write_jsonl(skipped, [{"task_id": "beta", "reason": "weak_contract"}])
    normalized_dir = tmp_path / "normalized"
    _write_jsonl(
        normalized_dir / "latest.jsonl",
        [
            {"payload": {"status": "solved"}},
            {"payload": {"status": "failed"}},
        ],
    )
    _write_jsonl(
        normalized_dir / "latest_errors.jsonl",
        [{"error_code": "rate_limit"}],
    )

    args = SimpleNamespace(
        tasks_csv=tmp_path / "tasks.csv",
        corpus_index=tmp_path / "index.jsonl",
        executable_subset=tmp_path / "subset.jsonl",
        cgcs_dir=cgcs_dir,
        eval_items=tmp_path / "eval.jsonl",
        batch_requests=tmp_path / "batch.jsonl",
        skipped_eval=skipped,
        normalized_dir=normalized_dir,
        output_json=tmp_path / "funnel.json",
        output_markdown=tmp_path / "funnel.md",
    )
    payload = build_funnel_report.build_report(args)
    assert payload["stages"]["indexed_count"] >= payload["stages"]["raw_corpus_count"]
    assert payload["stages"]["executable_subset_count"] == len(load_jsonl(tmp_path / "subset.jsonl"))
    assert payload["details"]["cgcs_rejections"]["missing_active_clause_id"] == 2
    assert (tmp_path / "funnel.md").exists()
