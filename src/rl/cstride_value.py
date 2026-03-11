"""Lightweight value regression model for counterfactual STRIDE."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CStrideValueConfig:
    """Hyper-parameters for the value approximation model."""

    lr: float = 1e-3
    l2: float = 1e-4


class CStrideValueModel:
    """Single-layer regression model trained with online gradient descent."""

    def __init__(self, feature_dim: int, config: CStrideValueConfig | None = None, seed: int | None = None) -> None:
        self.config = config or CStrideValueConfig()
        rng = np.random.default_rng(seed)
        self.weights = rng.normal(scale=0.05, size=(feature_dim,)).astype(np.float32)
        self.bias = 0.0

    def predict(self, features: np.ndarray) -> float:
        return float(np.dot(self.weights, features) + self.bias)

    def update(self, features: np.ndarray, target: float, weight: float = 1.0) -> None:
        pred = self.predict(features)
        error = (target - pred) * weight
        error = float(np.clip(error, -10.0, 10.0))
        self.weights += self.config.lr * error * features - self.config.l2 * self.weights
        self.bias += self.config.lr * error


__all__ = ["CStrideValueConfig", "CStrideValueModel"]
