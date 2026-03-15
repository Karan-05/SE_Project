from __future__ import annotations

from pathlib import Path

import pytest

from scripts.topcoder import fetch_topcoder_repos as fetch_script
from src.decomposition.topcoder.repos import (
    GitCommandError,
    RepoCandidateRecord,
    build_fetch_result,
    group_repo_candidates,
)


def make_candidate(
    challenge_id: str,
    repo_url: str,
    normalized_key: str,
    confidence: str = "high",
    strategy: str = "clone",
    artifact_type: str = "git_repo",
) -> RepoCandidateRecord:
    return RepoCandidateRecord(
        challenge_id=challenge_id,
        title="Sample",
        candidate_url=repo_url,
        repo_url=repo_url,
        normalized_url=repo_url,
        repo_host="github.com",
        normalized_repo_key=normalized_key,
        source_field="tests:repo_url",
        discovery_method="explicit_field",
        confidence_score=confidence,
        evidence_snippet="",
        acquisition_strategy=strategy,
        artifact_type=artifact_type,
        classification_reason="tests",
        notes="",
        challenge_text_context="",
        normalized_repo_url=repo_url,
    )


def test_group_repo_candidates_deduplicates_by_repo() -> None:
    records = [
        make_candidate("challenge-a", "https://github.com/topcoder/sample", "github.com/topcoder/sample"),
        make_candidate("challenge-b", "https://github.com/topcoder/sample", "github.com/topcoder/sample"),
    ]
    groups = group_repo_candidates(records, min_confidence="low")
    assert len(groups) == 1
    assert groups[0].challenge_ids == {"challenge-a", "challenge-b"}


def test_build_fetch_result_dry_run(tmp_path: Path) -> None:
    records = [make_candidate("challenge-a", "https://github.com/topcoder/sample", "github.com/topcoder/sample")]
    group = group_repo_candidates(records)[0]
    result = build_fetch_result(group, tmp_path, dry_run=True, timeout=5, retries=0)
    assert result.clone_status == "dry_run"
    assert result.local_path
    assert result.candidate_urls


def test_build_fetch_result_captures_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    records = [make_candidate("challenge-a", "https://github.com/topcoder/sample", "github.com/topcoder/sample")]
    group = group_repo_candidates(records)[0]

    def fake_ensure(*args, **kwargs):
        raise GitCommandError("boom")

    monkeypatch.setattr("src.decomposition.topcoder.repos.ensure_repo", fake_ensure)
    result = build_fetch_result(group, tmp_path, dry_run=False, timeout=1, retries=0)
    assert result.clone_status == "failed"
    assert result.error_type == "git_error"
    assert "boom" in (result.error_message or "")


def test_build_fetch_result_archive_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    records = [
        make_candidate(
            "challenge-a",
            "https://example.com/archive.zip",
            "github.com/example/archive--abc",
            strategy="download_archive",
            artifact_type="source_archive",
        )
    ]
    group = group_repo_candidates(records)[0]

    def fake_download(url, dest, timeout):
        (dest / "README.md").parent.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("ok", encoding="utf-8")
        return "abcd"

    monkeypatch.setattr("src.decomposition.topcoder.repos.download_and_unpack_archive", fake_download)
    result = build_fetch_result(group, tmp_path, dry_run=False, timeout=1, retries=0)
    assert result.clone_status == "archive_downloaded"
    assert result.source_origin == "archive"
    assert result.archive_hash == "abcd"


def test_clone_failure_falls_back_to_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    records = [
        make_candidate(
            "challenge-a",
            "https://github.com/example/foo",
            "github.com/example/foo",
            strategy="clone_or_source_download",
            artifact_type="git_host_repo_page",
        )
    ]
    group = group_repo_candidates(records)[0]

    def fake_ensure(*args, **kwargs):
        raise GitCommandError("fail")

    def fake_download(url, dest, timeout):
        dest.mkdir(parents=True, exist_ok=True)
        return "hash123"

    monkeypatch.setattr("src.decomposition.topcoder.repos.ensure_repo", fake_ensure)
    monkeypatch.setattr("src.decomposition.topcoder.repos.download_and_unpack_archive", fake_download)
    result = build_fetch_result(group, tmp_path, dry_run=False, timeout=1, retries=0, prefer_archive_fallback=True)
    assert result.clone_status == "archive_downloaded"
    assert result.source_origin == "archive"


def test_make_rejection_result_marks_rejection(tmp_path: Path) -> None:
    records = [make_candidate("challenge-a", "https://github.com/example/foo", "github.com/example/foo")]
    group = group_repo_candidates(records)[0]
    result = fetch_script.make_rejection_result(group, tmp_path, "host_not_allowed", "example.com")
    assert result.clone_status == "rejected"
    assert result.rejection_reason == "host_not_allowed"
