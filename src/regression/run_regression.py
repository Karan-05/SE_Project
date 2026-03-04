"""Train and evaluate regression models for submission count + winning score."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

import warnings

import matplotlib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import HuberRegressor, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.regression.build_dataset import FeatureConfig, build_regression_splits
from src.utils.metrics import regression_metrics
from src.utils.reporting import write_metadata
from src.utils.tables import write_latex_table

warnings.filterwarnings("ignore", category=ConvergenceWarning)
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

LOGGER = logging.getLogger(__name__)


def _build_preprocessor(config: FeatureConfig) -> ColumnTransformer:
    transformers = []
    if config.text_col:
        transformers.append(
            (
                "text",
                TfidfVectorizer(max_features=2048, ngram_range=(1, 2)),
                config.text_col,
            )
        )
    if config.numeric_cols:
        transformers.append(("numeric", StandardScaler(), config.numeric_cols))
    if config.time_cols:
        transformers.append(("time", StandardScaler(), config.time_cols))
    if config.categorical_cols:
        transformers.append(
            ("categorical", OneHotEncoder(handle_unknown="ignore"), config.categorical_cols)
        )
    return ColumnTransformer(transformers, remainder="drop", sparse_threshold=0.0)


def _plot_predictions(y_true: np.ndarray, y_pred: np.ndarray, out_path: Path, title: str) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].scatter(y_true, y_pred, alpha=0.6, edgecolors="none")
    min_val = min(y_true.min(), y_pred.min())
    max_val = max(y_true.max(), y_pred.max())
    axes[0].plot([min_val, max_val], [min_val, max_val], "k--", linewidth=1)
    axes[0].set_xlabel("True")
    axes[0].set_ylabel("Predicted")
    axes[0].set_title(f"{title} — Scatter")
    residuals = y_true - y_pred
    axes[1].hist(residuals, bins=30, color="#4c72b0", alpha=0.8)
    axes[1].set_title(f"{title} — Residuals")
    axes[1].set_xlabel("Residual")
    axes[1].set_ylabel("Count")
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def _train_models(
    target: str,
    splits,
    feature_cfg: FeatureConfig,
    seed: int,
) -> Tuple[List[Dict[str, float]], pd.DataFrame, Tuple[np.ndarray, np.ndarray]]:
    models = {
        "ridge": Ridge(alpha=1.0),
        "random_forest": RandomForestRegressor(n_estimators=300, random_state=seed, n_jobs=-1),
        "huber": HuberRegressor(epsilon=1.35, max_iter=1000),
    }
    metrics_records: List[Dict[str, float]] = []
    preds_frames: List[pd.DataFrame] = []
    best_score = float("-inf")
    best_payload: Tuple[np.ndarray, np.ndarray] = (np.array([]), np.array([]))
    for model_name, base_model in models.items():
        pipeline = Pipeline(
            [
                ("preprocess", _build_preprocessor(feature_cfg)),
                ("regressor", clone(base_model)),
            ]
        )
        pipeline.fit(splits.X_train, splits.y_train[target])
        val_pred = pipeline.predict(splits.X_val)
        val_metrics = regression_metrics(splits.y_val[target].to_numpy(), val_pred, target_name=target)
        val_metrics.update({"model": model_name, "split": "val"})
        metrics_records.append(val_metrics)
        test_pred = pipeline.predict(splits.X_test)
        test_metrics = regression_metrics(splits.y_test[target].to_numpy(), test_pred, target_name=target)
        test_metrics.update({"model": model_name, "split": "test"})
        metrics_records.append(test_metrics)
        preds_frames.append(
            pd.DataFrame(
                {
                    "target": target,
                    "model": model_name,
                    "split": "test",
                    "y_true": splits.y_test[target].to_numpy(),
                    "y_pred": test_pred,
                }
            )
        )
        if val_metrics["r2"] > best_score:
            best_score = val_metrics["r2"]
            best_payload = (splits.y_test[target].to_numpy(), test_pred)
    preds = pd.concat(preds_frames, ignore_index=True)
    return metrics_records, preds, best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regression baselines for continuous targets.")
    default_out = Path("reports") / "regression"
    parser.add_argument("--out_dir", type=Path, default=default_out, help="Directory for outputs")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    splits = build_regression_splits(seed=args.seed)
    metrics_all: List[Dict[str, float]] = []
    preds_frames: List[pd.DataFrame] = []
    scatter_payloads: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for target in ["submission_count", "winning_score"]:
        target_metrics, target_preds, payload = _train_models(target, splits, splits.feature_config, args.seed)
        metrics_all.extend(target_metrics)
        preds_frames.append(target_preds)
        scatter_payloads[target] = payload

    metrics_df = pd.DataFrame(metrics_all)
    metrics_json = args.out_dir / "regression_metrics.json"
    metrics_json.write_text(json.dumps(metrics_all, indent=2), encoding="utf-8")
    preds_df = pd.concat(preds_frames, ignore_index=True)
    preds_df.to_csv(args.out_dir / "preds_test.csv", index=False)
    test_metrics = metrics_df[metrics_df["split"] == "test"].copy()
    write_latex_table(test_metrics, args.out_dir / "table_regression.tex")

    _plot_predictions(
        *scatter_payloads["submission_count"], args.out_dir / "fig_scatter_submissions.png", "Submission count"
    )
    _plot_predictions(
        *scatter_payloads["winning_score"], args.out_dir / "fig_scatter_winning_score.png", "Winning score"
    )

    write_metadata(
        args.out_dir,
        seeds=[args.seed],
        config={"seed": args.seed, "targets": ["submission_count", "winning_score"]},
        inputs=[Path(__file__), Path(__file__).with_name("build_dataset.py")],
    )
    LOGGER.info("Regression evaluation complete → %s", args.out_dir)


if __name__ == "__main__":
    main()
