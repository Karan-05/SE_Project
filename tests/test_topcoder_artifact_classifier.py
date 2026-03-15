from __future__ import annotations

from src.decomposition.topcoder.artifact_classifier import classify_candidate_url


def test_classify_github_repo_page() -> None:
    result = classify_candidate_url("https://github.com/topcoder-platform/community-app")
    assert result.artifact_type == "git_host_repo_page"
    assert result.acquisition_strategy == "clone_or_source_download"
    assert result.normalized_repo_key == "github.com/topcoder-platform/community-app"


def test_classify_git_remote_prefers_clone_strategy() -> None:
    result = classify_candidate_url("git@github.com:Topcoder/Community-App.git")
    assert result.artifact_type == "git_repo"
    assert result.acquisition_strategy == "clone"


def test_classify_source_archive() -> None:
    result = classify_candidate_url("https://github.com/example/foo/archive/refs/heads/main.zip")
    assert result.artifact_type == "source_archive"
    assert result.acquisition_strategy == "download_archive"
    assert result.normalized_repo_key


def test_classify_execute_api_url_as_api_endpoint() -> None:
    result = classify_candidate_url("https://abcd123.execute-api.us-east-1.amazonaws.com/dev/override")
    assert result.artifact_type == "api_endpoint"
    assert result.acquisition_strategy == "reject_non_repo"


def test_classify_direct_ip_as_api_endpoint() -> None:
    result = classify_candidate_url("https://52.24.44.42/srt")
    assert result.artifact_type in {"api_endpoint", "web_app"}
    assert result.acquisition_strategy == "reject_non_repo"


def test_classify_docs_page() -> None:
    result = classify_candidate_url("https://example.com/docs/getting-started")
    assert result.artifact_type == "docs_page"
    assert result.acquisition_strategy == "reject_non_repo"
