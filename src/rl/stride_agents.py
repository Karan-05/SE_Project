"""Gate and residual policies for STRIDE."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import numpy as np


@dataclass
class StrideGateConfig:
    """Hyper-parameters for the override gate."""

    hidden_dim: int = 128
    lr: float = 5e-3
    l2: float = 1e-4
    include_teacher_confidence: bool = True
    include_uncertainty_features: bool = True
    min_override_prob: float = 0.01
    max_override_prob: float = 0.85


class StrideGate:
    """Two-layer perceptron trained with logistic loss."""

    def __init__(self, feature_dim: int, config: StrideGateConfig | None = None, seed: int | None = None) -> None:
        self.config = config or StrideGateConfig()
        rng = np.random.default_rng(seed)
        hidden = self.config.hidden_dim
        limit = np.sqrt(6.0 / (feature_dim + hidden))
        self.w1 = rng.uniform(-limit, limit, size=(hidden, feature_dim)).astype(np.float32)
        self.b1 = np.zeros(hidden, dtype=np.float32)
        self.w2 = rng.uniform(-limit, limit, size=(hidden,)).astype(np.float32)
        self.b2 = 0.0

    def _forward(self, features: np.ndarray) -> tuple[np.ndarray, float]:
        hidden = np.tanh(self.w1 @ features + self.b1)
        logit = float(self.w2 @ hidden + self.b2)
        prob = 1.0 / (1.0 + np.exp(-logit))
        return hidden, prob

    def predict(self, features: np.ndarray) -> float:
        _, prob = self._forward(features)
        return float(np.clip(prob, self.config.min_override_prob, self.config.max_override_prob))

    def update(self, features: np.ndarray, label: float, weight: float = 1.0) -> None:
        hidden, prob = self._forward(features)
        error = (label - prob) * weight
        grad_w2 = error * hidden
        grad_b2 = error
        delta_hidden = error * self.w2 * (1 - hidden**2)
        grad_w1 = np.outer(delta_hidden, features)
        grad_b1 = delta_hidden
        self.w2 += self.config.lr * grad_w2 - self.config.l2 * self.w2
        self.b2 += self.config.lr * grad_b2
        self.w1 += self.config.lr * grad_w1 - self.config.l2 * self.w1
        self.b1 += self.config.lr * grad_b1


@dataclass
class StrideResidualConfig:
    """Hyper-parameters for the residual action selector."""

    lr: float = 3e-3
    entropy_bonus: float = 0.01
    epsilon: float = 0.05


class StrideResidualPolicy:
    """Softmax policy optimized with REINFORCE-style updates."""

    def __init__(self, feature_dim: int, action_dim: int, config: StrideResidualConfig | None = None, seed: int | None = None) -> None:
        self.config = config or StrideResidualConfig()
        self.action_dim = action_dim
        rng = np.random.default_rng(seed)
        self.weights = rng.normal(scale=0.1, size=(action_dim, feature_dim)).astype(np.float32)
        self.bias = np.zeros(action_dim, dtype=np.float32)

    def logits(self, features: np.ndarray) -> np.ndarray:
        return self.weights @ features + self.bias

    def _probs(self, logits: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
        masked_logits = np.array(logits, copy=True)
        if mask is not None:
            invalid = mask <= 0
            masked_logits[invalid] = -np.inf
        finite = np.isfinite(masked_logits)
        if not np.any(finite):
            return np.ones_like(masked_logits) / len(masked_logits)
        shift = np.max(masked_logits[finite])
        shifted = masked_logits - shift
        exp = np.zeros_like(masked_logits, dtype=np.float64)
        exp[finite] = np.exp(shifted[finite])
        denom = np.sum(exp)
        if denom <= 0:
            return np.ones_like(exp) / len(exp)
        return (exp / denom).astype(np.float32)

    def act(self, features: np.ndarray, mask: Optional[np.ndarray] = None, greedy: bool = False) -> int:
        logits = self.logits(features)
        probs = self._probs(logits, mask)
        if not greedy and np.random.rand() < self.config.epsilon:
            valid = np.where((mask > 0) if mask is not None else np.ones_like(probs, dtype=bool))[0]
            if len(valid) == 0:
                valid = np.arange(self.action_dim)
            return int(np.random.choice(valid))
        if greedy:
            if mask is not None:
                masked = np.where(mask > 0)[0]
                if len(masked) == 0:
                    return int(np.argmax(probs))
                values = probs[masked]
                return int(masked[int(np.argmax(values))])
            return int(np.argmax(probs))
        return int(np.random.choice(self.action_dim, p=probs))

    def update(self, features: np.ndarray, action: int, advantage: float, mask: Optional[np.ndarray] = None) -> None:
        logits = self.logits(features)
        probs = self._probs(logits, mask)
        one_hot = np.zeros_like(probs)
        one_hot[action] = 1.0
        grad = advantage * (one_hot - probs)
        self.weights += self.config.lr * np.outer(grad, features)
        self.bias += self.config.lr * grad
        self.bias += self.config.entropy_bonus * (-probs + 1.0 / len(probs))

    def imitate(self, features: np.ndarray, target_action: int, weight: float = 1.0) -> None:
        logits = self.logits(features)
        probs = self._probs(logits, None)
        one_hot = np.zeros_like(probs)
        one_hot[target_action] = 1.0
        grad = weight * (one_hot - probs)
        self.weights += self.config.lr * np.outer(grad, features)
        self.bias += self.config.lr * grad


def build_stride_features(
    observation: np.ndarray,
    teacher_index: int,
    action_dim: int,
    manager_features: Dict[str, float],
    include_confidence: bool = True,
    include_uncertainty: bool = True,
    extra_features: Sequence[float] | None = None,
) -> np.ndarray:
    """Compose a feature vector used by the gate and residual policy."""

    macro_vec = np.zeros(action_dim, dtype=np.float32)
    if 0 <= teacher_index < action_dim:
        macro_vec[teacher_index] = 1.0
    features = [observation.astype(np.float32), macro_vec]
    if include_confidence:
        features.append(np.array([manager_features.get("success_probability", 0.0)], dtype=np.float32))
    if include_uncertainty:
        features.append(np.array([manager_features.get("uncertainty", 0.0)], dtype=np.float32))
    features.append(np.array([manager_features.get("expected_cost", 0.0)], dtype=np.float32))
    if extra_features is not None:
        features.append(np.asarray(extra_features, dtype=np.float32))
    return np.concatenate(features).astype(np.float32)
