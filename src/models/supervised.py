"""Supervised learning baselines for competition outcomes and market dynamics."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pickle
import numpy as np
import pandas as pd

try:  # optional plotting dependencies
    import matplotlib.pyplot as plt  # type: ignore
except ImportError:  # pragma: no cover
    plt = None

try:
    import seaborn as sns  # type: ignore
except ImportError:  # pragma: no cover
    sns = None
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import PathConfig, SupervisedConfig
from src.utils.metrics import classification_metrics, regression_metrics, save_metrics

logger = logging.getLogger(__name__)

if sns is not None:  # plot styling optional
    sns.set_style("whitegrid")


@dataclass
class DatasetBundle:
    tasks: pd.DataFrame
    market: pd.DataFrame


FEATURE_MODES = {
    "text_only": {"use_numeric": False, "use_categorical": False, "use_time": False, "use_embeddings": False},
    "text_metadata": {"use_numeric": True, "use_categorical": True, "use_time": False, "use_embeddings": False},
    "text_time": {"use_numeric": True, "use_categorical": True, "use_time": True, "use_embeddings": False},
    "multimodal": {"use_numeric": True, "use_categorical": True, "use_time": True, "use_embeddings": True},
}

NUMERIC_FEATURES = [
    "prize",
    "difficulty",
    "duration_days",
    "num_registrants",
    "num_submissions",
    "local_time_load",
    "market_num_tasks",
    "market_avg_prize",
    "market_avg_submissions",
    "market_starved_rate",
    "market_failed_rate",
    "market_dropped_rate",
]
CATEGORICAL_FEATURES = ["track", "platform", "company"]
TIME_FEATURES = ["posted_month", "posted_dow"]


class SupervisedExperiment:
    """Train and evaluate models across multiple targets and feature bundles."""

    def __init__(
        self,
        processed_dir: Path | None = None,
        config: SupervisedConfig | None = None,
        feature_mode: str = "multimodal",
    ) -> None:
        self.path_cfg = PathConfig()
        self.processed_dir = processed_dir or self.path_cfg.processed_data
        self.config = config or SupervisedConfig()
        self.feature_mode = feature_mode
        self.bundle = self._load_dataset()
        self.target_columns = set(self.config.classification_targets.keys()) | set(
            self.config.regression_targets.keys()
        )
        self.dataset = self._prepare_features()

    # ------------------------------------------------------------------
    def _read_table(self, name: str) -> pd.DataFrame:
        pq_path = self.processed_dir / f"{name}.parquet"
        try:
            if pq_path.exists():
                return pd.read_parquet(pq_path)
            raise FileNotFoundError
        except Exception:
            csv_path = self.processed_dir / f"{name}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                if name in {"tasks", "interactions"}:
                    for col in {"posted_time", "deadline", "timestamp"}:
                        if col in df.columns:
                            df[col] = pd.to_datetime(df[col])
                if name == "market":
                    if "time_bucket" in df.columns:
                        df["time_bucket"] = pd.to_datetime(df["time_bucket"])
                return df
            raise

    def _load_dataset(self) -> DatasetBundle:
        tasks = self._read_table("tasks")
        market = self._read_table("market")
        return DatasetBundle(tasks=tasks, market=market)

    def _maybe_merge_embeddings(self, df: pd.DataFrame) -> pd.DataFrame:
        embedding_csv = self.path_cfg.embeddings_dir / "task_embeddings.csv"
        if self.config.use_embeddings and embedding_csv.exists():
            emb = pd.read_csv(embedding_csv)
            df = df.merge(emb, left_on="task_id", right_on="id", how="left")
            df = df.drop(columns=["id"], errors="ignore")
        elif self.config.use_embeddings:
            logger.warning("Embedding flag enabled but %s not found", embedding_csv)
        return df

    def _prepare_features(self) -> pd.DataFrame:
        tasks = self.bundle.tasks.copy()
        tasks["market_bucket"] = tasks["market_bucket"].astype(str)
        market = self.bundle.market.copy()
        market = market.rename(
            columns={
                "num_tasks": "market_num_tasks",
                "avg_prize": "market_avg_prize",
                "num_submissions": "market_avg_submissions",
                "starved": "market_starved_rate",
                "failed": "market_failed_rate",
                "dropped": "market_dropped_rate",
            }
        )
        market["time_bucket"] = pd.to_datetime(market["time_bucket"])
        market["time_bucket_str"] = market["time_bucket"].dt.to_period("M").astype(str)
        tasks = tasks.merge(
            market,
            left_on=["market_bucket", "track"],
            right_on=["time_bucket_str", "track"],
            how="left",
        )
        tasks = tasks.drop(columns=["time_bucket", "time_bucket_str"], errors="ignore")
        tasks["text"] = (
            tasks["title"].fillna("")
            + " "
            + tasks["description"].fillna("")
            + " "
            + tasks["tags"].fillna("")
        )
        tasks["posted_month"] = pd.to_datetime(tasks["posted_time"]).dt.month
        tasks["posted_dow"] = pd.to_datetime(tasks["posted_time"]).dt.dayofweek
        for col in NUMERIC_FEATURES:
            if col in tasks.columns:
                median = tasks[col].median()
                if pd.isna(median):
                    median = 0.0
                tasks[col] = tasks[col].fillna(median)
        for col in CATEGORICAL_FEATURES:
            if col in tasks.columns:
                tasks[col] = tasks[col].fillna("unknown")
        tasks = self._maybe_merge_embeddings(tasks)
        return tasks

    # ------------------------------------------------------------------
    def _build_column_transformer(self, df: pd.DataFrame) -> ColumnTransformer:
        mode = FEATURE_MODES.get(self.feature_mode, FEATURE_MODES["multimodal"])
        numeric_cols = [
            col for col in NUMERIC_FEATURES if col in df.columns and col not in self.target_columns
        ]
        categorical_cols = [
            col for col in CATEGORICAL_FEATURES if col in df.columns and col not in self.target_columns
        ]
        time_cols = [
            col for col in TIME_FEATURES if col in df.columns and col not in self.target_columns
        ]
        embedding_cols = [col for col in df.columns if col.startswith("dim_")]

        transformers = []
        transformers.append(
            (
                "text",
                TfidfVectorizer(max_features=self.config.max_tfidf_features, ngram_range=(1, 2)),
                "text",
            )
        )
        if mode["use_numeric"]:
            transformers.append(("numeric", StandardScaler(), numeric_cols))
        if mode["use_categorical"]:
            transformers.append(
                (
                    "categorical",
                    OneHotEncoder(handle_unknown="ignore", min_frequency=0.01),
                    categorical_cols,
                )
            )
        if mode["use_time"]:
            transformers.append(("time", OneHotEncoder(handle_unknown="ignore"), time_cols))
        if mode["use_embeddings"] and embedding_cols:
            transformers.append(("embeddings", "passthrough", embedding_cols))
        return ColumnTransformer(transformers=transformers)

    def _get_models(self, task_type: str):
        if task_type == "classification":
            return {
                "log_reg": LogisticRegression(max_iter=1000),
                "rf": RandomForestClassifier(
                    n_estimators=200, random_state=self.config.random_state, n_jobs=-1
                ),
                "gb": GradientBoostingClassifier(random_state=self.config.random_state),
            }
        return {
            "rf_reg": RandomForestRegressor(
                n_estimators=200, random_state=self.config.random_state, n_jobs=-1
            ),
            "gb_reg": GradientBoostingRegressor(random_state=self.config.random_state),
        }

    def _split(self, df: pd.DataFrame, target: str):
        X = df.copy()
        y = X.pop(target)
        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=self.config.test_size,
            random_state=self.config.random_state,
            stratify=y if y.nunique() > 1 and y.dtype in [np.int64, np.int32, np.int16] else None,
        )
        val_size = self.config.val_size / (1 - self.config.test_size)
        X_train, X_val, y_train, y_val = train_test_split(
            X_train,
            y_train,
            test_size=val_size,
            random_state=self.config.random_state,
            stratify=y_train if y_train.nunique() > 1 and y_train.dtype in [np.int64, np.int32, np.int16] else None,
        )
        return X_train, X_val, X_test, y_train, y_val, y_test

    def _plot_feature_importance(self, pipeline: Pipeline, target: str, model_name: str) -> None:
        preprocess = pipeline.named_steps["preprocess"]
        model = pipeline.named_steps["model"]
        if plt is None:
            return
        try:
            feature_names = preprocess.get_feature_names_out()
        except Exception:  # pragma: no cover
            feature_names = [f"f_{i}" for i in range(model.n_features_in_)]

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "coef_"):
            importances = np.abs(model.coef_).ravel()
        else:
            return
        top_idx = np.argsort(importances)[-15:]
        top_features = np.array(feature_names)[top_idx]
        top_values = importances[top_idx]
        order = np.argsort(top_values)

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(range(len(order)), top_values[order])
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels(top_features[order])
        ax.set_title(f"Feature importance: {model_name} → {target}")
        ax.set_xlabel("Importance")
        fig.tight_layout()
        fig_path = self.path_cfg.figs_dir / f"feat_{self.feature_mode}_{target}_{model_name}.png"
        fig.savefig(fig_path, dpi=200)
        plt.close(fig)

    # ------------------------------------------------------------------
    def run(self) -> pd.DataFrame:
        df = self.dataset.copy()
        column_transformer = self._build_column_transformer(df)
        records: List[Dict[str, float]] = []
        artifacts_dir = self.path_cfg.artifacts_dir / "supervised"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        for target, task_type in {**self.config.classification_targets, **self.config.regression_targets}.items():
            if target not in df.columns:
                logger.warning("Skipping target %s – column not found", target)
                continue
            X_train, X_val, X_test, y_train, y_val, y_test = self._split(df, target)
            models = self._get_models(task_type)
            for name, estimator in models.items():
                pipeline = Pipeline([
                    ("preprocess", column_transformer),
                    ("model", estimator),
                ])
                pipeline.fit(X_train, y_train)
                if task_type == "classification":
                    y_val_prob = pipeline.predict_proba(X_val)[:, 1]
                    y_test_prob = pipeline.predict_proba(X_test)[:, 1]
                    val_metrics = classification_metrics(y_val.to_numpy(), y_val_prob, target_name=target)
                    val_metrics.update({"split": "val", "model": name, "feature_mode": self.feature_mode})
                    test_metrics = classification_metrics(y_test.to_numpy(), y_test_prob, target_name=target)
                    test_metrics.update({"split": "test", "model": name, "feature_mode": self.feature_mode})
                else:
                    y_val_pred = pipeline.predict(X_val)
                    y_test_pred = pipeline.predict(X_test)
                    val_metrics = regression_metrics(y_val.to_numpy(), y_val_pred, target_name=target)
                    val_metrics.update({"split": "val", "model": name, "feature_mode": self.feature_mode})
                    test_metrics = regression_metrics(y_test.to_numpy(), y_test_pred, target_name=target)
                    test_metrics.update({"split": "test", "model": name, "feature_mode": self.feature_mode})
                records.extend([val_metrics, test_metrics])

                model_path = artifacts_dir / f"{target}_{name}_{self.feature_mode}.pkl"
                with model_path.open("wb") as fp:
                    pickle.dump(pipeline, fp)
                self._plot_feature_importance(pipeline, target, name)

        metrics_path = self.path_cfg.tables_dir / f"supervised_metrics_{self.feature_mode}.csv"
        df_metrics = save_metrics(records, metrics_path)
        return df_metrics


def run_ablation(
    feature_modes: List[str] | None = None,
    processed_dir: Path | None = None,
    config: SupervisedConfig | None = None,
) -> pd.DataFrame:
    modes = feature_modes or list(FEATURE_MODES.keys())
    dfs = []
    for mode in modes:
        cfg = config or SupervisedConfig(use_embeddings=FEATURE_MODES[mode]["use_embeddings"])
        cfg.use_embeddings = FEATURE_MODES[mode]["use_embeddings"]
        exp = SupervisedExperiment(processed_dir=processed_dir, config=cfg, feature_mode=mode)
        dfs.append(exp.run())
    concat = pd.concat(dfs, ignore_index=True)
    output_path = PathConfig().tables_dir / "multimodal_ablation.csv"
    concat.to_csv(output_path, index=False)
    return concat


__all__ = ["SupervisedExperiment", "run_ablation"]
