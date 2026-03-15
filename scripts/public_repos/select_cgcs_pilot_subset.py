#!/usr/bin/env python3
"""Select a small, diverse subset of repos from the CGCS seed pool for the pilot benchmark.

Produces:
  <out-dir>/pilot_subset.jsonl          — selected repo entries
  <out-dir>/pilot_subset_summary.json   — selection statistics
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Sequence


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _owner_of(entry: Dict[str, Any]) -> str:
    repo_key = str(entry.get("repo_key") or "")
    parts = repo_key.split("/")
    # github.com/owner/repo  →  owner
    if len(parts) >= 3:
        return parts[-2].lower()
    return repo_key.lower()


def _lang_of(entry: Dict[str, Any]) -> str:
    return str(entry.get("language") or "unknown").lower()


def _build_systems(entry: Dict[str, Any]) -> Sequence[str]:
    values = entry.get("build_systems") or entry.get("detected_build_systems") or []
    return [str(v).lower() for v in values if v]


def _test_frameworks(entry: Dict[str, Any]) -> Sequence[str]:
    values = entry.get("test_frameworks") or entry.get("detected_test_frameworks") or []
    return [str(v).lower() for v in values if v]


def _size_penalty(entry: Dict[str, Any]) -> int:
    """Crude heuristic to avoid giant / flaky repos based on metadata."""
    build_files = len(entry.get("detected_build_files") or [])
    test_paths = len(entry.get("detected_test_paths") or [])
    repo_size = int(entry.get("repo_size_bytes") or 0)
    penalty = 0
    if build_files > 20:
        penalty += 1
    if test_paths > 100:
        penalty += 1
    if repo_size and repo_size > 200_000_000:
        penalty += 1
    return penalty


def _selection_reason(
    entry: Dict[str, Any],
    *,
    lang_new: bool,
    build_new: bool,
    tests_new: bool,
) -> str:
    parts: List[str] = []
    parts.append(f"confidence={float(entry.get('runnable_confidence') or 0):.2f}")
    if lang_new:
        parts.append(f"adds_new_language={_lang_of(entry)}")
    if build_new:
        parts.append("adds_new_build_system")
    if tests_new:
        parts.append("adds_new_test_framework")
    owner = _owner_of(entry)
    if owner:
        parts.append(f"unique_owner={owner}")
    notes = str(entry.get("notes") or "").strip().lower()
    if "flake" in notes or "unstable" in notes:
        parts.append("watch_flakiness_flagged")
    return "; ".join(parts)


def select_pilot_subset(
    records: List[Dict[str, Any]],
    *,
    max_repos: int,
    min_confidence: float,
    seed: int,
) -> List[Dict[str, Any]]:
    """Return a diverse, deterministic subset of at most *max_repos* entries."""
    rng = random.Random(seed)

    # 1. Filter by minimum runnable confidence
    eligible = [r for r in records if float(r.get("runnable_confidence") or 0) >= min_confidence]

    if not eligible:
        return []

    # 2. Sort by confidence descending, then by repo_key for determinism
    eligible.sort(key=lambda r: (-float(r.get("runnable_confidence") or 0), str(r.get("repo_key") or "")))

    # 3. Greedy diversity selection: prefer languages/build systems/test frameworks, cap owner at 1
    lang_counts: Counter[str] = Counter()
    build_counts: Counter[str] = Counter()
    test_counts: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()
    selected: List[Dict[str, Any]] = []
    selection_reasons: Dict[str, str] = {}

    remaining = eligible[:]
    while remaining and len(selected) < max_repos:
        best_entry: Dict[str, Any] | None = None
        best_score: tuple | None = None
        for entry in remaining:
            owner = _owner_of(entry)
            if owner_counts[owner] >= 1:
                continue
            lang = _lang_of(entry)
            builds = _build_systems(entry)
            tests = _test_frameworks(entry)
            confidence = float(entry.get("runnable_confidence") or 0)
            diversity_score = (
                lang_counts[lang],
                min((build_counts[b] for b in builds), default=0),
                min((test_counts[t] for t in tests), default=0),
            )
            penalty = _size_penalty(entry)
            score = (
                diversity_score,
                penalty,
                -confidence,
                str(entry.get("repo_key") or ""),
            )
            if best_score is None or score < best_score:
                best_entry = entry
                best_score = score
        if best_entry is None:
            break
        remaining.remove(best_entry)
        lang = _lang_of(best_entry)
        builds = list(_build_systems(best_entry))
        tests = list(_test_frameworks(best_entry))
        owner = _owner_of(best_entry)

        lang_new = lang_counts[lang] == 0
        build_new = any(build_counts[b] == 0 for b in builds) if builds else False
        tests_new = any(test_counts[t] == 0 for t in tests) if tests else False
        selection_reasons[str(best_entry.get("repo_key"))] = _selection_reason(
            best_entry,
            lang_new=lang_new,
            build_new=build_new,
            tests_new=tests_new,
        )

        lang_counts[lang] += 1
        for b in builds:
            build_counts[b] += 1
        for t in tests:
            test_counts[t] += 1
        owner_counts[owner] += 1
        selected.append(best_entry)

    for rank, entry in enumerate(selected, start=1):
        entry["pilot_rank"] = rank
        entry["selection_reason"] = selection_reasons.get(str(entry.get("repo_key")), "")
        entry["detected_build_systems"] = list(dict.fromkeys(_build_systems(entry)))
        entry["detected_test_frameworks"] = list(dict.fromkeys(_test_frameworks(entry)))
    return selected


def build_summary(
    selected: List[Dict[str, Any]],
    pool_size: int,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    lang_counts: Counter[str] = Counter(_lang_of(r) for r in selected)
    confidences = [float(r.get("runnable_confidence") or 0) for r in selected]
    build_counts = Counter(
        system for r in selected for system in _build_systems(r)
    )
    test_counts = Counter(
        framework for r in selected for framework in _test_frameworks(r)
    )
    return {
        "pool_size": pool_size,
        "selected_count": len(selected),
        "max_repos": args.max_repos,
        "min_confidence": args.min_confidence,
        "seed": args.seed,
        "languages": dict(lang_counts),
        "build_systems": dict(build_counts),
        "test_frameworks": dict(test_counts),
        "confidence_min": min(confidences) if confidences else 0.0,
        "confidence_max": max(confidences) if confidences else 0.0,
        "confidence_avg": mean(confidences) if confidences else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/public_repos/cgcs_seed_pool.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/public_repos/pilot"))
    parser.add_argument("--max-repos", type=int, default=10)
    parser.add_argument("--min-confidence", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = _load_jsonl(args.input)
    print(f"[pilot-subset] Loaded {len(records)} entries from {args.input}")

    selected = select_pilot_subset(
        records,
        max_repos=args.max_repos,
        min_confidence=args.min_confidence,
        seed=args.seed,
    )
    print(f"[pilot-subset] Selected {len(selected)} repos")

    out_jsonl = args.out_dir / "cgcs_pilot_subset.jsonl"
    out_summary = args.out_dir / "cgcs_pilot_subset_summary.json"
    _write_jsonl(out_jsonl, selected)
    _write_json(out_summary, build_summary(selected, len(records), args))
    print(f"[pilot-subset] Written → {out_jsonl}")
    print(f"[pilot-subset] Summary → {out_summary}")


if __name__ == "__main__":
    main()
