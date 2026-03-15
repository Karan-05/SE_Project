from __future__ import annotations

from src.decomposition.topcoder.discovery import ArtifactCandidate, filter_repo_candidates


def make_artifact(
    normalized_repo_key: str | None,
    artifact_type: str,
    acquisition_strategy: str,
    confidence: str = "high",
) -> ArtifactCandidate:
    url = "https://github.com/example/foo"
    return ArtifactCandidate(
        challenge_id="challenge",
        title="Example",
        candidate_url=url,
        normalized_url=url,
        host="github.com",
        path="/example/foo",
        source_path="tests",
        source_field="tests:repo_url",
        discovery_method="explicit_field",
        evidence_snippet="",
        artifact_type=artifact_type,
        acquisition_strategy=acquisition_strategy,
        confidence_score=confidence,
        classification_reason="test",
        normalized_repo_key=normalized_repo_key,
        normalized_repo_url=url if normalized_repo_key else None,
        challenge_text_context="",
        notes="",
    )


def test_filter_repo_candidates_skips_non_source_artifacts() -> None:
    artifacts = [
        make_artifact("github.com/example/foo", "git_host_repo_page", "clone_or_source_download"),
        make_artifact(None, "api_endpoint", "reject_non_repo"),
    ]
    candidates, summary = filter_repo_candidates(artifacts)
    assert len(candidates) == 1
    assert summary.repo_candidates_emitted == 1


def test_filter_repo_candidates_keeps_archive_candidates() -> None:
    artifacts = [
        make_artifact("github.com/example/archive--abc", "source_archive", "download_archive"),
    ]
    candidates, summary = filter_repo_candidates(artifacts)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.acquisition_strategy == "download_archive"
    assert summary.repo_candidates_emitted == 1


def test_duplicates_marked_when_repo_key_repeats() -> None:
    artifacts = [
        make_artifact("github.com/example/foo", "git_repo", "clone"),
        make_artifact("github.com/example/foo", "git_repo", "clone"),
    ]
    candidates, summary = filter_repo_candidates(artifacts)
    assert len(candidates) == 2
    assert any(candidate.is_duplicate_candidate for candidate in candidates)
    assert summary.unique_repo_count == 1
