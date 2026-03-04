"""Dataset builder for regression targets."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import pandas as pd
from sklearn.model_selection import train_test_split

from src.config import PathConfig, SupervisedConfig

NUMERIC_BASE = ["prize", "difficulty", "duration_days", "num_registrants", "local_time_load"]
CATEGORICAL_BASE = ["track", "platform", "company"]


@dataclass
class FeatureConfig:
    text_col: str
    numeric_cols: List[str]
    categorical_cols: List[str]
    time_cols: List[str]


@dataclass
class RegressionSplits:
    X_train: pd.DataFrame
    X_val: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.DataFrame
    y_val: pd.DataFrame
    y_test: pd.DataFrame
    feature_config: FeatureConfig


def _load_tasks(processed_dir: Path) -> pd.DataFrame:
    pq_path = processed_dir / "tasks.parquet"
    if pq_path.exists():
        return pd.read_parquet(pq_path)
    csv_path = processed_dir / "tasks.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path)
    raise FileNotFoundError(f"Unable to find tasks data under {processed_dir}")


def _prepare_features(tasks: pd.DataFrame) -> Tuple[pd.DataFrame, FeatureConfig]:
    df = tasks.copy()
    df["text"] = (
        df.get("title", "").fillna("")
        + " "
        + df.get("description", "").fillna("")
        + " "
        + df.get("tags", "").fillna("")
    )
    if "posted_time" in df.columns:
        df["posted_time"] = pd.to_datetime(df["posted_time"])
    else:
        df["posted_time"] = pd.Timestamp("2020-01-01")
    df["posted_month"] = df["posted_time"].dt.month
    df["posted_dow"] = df["posted_time"].dt.dayofweek
    numeric_cols = [col for col in NUMERIC_BASE if col in df.columns]
    categorical_cols = [col for col in CATEGORICAL_BASE if col in df.columns]
    time_cols = [col for col in ["posted_month", "posted_dow"] if col in df.columns]
    for col in numeric_cols:
        df[col] = df[col].fillna(df[col].median())
    for col in categorical_cols:
        df[col] = df[col].fillna("unknown")
    features = df[numeric_cols + categorical_cols + time_cols + ["text"]].copy()
    feat_cfg = FeatureConfig(
        text_col="text",
        numeric_cols=numeric_cols,
        categorical_cols=categorical_cols,
        time_cols=time_cols,
    )
    return features, feat_cfg


def build_regression_splits(
    processed_dir: Path | None = None,
    seed: int = 42,
    config: SupervisedConfig | None = None,
) -> RegressionSplits:
    path_cfg = PathConfig()
    processed_dir = processed_dir or path_cfg.processed_data
    cfg = config or SupervisedConfig()
    tasks = _load_tasks(processed_dir)
    required_targets = {"num_submissions": "submission_count", "winning_score": "winning_score"}
    missing_targets = [col for col in required_targets if col not in tasks.columns]
    if missing_targets:
        raise RuntimeError(
            f"Missing regression target columns: {missing_targets}. Required columns: {list(required_targets)}"
        )
    tasks = tasks.dropna(subset=required_targets.keys())
    features, feature_cfg = _prepare_features(tasks)
    targets = tasks[list(required_targets.keys())].rename(columns=required_targets)

    X_train_val, X_test, y_train_val, y_test = train_test_split(
        features, targets, test_size=cfg.test_size, random_state=seed
    )
    val_fraction = cfg.val_size / max(1e-6, (1 - cfg.test_size))
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val, y_train_val, test_size=val_fraction, random_state=seed
    )
    return RegressionSplits(
        X_train=X_train.reset_index(drop=True),
        X_val=X_val.reset_index(drop=True),
        X_test=X_test.reset_index(drop=True),
        y_train=y_train.reset_index(drop=True),
        y_val=y_val.reset_index(drop=True),
        y_test=y_test.reset_index(drop=True),
        feature_config=feature_cfg,
    )


__all__ = ["RegressionSplits", "FeatureConfig", "build_regression_splits"]
