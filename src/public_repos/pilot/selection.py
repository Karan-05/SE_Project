"""Helper utilities for selecting and scoring pilot repos."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Mapping, Sequence


def repo_owner(entry: Mapping[str, object]) -> str:
    repo_key = str(entry.get("repo_key") or "")
    parts = repo_key.split("/")
    if len(parts) >= 3:
        return parts[-2].lower()
    return repo_key.lower()


def language_of(entry: Mapping[str, object]) -> str:
    return str(entry.get("language") or entry.get("language_hint") or "unknown").lower()


def build_systems_of(entry: Mapping[str, object]) -> list[str]:
    values: Iterable[object] = entry.get("build_systems") or entry.get("detected_build_systems") or []
    return [str(value).lower() for value in values if value]


def test_frameworks_of(entry: Mapping[str, object]) -> list[str]:
    values: Iterable[object] = entry.get("test_frameworks") or entry.get("detected_test_frameworks") or []
    return [str(value).lower() for value in values if value]


def runnable_confidence(entry: Mapping[str, object]) -> float:
    value = entry.get("runnable_confidence")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def selection_reason(
    entry: Mapping[str, object],
    *,
    adds_language: bool,
    adds_build_system: bool,
    adds_test_framework: bool,
) -> str:
    reasons: list[str] = [f"confidence={runnable_confidence(entry):.2f}"]
    if adds_language:
        reasons.append(f"adds_language={language_of(entry)}")
    if adds_build_system:
        reasons.append("adds_build_system")
    if adds_test_framework:
        reasons.append("adds_test_framework")
    owner = repo_owner(entry)
    if owner:
        reasons.append(f"owner={owner}")
    notes = str(entry.get("notes") or "").strip().lower()
    if "flake" in notes:
        reasons.append("watch_flakiness_flagged")
    return "; ".join(reasons)


@dataclass(slots=True)
class DiversityScore:
    lang_count: int
    build_count: int
    test_count: int
    confidence: float

    def rank_tuple(self) -> tuple:
        return (self.lang_count, self.build_count, self.test_count, -self.confidence)


def compute_diversity_score(
    entry: Mapping[str, object],
    *,
    lang_counts: Mapping[str, int],
    build_counts: Mapping[str, int],
    test_counts: Mapping[str, int],
) -> DiversityScore:
    lang = language_of(entry)
    builds = build_systems_of(entry)
    tests = test_frameworks_of(entry)
    lang_count = lang_counts.get(lang, 0)
    build_count = int(mean([build_counts.get(b, 0) for b in builds])) if builds else 0
    test_count = int(mean([test_counts.get(t, 0) for t in tests])) if tests else 0
    return DiversityScore(
        lang_count=lang_count,
        build_count=build_count,
        test_count=test_count,
        confidence=runnable_confidence(entry),
    )


def merge_manifest_entry(
    manifest_entry: Mapping[str, object],
    subset_entry: Mapping[str, object] | None = None,
) -> dict[str, object]:
    merged: dict[str, object] = {}
    if manifest_entry:
        merged.update(manifest_entry)
    if subset_entry:
        merged.update(subset_entry)
    return merged


def normalize_pilot_rank(entries: Sequence[dict[str, object]]) -> None:
    for idx, entry in enumerate(entries, start=1):
        entry["pilot_rank"] = idx
