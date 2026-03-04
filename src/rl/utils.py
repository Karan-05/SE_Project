"""Utility helpers for RL modules (reproducibility + streaming stats)."""
from __future__ import annotations

import os
import random
from dataclasses import dataclass

import numpy as np

try:  # pragma: no cover - torch is optional
    import torch
except ImportError:  # pragma: no cover
    torch = None  # type: ignore


def set_global_seeds(seed: int) -> None:
    """Seed python, numpy, torch (if available), and hashing for reproducibility."""

    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
        if torch.cuda.is_available():  # pragma: no cover
            torch.cuda.manual_seed_all(seed)


@dataclass
class RunningStats:
    """Online mean/std estimator using Welford's algorithm."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def std(self) -> float:
        return float(np.sqrt(self.variance))


__all__ = ["set_global_seeds", "RunningStats"]
