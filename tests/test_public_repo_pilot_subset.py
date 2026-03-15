"""Tests for pilot subset selection logic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.public_repos.select_cgcs_pilot_subset import select_pilot_subset


def _make_entry(repo_key: str, language: str, confidence: float) -> dict:
    parts = repo_key.split("/")
    return {
        "repo_key": repo_key,
        "language": language,
        "runnable_confidence": confidence,
        "local_path": f"/data/{repo_key}",
    }


def test_select_pilot_subset_basic():
    records = [
        _make_entry("github.com/ownerA/repoA", "python", 1.0),
        _make_entry("github.com/ownerB/repoB", "javascript", 0.9),
        _make_entry("github.com/ownerC/repoC", "typescript", 0.8),
        _make_entry("github.com/ownerD/repoD", "java", 0.7),
        _make_entry("github.com/ownerE/repoE", "python", 0.6),
    ]
    selected = select_pilot_subset(records, max_repos=3, min_confidence=0.6, seed=0)
    assert 1 <= len(selected) <= 3
    for idx, entry in enumerate(selected, start=1):
        assert entry["pilot_rank"] == idx
        assert isinstance(entry.get("selection_reason"), str)
        assert entry["selection_reason"]


def test_select_pilot_subset_confidence_filter():
    records = [
        _make_entry("github.com/ownerA/repoA", "python", 0.3),
        _make_entry("github.com/ownerB/repoB", "python", 0.9),
    ]
    selected = select_pilot_subset(records, max_repos=5, min_confidence=0.6, seed=0)
    assert len(selected) == 1
    assert selected[0]["repo_key"] == "github.com/ownerB/repoB"


def test_select_pilot_subset_owner_cap():
    """Same owner should appear at most once."""
    records = [
        _make_entry("github.com/sameOwner/repo1", "python", 1.0),
        _make_entry("github.com/sameOwner/repo2", "python", 0.9),
        _make_entry("github.com/otherOwner/repo3", "python", 0.8),
    ]
    selected = select_pilot_subset(records, max_repos=5, min_confidence=0.5, seed=0)
    owners = [r["repo_key"].split("/")[-2] for r in selected]
    assert owners.count("sameOwner") <= 1


def test_select_pilot_subset_determinism():
    records = [
        _make_entry(f"github.com/owner{i}/repo{i}", "python", 1.0 - i * 0.05)
        for i in range(10)
    ]
    s1 = select_pilot_subset(records, max_repos=5, min_confidence=0.5, seed=42)
    s2 = select_pilot_subset(records, max_repos=5, min_confidence=0.5, seed=42)
    assert [r["repo_key"] for r in s1] == [r["repo_key"] for r in s2]
    assert [r["pilot_rank"] for r in s1] == [r["pilot_rank"] for r in s2]


def test_select_pilot_subset_empty():
    selected = select_pilot_subset([], max_repos=5, min_confidence=0.5, seed=0)
    assert selected == []
