"""Sampling strategies for presentation-mode experiments."""
from __future__ import annotations

import random
from typing import Dict, List, Tuple


def select_sample(
    tasks: List[Dict],
    sample_size: int,
    strategy: str,
    seed: int,
    synth_fraction: float = 0.25,
    min_with_tests: int = 1,
) -> Tuple[List[Dict], Dict[str, int]]:
    """Return a deterministic sample with optional guaranteed coding coverage."""

    def _has_tests(task: Dict) -> bool:
        return bool(task.get("metadata", {}).get("tests"))

    def _count(selected: List[Dict]) -> Dict[str, int]:
        return {
            "total": len(selected),
            "with_tests": sum(1 for task in selected if _has_tests(task)),
            "without_tests": sum(1 for task in selected if not _has_tests(task)),
        }

    if sample_size <= 0 or sample_size >= len(tasks):
        return tasks, _count(tasks)
    rng = random.Random(seed)
    with_tests = [task for task in tasks if _has_tests(task)]
    without_tests = [task for task in tasks if not _has_tests(task)]
    if strategy == "stratified":
        synth_cap = min(int(sample_size * synth_fraction), len(without_tests))
        base_cap = max(sample_size - synth_cap, 0)
        selected: List[Dict] = []
        if with_tests:
            take = min(base_cap, len(with_tests))
            selected.extend(rng.sample(with_tests, take))
        if synth_cap and without_tests:
            selected.extend(rng.sample(without_tests, synth_cap))
        remaining = sample_size - len(selected)
        if remaining > 0:
            universe = [task for task in tasks if task not in selected]
            if universe:
                selected.extend(rng.sample(universe, min(remaining, len(universe))))
    else:
        selected = rng.sample(tasks, sample_size)
    counts = _count(selected)
    desired_with_tests = max(0, min(min_with_tests, sample_size, len(with_tests)))
    if desired_with_tests > counts["with_tests"] and with_tests:
        available = [task for task in with_tests if task not in selected]
        while counts["with_tests"] < desired_with_tests and available:
            candidate = rng.choice(available)
            available.remove(candidate)
            if len(selected) >= sample_size:
                replaceable = [idx for idx, task in enumerate(selected) if not _has_tests(task)]
                if replaceable:
                    idx = rng.choice(replaceable)
                else:
                    idx = rng.randrange(len(selected))
                selected[idx] = candidate
            else:
                selected.append(candidate)
            counts = _count(selected)
    else:
        counts = _count(selected)
    return selected, counts
