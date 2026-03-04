from __future__ import annotations

from src.experiments.topcoder.sampling import select_sample


def _build_tasks(count: int, with_tests: int) -> list[dict]:
    tasks = []
    for idx in range(count):
        has_tests = idx < with_tests
        tasks.append({"id": f"task_{idx}", "metadata": {"tests": [{"name": "t"}]} if has_tests else {}})
    return tasks


def test_select_sample_stratified() -> None:
    tasks = _build_tasks(20, 10)
    sample, counts = select_sample(tasks, 8, "stratified", seed=42, synth_fraction=0.25)
    assert len(sample) == 8
    assert counts["with_tests"] >= counts["without_tests"]


def test_select_sample_random_exact_size() -> None:
    tasks = _build_tasks(5, 2)
    sample, counts = select_sample(tasks, 5, "random", seed=1)
    assert len(sample) == 5
    assert counts["total"] == 5


def test_select_sample_guarantees_min_with_tests() -> None:
    tasks = _build_tasks(50, 10)
    sample, counts = select_sample(tasks, 10, "random", seed=7, min_with_tests=3)
    assert len(sample) == 10
    assert counts["with_tests"] >= 3
