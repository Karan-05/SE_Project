"""Belief encoder and calibration helpers for AEGIS-RL."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, Tuple

import numpy as np

from .aegis_graph_memory import GraphSummary
from .aegis_state import AegisBeliefState


@dataclass
class BeliefEncoderConfig:
    """Hyper-parameters governing the belief encoder."""

    history_length: int = 12
    feature_dim: int = 32
    smoothing: float = 0.85
    calibration_lr: float = 0.05
    min_success_prob: float = 0.03
    max_success_prob: float = 0.97
    min_cost: float = 0.0
    max_cost: float = 1.0


class CalibrationAccumulator:
    """Tracks calibration calibration/alignment metrics."""

    def __init__(self) -> None:
        self.predictions: Deque[float] = deque(maxlen=256)
        self.outcomes: Deque[float] = deque(maxlen=256)
        self.cost_preds: Deque[float] = deque(maxlen=256)
        self.cost_targets: Deque[float] = deque(maxlen=256)

    def record(self, success_prob: float, outcome: float, cost_pred: float, realized_cost: float) -> None:
        self.predictions.append(float(success_prob))
        self.outcomes.append(float(outcome))
        self.cost_preds.append(float(cost_pred))
        self.cost_targets.append(float(realized_cost))

    def miscalibration(self) -> Dict[str, float]:
        if not self.predictions:
            return {"brier": 0.0, "cost_mae": 0.0}
        preds = np.array(self.predictions, dtype=np.float32)
        targets = np.array(self.outcomes, dtype=np.float32)
        brier = float(np.mean((preds - targets) ** 2))
        cost_mae = float(np.mean(np.abs(np.array(self.cost_preds) - np.array(self.cost_targets))))
        return {"brier": brier, "cost_mae": cost_mae}


class BeliefEncoder:
    """Transforms raw environment observations into belief states."""

    def __init__(self, observation_dim: int, config: BeliefEncoderConfig | None = None) -> None:
        self.config = config or BeliefEncoderConfig()
        self.history: Deque[np.ndarray] = deque(maxlen=self.config.history_length)
        rng = np.random.default_rng(2026)
        self._budget_dim = 6
        fused_dim = self.config.feature_dim + self._budget_dim
        self.success_weights = rng.uniform(-0.05, 0.05, size=fused_dim)
        self.cost_weights = rng.uniform(-0.05, 0.05, size=fused_dim)
        self.bias_success = 0.0
        self.bias_cost = 0.0
        self.calibration = CalibrationAccumulator()

    def reset(self) -> None:
        self.history.clear()

    def _sigmoid(self, x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-x))

    def encode(
        self,
        base_observation: np.ndarray,
        info: Dict[str, object],
        graph_summary: GraphSummary,
        budget_features: np.ndarray,
        option_history: Iterable[int],
    ) -> AegisBeliefState:
        obs = np.asarray(base_observation, dtype=np.float32)
        self.history.append(obs.copy())
        momentum = np.mean(np.stack(self.history, axis=0), axis=0) if self.history else obs
        graph_vec = graph_summary.as_array()
        features = np.concatenate([obs, momentum, graph_vec[: obs.shape[0] // 4]], axis=0)
        features = features[: self.config.feature_dim]
        pad = self.config.feature_dim - features.shape[0]
        if pad > 0:
            features = np.pad(features, (0, pad), mode="constant", constant_values=0.0)
        fused = np.concatenate([features, budget_features[: self._budget_dim]], axis=0)
        success_logit = float(np.dot(fused[: self.success_weights.shape[0]], self.success_weights) + self.bias_success)
        success_prob = float(self._sigmoid(np.array([success_logit]))[0])
        success_prob = float(
            np.clip(success_prob * self.config.smoothing + (1 - self.config.smoothing) * 0.5,  # type: ignore[arg-type]
                    self.config.min_success_prob,
                    self.config.max_success_prob)
        )

        cost_pred = float(np.dot(fused[: self.cost_weights.shape[0]], self.cost_weights) + self.bias_cost)
        cost_pred = float(np.clip(cost_pred, self.config.min_cost, self.config.max_cost))

        disagreement = info.get("uncertainty_summary", [0.0])
        disagreement_value = float(np.mean(disagreement)) if isinstance(disagreement, (list, tuple, np.ndarray)) else float(disagreement)
        history_tuple = tuple(int(x) for x in option_history)
        return AegisBeliefState(
            features=features.astype(np.float32),
            success_probability=success_prob,
            expected_cost_to_success=cost_pred,
            uncertainty_score=disagreement_value,
            history_window=history_tuple[-self.config.history_length :],
        )

    def update_calibration(self, outcome: bool, realized_cost: float, belief: AegisBeliefState) -> Dict[str, float]:
        error = float(outcome) - belief.success_probability
        self.bias_success += self.config.calibration_lr * error
        cost_error = realized_cost - belief.expected_cost_to_success
        self.bias_cost += self.config.calibration_lr * cost_error
        self.calibration.record(
            success_prob=belief.success_probability,
            outcome=float(outcome),
            cost_pred=belief.expected_cost_to_success,
            realized_cost=realized_cost,
        )
        return self.calibration.miscalibration()
