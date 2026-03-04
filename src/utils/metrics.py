"""Shared metric helpers for supervised, self-supervised, and RL stacks."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
    roc_auc_score,
)


def classification_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
    average: str = "binary",
    target_name: str | None = None,
) -> Dict[str, float]:
    """Return a dictionary of standard classification metrics."""

    y_pred = (y_prob >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average=average, zero_division=0
    )
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "log_loss": float(log_loss(y_true, np.clip(y_prob, 1e-6, 1 - 1e-6))),
        "roc_auc": float(roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else np.nan),
    }
    if target_name:
        metrics["target"] = target_name
    return metrics


def regression_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    target_name: str | None = None,
) -> Dict[str, float]:
    mse = mean_squared_error(y_true, y_pred)
    rmse = float(np.sqrt(mse))
    mae = mean_absolute_error(y_true, y_pred)
    r2 = r2_score(y_true, y_pred)
    metrics = {"rmse": float(rmse), "mae": float(mae), "r2": float(r2)}
    if target_name:
        metrics["target"] = target_name
    return metrics


def save_metrics(records: Iterable[Dict[str, float]], output_path: Path) -> pd.DataFrame:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(list(records))
    df.to_csv(output_path, index=False)
    return df


def summarize_rl_rewards(
    rewards: List[float],
    wins: List[int],
    starved: List[int],
    agent_name: str,
) -> Dict[str, float]:
    return {
        "agent": agent_name,
        "avg_reward": float(np.mean(rewards)),
        "std_reward": float(np.std(rewards)),
        "win_rate": float(np.mean(wins)),
        "starved_tasks": float(np.mean(starved)),
    }


__all__ = [
    "classification_metrics",
    "regression_metrics",
    "save_metrics",
    "summarize_rl_rewards",
]
