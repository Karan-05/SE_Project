from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.topcoder import build_repo_acquisition_report as report_script


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_source_acquisition_report_counts(tmp_path: Path, monkeypatch) -> None:
    artifact_file = tmp_path / "artifact.jsonl"
    repo_file = tmp_path / "repo.jsonl"
    fetch_file = tmp_path / "fetch.jsonl"
    snapshots_file = tmp_path / "snapshots.jsonl"
    workspaces_file = tmp_path / "workspaces.jsonl"
    json_output = tmp_path / "report.json"
    md_output = tmp_path / "report.md"

    write_jsonl(
        artifact_file,
        [
            {
                "artifact_type": "git_host_repo_page",
                "acquisition_strategy": "clone_or_source_download",
                "host": "github.com",
            },
            {
                "artifact_type": "docs_page",
                "acquisition_strategy": "reject_non_repo",
                "host": "docs.example.com",
            },
        ],
    )
    write_jsonl(
        repo_file,
        [
            {
                "normalized_repo_key": "github.com/example/foo",
                "repo_host": "github.com",
                "acquisition_strategy": "clone",
            },
            {
                "normalized_repo_key": "github.com/example/foo",
                "repo_host": "github.com",
                "acquisition_strategy": "clone",
            },
        ],
    )
    write_jsonl(
        fetch_file,
        [
            {
                "normalized_repo_key": "github.com/example/foo",
                "repo_host": "github.com",
                "clone_status": "cloned",
                "source_origin": "clone",
            },
            {
                "normalized_repo_key": "docs",
                "repo_host": "docs.example.com",
                "clone_status": "rejected",
                "rejection_reason": "host_not_allowed",
            },
        ],
    )
    write_jsonl(
        snapshots_file,
        [
            {
                "snapshot_id": "github.com/example/foo@123",
                "repo_url": "https://github.com/example/foo",
                "source_origin": "clone",
                "local_path": "/tmp/foo",
                "normalized_repo_key": "github.com/example/foo",
                "resolved_commit": "123",
                "branch": "main",
                "archive_hash": None,
                "challenge_ids": [],
                "detected_languages": [],
                "detected_build_systems": [],
                "detected_package_managers": [],
                "detected_test_frameworks": [],
                "likely_runnable": True,
                "likely_js_repo": False,
                "likely_python_repo": False,
                "likely_java_repo": False,
                "workspace_prep_status": "pending",
            }
        ],
    )
    write_jsonl(
        workspaces_file,
        [
            {
                "workspace_id": "github.com/example/foo@123::workspace",
                "snapshot_id": "github.com/example/foo@123",
                "repo_url": "https://github.com/example/foo",
                "source_origin": "clone",
                "local_path": "/tmp/foo",
                "install_command": None,
                "build_command": None,
                "test_command": None,
                "env_hints": [],
                "prep_status": "manifest_only",
                "prep_error": None,
                "runnable_confidence": "medium",
                "notes": "",
                "synthetic_workspace": False,
                "original_repo_recovered": True,
            }
        ],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_repo_acquisition_report.py",
            "--artifact-candidates",
            str(artifact_file),
            "--candidates",
            str(repo_file),
            "--fetch-manifest",
            str(fetch_file),
            "--snapshots",
            str(snapshots_file),
            "--workspaces",
            str(workspaces_file),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(md_output),
        ],
    )
    report_script.main()

    data = json.loads(json_output.read_text(encoding="utf-8"))
    assert data["artifact_stage"]["total_artifact_candidates"] == 2
    assert data["artifact_stage"]["rejected_non_source_candidates"] == 1
    assert data["repo_candidate_stage"]["unique_repo_candidates"] == 1
    assert data["fetch_stage"]["clone_success_count"] == 1
    assert data["snapshot_stage"]["snapshot_count"] == 1
    assert data["workspace_stage"]["workspace_manifest_count"] == 1
