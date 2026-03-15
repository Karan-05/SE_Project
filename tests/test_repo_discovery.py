from __future__ import annotations

from src.decomposition.topcoder.discovery import (
    ChallengeRecord,
    discover_candidates_from_record,
    discover_repo_candidates,
    extract_urls_from_text,
)
from src.decomposition.topcoder.repos import normalize_repo_url


def make_record(
    challenge_id: str,
    description: str,
    payload: dict[str, object] | None = None,
) -> ChallengeRecord:
    return ChallengeRecord(
        challenge_id=challenge_id,
        title="Sample",
        description=description,
        payload=payload or {},
        source_path="tests",
    )


def test_extract_urls_from_text_finds_common_hosts() -> None:
    text = (
        "Source repos: https://github.com/topcoder-platform/community-app "
        "and git@gitlab.com:foo/bar.git plus https://bitbucket.org/org/repo"
    )
    urls = list(extract_urls_from_text(text))
    assert "https://github.com/topcoder-platform/community-app" in urls
    assert "git@gitlab.com:foo/bar.git" in urls
    assert "https://bitbucket.org/org/repo" in urls


def test_normalize_repo_url_handles_ssh_and_https() -> None:
    ssh_info = normalize_repo_url("git@github.com:Topcoder/Community-App.git")
    https_info = normalize_repo_url("https://github.com/topcoder/community-app/")
    assert ssh_info
    assert https_info
    assert ssh_info.repo_key == "github.com/topcoder/community-app"
    assert ssh_info.repo_key == https_info.repo_key


def test_discovery_assigns_confidence_by_field() -> None:
    payload = {
        "repo_url": "https://github.com/topcoder-platform/community-app",
        "description": "See docs here https://github.com/topcoder-platform/community-app/wiki",
    }
    record = make_record("challenge-1", "desc", payload)
    candidates = discover_candidates_from_record(record)
    assert any(candidate.confidence_score == "high" for candidate in candidates)
    assert any(candidate.discovery_method == "text_field" for candidate in candidates)


def test_discovery_marks_duplicates_across_records() -> None:
    payload = {"repo_url": "https://github.com/topcoder-platform/community-app"}
    records = [
        make_record("challenge-a", "", payload),
        make_record("challenge-b", "", payload),
    ]
    candidates, summary = discover_repo_candidates(records)
    assert summary.unique_repo_count == 1
    dup_flags = [candidate.is_duplicate_candidate for candidate in candidates]
    assert any(dup_flags)
