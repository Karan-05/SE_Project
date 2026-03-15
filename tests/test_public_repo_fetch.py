from __future__ import annotations

from pathlib import Path

from src.decomposition.topcoder.repos import GitCommandError
from src.public_repos.fetcher import FetchOptions, build_fetch_requests, fetch_repositories


def make_records() -> list[dict[str, object]]:
    return [
        {
            "repo_url": "https://github.com/example/demo",
            "repo_key": "github.com/example/demo",
            "language": "python",
            "selection_rank": 1,
        }
    ]


def test_fetch_dry_run_emits_manifest(tmp_path: Path) -> None:
    records = make_records()
    requests = build_fetch_requests(records, tmp_path)
    options = FetchOptions(dry_run=True, timeout=60, retries=0, validate_remote=True)
    results = fetch_repositories(requests, options, max_workers=1)
    assert len(results) == 1
    assert results[0].status == "dry_run"
    assert results[0].as_dict()["local_path"].startswith(str(tmp_path))


def test_fetch_handles_clone_failure(monkeypatch, tmp_path: Path) -> None:
    records = make_records()
    requests = build_fetch_requests(records, tmp_path)

    def fake_ensure(*args, **kwargs):
        raise GitCommandError("ls-remote failed")

    monkeypatch.setattr("src.public_repos.fetcher.ensure_repo", fake_ensure)
    options = FetchOptions(dry_run=False, timeout=1, retries=0, validate_remote=True)
    results = fetch_repositories(requests, options, max_workers=1)
    assert results[0].status == "failed"
    assert "ls-remote" in results[0].error_message


def test_fetch_records_success(monkeypatch, tmp_path: Path) -> None:
    records = make_records()
    requests = build_fetch_requests(records, tmp_path)

    def fake_ensure(*args, **kwargs):
        return "updated", "main", "abc123"

    monkeypatch.setattr("src.public_repos.fetcher.ensure_repo", fake_ensure)
    options = FetchOptions(dry_run=False, timeout=1, retries=0, validate_remote=False)
    results = fetch_repositories(requests, options, max_workers=1)
    assert results[0].status == "updated"
    payload = results[0].as_dict()
    assert payload["resolved_commit"] == "abc123"
