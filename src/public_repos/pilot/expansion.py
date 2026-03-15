"""Expansion and backfill helpers for the pilot subset."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from . import selection


@dataclass(slots=True)
class ReplacementDecision:
    repo_key: str
    reason: str
    entry: dict[str, object]
    replacement_for: str | None = None


def _eligible_candidates(
    seed_pool: Sequence[Mapping[str, object]],
    *,
    exclude_keys: set[str],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for record in seed_pool:
        repo_key = str(record.get("repo_key") or "")
        if not repo_key or repo_key in exclude_keys:
            continue
        candidates.append(dict(record))
    return candidates


def select_replacements(
    seed_pool: Sequence[Mapping[str, object]],
    *,
    current_entries: Sequence[Mapping[str, object]],
    attempted_keys: set[str],
    hard_blocked: set[str],
    max_new: int,
    rng_seed: int,
) -> list[ReplacementDecision]:
    if max_new <= 0:
        return []
    exclude = set(attempted_keys) | set(entry.get("repo_key") or "" for entry in current_entries) | set(hard_blocked)
    pool = _eligible_candidates(seed_pool, exclude_keys=exclude)
    if not pool:
        return []

    rng = random.Random(rng_seed)
    lang_counts: dict[str, int] = {}
    build_counts: dict[str, int] = {}
    test_counts: dict[str, int] = {}
    for entry in current_entries:
        lang = selection.language_of(entry)
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        for build in selection.build_systems_of(entry):
            build_counts[build] = build_counts.get(build, 0) + 1
        for tf in selection.test_frameworks_of(entry):
            test_counts[tf] = test_counts.get(tf, 0) + 1

    scored: list[tuple[tuple, dict[str, object]]] = []
    for record in pool:
        score = selection.compute_diversity_score(
            record,
            lang_counts=lang_counts,
            build_counts=build_counts,
            test_counts=test_counts,
        )
        scored.append((score.rank_tuple() + (rng.random(),), dict(record)))
    scored.sort(key=lambda item: item[0])

    replacements: list[ReplacementDecision] = []
    for _, entry in scored[:max_new]:
        lang = selection.language_of(entry)
        builds = selection.build_systems_of(entry)
        tests = selection.test_frameworks_of(entry)
        reason = selection.selection_reason(
            entry,
            adds_language=lang_counts.get(lang, 0) == 0,
            adds_build_system=any(build_counts.get(b, 0) == 0 for b in builds) if builds else False,
            adds_test_framework=any(test_counts.get(t, 0) == 0 for t in tests) if tests else False,
        )
        replacements.append(
            ReplacementDecision(
                repo_key=str(entry.get("repo_key") or ""),
                reason=reason,
                entry=entry,
            )
        )
    return replacements
