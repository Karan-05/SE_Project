"""Selection helpers for assembling the 100-repo pool."""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .types import RepoCandidate
from .utils import normalize_language, now_utc_iso, write_json, write_jsonl


@dataclass(slots=True)
class SelectionConfig:
    target_size: int
    min_stars: int
    max_stars: int | None
    exclude_archived: bool
    require_tests: bool
    require_build_files: bool
    max_per_owner: int
    seed: int
    languages: list[str]
    per_language_targets: dict[str, int]


def load_candidate_file(path: Path) -> list[RepoCandidate]:
    candidates: list[RepoCandidate] = []
    if not path.exists():
        return candidates
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            candidates.append(RepoCandidate.from_dict(payload))
    return candidates


def parse_language_targets(
    languages: Sequence[str],
    target_size: int,
    overrides: dict[str, int] | None = None,
) -> dict[str, int]:
    normalized = [normalize_language(lang) for lang in languages if lang]
    normalized = [lang for lang in normalized if lang]
    if overrides:
        ordered = {normalize_language(lang): count for lang, count in overrides.items()}
        return ordered
    if not normalized:
        return {"python": target_size}
    base = target_size // len(normalized)
    remainder = target_size % len(normalized)
    targets: dict[str, int] = {}
    for idx, language in enumerate(normalized):
        targets[language] = base + (1 if idx < remainder else 0)
    return targets


def filter_candidates(
    candidates: Sequence[RepoCandidate],
    config: SelectionConfig,
) -> tuple[list[RepoCandidate], Counter]:
    filtered: list[RepoCandidate] = []
    filter_counts: Counter = Counter()
    for candidate in candidates:
        reasons: list[str] = []
        if candidate.stars < config.min_stars:
            reasons.append("min_stars")
        if config.max_stars is not None and candidate.stars > config.max_stars:
            reasons.append("max_stars")
        if config.exclude_archived and candidate.archived:
            reasons.append("archived")
        if config.require_tests and not candidate.has_tests:
            reasons.append("missing_tests")
        if config.require_build_files and not candidate.has_build_files:
            reasons.append("missing_build_files")
        if reasons:
            filter_counts.update(reasons)
            continue
        filtered.append(candidate)
    return filtered, filter_counts


def language_bucket(candidate: RepoCandidate, language_targets: dict[str, int]) -> str:
    normalized = normalize_language(candidate.language)
    if normalized in language_targets:
        return normalized
    return "other"


def enforce_owner_cap(
    candidate: RepoCandidate,
    owner_counts: dict[str, int],
    max_per_owner: int,
) -> bool:
    owner_key = f"{candidate.host.lower()}/{candidate.owner.lower()}"
    if max_per_owner > 0 and owner_counts.get(owner_key, 0) >= max_per_owner:
        return False
    owner_counts[owner_key] = owner_counts.get(owner_key, 0) + 1
    return True


def select_pool(
    candidates: Sequence[RepoCandidate],
    config: SelectionConfig,
) -> tuple[list[RepoCandidate], list[RepoCandidate], Counter]:
    filtered, filter_counts = filter_candidates(candidates, config)
    per_language_counts = Counter()
    language_targets = config.per_language_targets
    owner_counts: dict[str, int] = defaultdict(int)
    selected: list[RepoCandidate] = []
    used_keys: set[str] = set()
    rng = random.Random(config.seed)
    sorted_candidates = list(filtered)
    rng.shuffle(sorted_candidates)
    sorted_candidates.sort(key=lambda c: (-c.suitability_score, -c.stars, c.repo_key))
    buckets: dict[str, list[RepoCandidate]] = defaultdict(list)
    for candidate in sorted_candidates:
        bucket = language_bucket(candidate, language_targets)
        buckets[bucket].append(candidate)

    for language, target in language_targets.items():
        bucket = buckets.get(language, [])
        for candidate in bucket:
            if candidate.repo_key in used_keys:
                continue
            if not enforce_owner_cap(candidate, owner_counts, config.max_per_owner):
                continue
            selected.append(candidate)
            used_keys.add(candidate.repo_key)
            per_language_counts[language] += 1
            candidate.selection_rank = len(selected)
            if per_language_counts[language] >= target or len(selected) >= config.target_size:
                break

    if len(selected) < config.target_size:
        remaining = [candidate for candidate in sorted_candidates if candidate.repo_key not in used_keys]
        for candidate in remaining:
            if len(selected) >= config.target_size:
                break
            bucket = language_bucket(candidate, language_targets)
            if not enforce_owner_cap(candidate, owner_counts, config.max_per_owner):
                continue
            selected.append(candidate)
            used_keys.add(candidate.repo_key)
            per_language_counts[bucket] += 1
            candidate.selection_rank = len(selected)

    return selected, filtered, filter_counts


def build_selection_summary(
    input_candidates: Sequence[RepoCandidate],
    filtered_candidates: Sequence[RepoCandidate],
    selected: Sequence[RepoCandidate],
    config: SelectionConfig,
    filter_counts: Counter,
) -> dict[str, object]:
    language_counts = Counter(language_bucket(candidate, config.per_language_targets) for candidate in selected)
    owner_counts = Counter(f"{candidate.host}/{candidate.owner}" for candidate in selected)
    language_target_summary: dict[str, dict[str, int]] = {
        language: {
            "target": config.per_language_targets.get(language, 0),
            "selected": language_counts.get(language, 0),
        }
        for language in config.per_language_targets
    }
    for bucket, count in language_counts.items():
        if bucket not in language_target_summary:
            language_target_summary[bucket] = {"target": 0, "selected": count}
    summary = {
        "generated_at": now_utc_iso(),
        "input_candidates": len(input_candidates),
        "eligible_candidates": len(filtered_candidates),
        "selected": len(selected),
        "target": config.target_size,
        "filters": dict(filter_counts),
        "language_summary": language_target_summary,
        "owner_cap": config.max_per_owner,
        "owner_distribution": owner_counts.most_common(10),
        "config": {
            "min_stars": config.min_stars,
            "max_stars": config.max_stars,
            "exclude_archived": config.exclude_archived,
            "require_tests": config.require_tests,
            "require_build_files": config.require_build_files,
            "seed": config.seed,
            "languages": config.languages,
        },
    }
    return summary


def write_selection_outputs(
    selected: Sequence[RepoCandidate],
    output_dir: Path,
    target_size: int,
    summary: dict[str, object],
) -> None:
    base_name = f"repo_pool_{target_size}"
    write_jsonl(output_dir / f"{base_name}.jsonl", (candidate.as_dict() for candidate in selected))
    write_json(output_dir / f"{base_name}_summary.json", summary)
    write_json(output_dir / "repo_selection_summary.json", summary)
