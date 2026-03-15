"""Leakage detection utilities for fine-tuning datasets."""
from __future__ import annotations

from typing import Iterable, List, Sequence, Set


def detect_task_overlap(train_tasks: Iterable[str], valid_tasks: Iterable[str]) -> List[str]:
    """Return task IDs present in both splits."""

    train_set = set(train_tasks)
    valid_set = set(valid_tasks)
    return sorted(train_set & valid_set)


def validate_holdout_separation(train_tasks: Sequence[str], held_out: Set[str]) -> List[str]:
    """Identify held-out tasks that leaked into the training split."""

    return sorted({task for task in train_tasks if task in held_out})
