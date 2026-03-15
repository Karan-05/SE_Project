from __future__ import annotations

from src.public_repos.scoring import compute_suitability
from src.public_repos.selection import (
    SelectionConfig,
    build_selection_summary,
    parse_language_targets,
    select_pool,
)
from src.public_repos.types import RepoCandidate, RepoIdentity


def make_candidate(idx: int, language: str, owner: str, stars: int = 50) -> RepoCandidate:
    identity = RepoIdentity(host="github.com", owner=owner, name=f"repo{idx}")
    candidate = RepoCandidate.from_identity(identity, source_type="host_search")
    candidate.language = language
    candidate.stars = stars
    candidate.has_build_files = True
    candidate.has_tests = True
    candidate.has_ci = True
    candidate.has_license = True
    candidate.estimated_size_kb = 1024
    candidate.last_pushed_at = "2024-02-01T00:00:00Z"
    compute_suitability(candidate, min_stars=20, recent_days=365)
    return candidate


def test_selection_respects_language_targets_and_owner_cap() -> None:
    candidates = [
        make_candidate(1, "python", "alpha"),
        make_candidate(2, "python", "beta"),
        make_candidate(3, "javascript", "gamma"),
        make_candidate(4, "javascript", "gamma"),
        make_candidate(5, "typescript", "delta"),
    ]
    overrides = {"python": 2, "javascript": 1}
    config = SelectionConfig(
        target_size=3,
        min_stars=10,
        max_stars=None,
        exclude_archived=False,
        require_tests=False,
        require_build_files=False,
        max_per_owner=1,
        seed=0,
        languages=["python", "javascript", "typescript"],
        per_language_targets=parse_language_targets(["python", "javascript"], 3, overrides),
    )
    selected, filtered, filter_counts = select_pool(candidates, config)
    assert len(selected) == 3
    summary = build_selection_summary(candidates, filtered, selected, config, filter_counts)
    assert summary["language_summary"]["python"]["selected"] == 2
    assert summary["language_summary"]["javascript"]["selected"] == 1
    owners = {owner for owner, _ in summary["owner_distribution"]}
    assert len(owners) == len(summary["owner_distribution"])


def test_selection_filters_missing_tests_when_required() -> None:
    good = make_candidate(1, "python", "alpha")
    missing_tests = make_candidate(2, "python", "beta")
    missing_tests.has_tests = False
    compute_suitability(missing_tests, min_stars=20, recent_days=365)
    config = SelectionConfig(
        target_size=2,
        min_stars=10,
        max_stars=None,
        exclude_archived=False,
        require_tests=True,
        require_build_files=False,
        max_per_owner=2,
        seed=0,
        languages=["python"],
        per_language_targets={"python": 2},
    )
    selected, filtered, filter_counts = select_pool([good, missing_tests], config)
    assert len(selected) == 1
    assert filter_counts["missing_tests"] == 1
