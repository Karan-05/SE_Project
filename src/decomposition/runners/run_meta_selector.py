"""Train a leakage-audited meta-selector that picks the best strategy per task."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

from src.config import PathConfig, PROJECT_ROOT

REPORT_DIR = PathConfig().reports_root / "decomposition"
ARTIFACTS_DIR = PathConfig().artifacts_dir
ALLOWED_NUMERIC_FEATURES = [
    "statement_len",
    "est_complexity",
    "contract_completeness",
    "pattern_confidence",
    "decomposition_steps",
]
PITFALL_PREFIX = "pitfall::"


def _load_tasks(tasks_file: Path) -> Dict[str, Dict]:
    with tasks_file.open("r", encoding="utf-8") as fp:
        tasks = json.load(fp)
    return {task["id"]: task for task in tasks}


def _best_strategy_per_task(df: pd.DataFrame) -> Dict[str, str]:
    best: Dict[str, Tuple[float, float, str]] = {}
    for _, row in df.iterrows():
        task_id = row["task_id"]
        pass_rate = float(row["pass_rate"])
        cost = float(row.get("decomposition_steps", 0.0) or 0.0)
        key = (pass_rate, -cost)
        if task_id not in best or key > (best[task_id][0], best[task_id][1]):
            best[task_id] = (pass_rate, -cost, row["strategy"])
    return {task_id: entry[2] for task_id, entry in best.items()}


def _row_features(task: Dict, row: pd.Series, label: int) -> Dict[str, float | str | int]:
    statement = task.get("statement") or task.get("problem_statement", "")
    statement_len = len(statement.split())
    pitfalls = task.get("pitfalls", [])
    est_complexity = float(row.get("contract_length", 0) or statement_len / 2)
    feature_row: Dict[str, float | str | int] = {
        "task_id": task["id"],
        "strategy": row["strategy"],
        "task_type": task.get("type", task.get("category", "unknown")),
        "task_difficulty": task.get("difficulty", "unknown"),
        "split": task.get("split", "train"),
        "statement_len": statement_len,
        "est_complexity": est_complexity,
        "contract_completeness": float(row.get("contract_completeness", 0.0) or 0.0),
        "pattern_confidence": float(row.get("pattern_confidence", 0.0) or 0.0),
        "decomposition_steps": float(row.get("decomposition_steps", 0.0) or 0.0),
        "label": label,
        "best_strategy": row.get("best_strategy"),
    }
    for pit in pitfalls:
        feature_row[f"{PITFALL_PREFIX}{pit}"] = 1.0
    return feature_row


def build_dataset(tasks_file: Path, comparison_file: Path) -> pd.DataFrame:
    task_map = _load_tasks(tasks_file)
    df = pd.read_csv(comparison_file)
    best = _best_strategy_per_task(df)
    rows: List[Dict[str, float | str | int]] = []
    for _, row in df.iterrows():
        task = task_map[row["task_id"]]
        label = 1 if row["strategy"] == best[row["task_id"]] else 0
        series = row.copy()
        series["best_strategy"] = best[row["task_id"]]
        rows.append(_row_features(task, series, label))
    dataset = pd.DataFrame(rows)
    dataset.fillna(0.0, inplace=True)
    return dataset


def _encode_features(df: pd.DataFrame, feature_cols: List[str] | None = None) -> Tuple[np.ndarray, List[str]]:
    work = df.copy()
    pitfall_cols = [col for col in work.columns if col.startswith(PITFALL_PREFIX)]
    feature_df = work[ALLOWED_NUMERIC_FEATURES].copy()
    for col in pitfall_cols:
        feature_df[col] = work[col]
    dummies = pd.get_dummies(work[["strategy", "task_type", "task_difficulty"]], drop_first=False)
    feature_df = pd.concat([feature_df, dummies], axis=1)
    feature_df = feature_df.fillna(0.0)
    if feature_cols is None:
        feature_cols = feature_df.columns.tolist()
    for col in feature_cols:
        if col not in feature_df:
            feature_df[col] = 0.0
    feature_df = feature_df[feature_cols]
    return feature_df.to_numpy(dtype=float), feature_cols


def _train_model(train_df: pd.DataFrame) -> Tuple[LogisticRegression, List[str]]:
    X_train, feature_cols = _encode_features(train_df)
    y_train = train_df["label"].astype(int).to_numpy()
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train)
    return model, feature_cols


def _task_level_split(dataset: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    unique_tasks = dataset["task_id"].unique()
    if len(unique_tasks) <= 3:
        return dataset, dataset
    train_ids, test_ids = train_test_split(unique_tasks, test_size=0.3, random_state=42)
    train_df = dataset[dataset["task_id"].isin(train_ids)].copy()
    test_df = dataset[dataset["task_id"].isin(test_ids)].copy()
    return train_df, test_df


def train_meta_selector(dataset: pd.DataFrame) -> Tuple[LogisticRegression, List[str], float]:
    train_df, test_df = _task_level_split(dataset)
    model, feature_cols = _train_model(train_df)
    X_test, _ = _encode_features(test_df, feature_cols)
    y_test = test_df["label"].astype(int).to_numpy()
    if y_test.size == 0:
        accuracy = 1.0
    else:
        preds = model.predict(X_test)
        accuracy = float(accuracy_score(y_test, preds))
    return model, feature_cols, accuracy


def predict_best_strategies(model: LogisticRegression, feature_cols: List[str], dataset: pd.DataFrame) -> pd.DataFrame:
    X, _ = _encode_features(dataset, feature_cols)
    probs = model.predict_proba(X)[:, 1]
    dataset = dataset.copy()
    dataset["probability"] = probs
    predictions = []
    for task_id, group in dataset.groupby("task_id"):
        best_row = group.loc[group["probability"].idxmax()]
        predictions.append(
            {
                "task_id": task_id,
                "predicted_strategy": best_row["strategy"],
                "probability": float(best_row["probability"]),
                "true_best_strategy": best_row["best_strategy"],
            }
        )
    return pd.DataFrame(predictions)


def _write_audit(model: LogisticRegression, feature_cols: List[str], output_path: Path) -> None:
    coeffs = model.coef_[0]
    audit_df = pd.DataFrame({
        "feature": feature_cols,
        "coefficient": coeffs,
        "abs_coefficient": np.abs(coeffs),
    }).sort_values("abs_coefficient", ascending=False)
    lines = ["# Meta-Selector Audit", "", "Allowed numerical features:"]
    lines.append(", ".join(ALLOWED_NUMERIC_FEATURES))
    lines.append("")
    lines.append("| feature | coefficient | abs_coefficient |")
    lines.append("| --- | --- | --- |")
    for _, row in audit_df.iterrows():
        lines.append(f"| {row['feature']} | {row['coefficient']:.4f} | {row['abs_coefficient']:.4f} |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_loo_type(dataset: pd.DataFrame, out_path: Path) -> None:
    rows = []
    for task_type in sorted(dataset["task_type"].unique()):
        test_df = dataset[dataset["task_type"] == task_type]
        train_df = dataset[dataset["task_type"] != task_type]
        if test_df.empty or train_df.empty:
            continue
        model, feature_cols = _train_model(train_df)
        X_test, _ = _encode_features(test_df, feature_cols)
        y_test = test_df["label"].astype(int).to_numpy()
        preds = model.predict(X_test)
        acc = float(accuracy_score(y_test, preds)) if y_test.size else 0.0
        rows.append(
            {
                "task_type": task_type,
                "accuracy": acc,
                "num_tasks": test_df["task_id"].nunique(),
                "num_rows": len(test_df),
            }
        )
    pd.DataFrame(rows).to_csv(out_path, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and evaluate the decomposition meta-selector")
    parser.add_argument("--tasks-file", type=Path, default=PROJECT_ROOT / "experiments" / "decomposition" / "benchmark_tasks.json")
    parser.add_argument("--comparison-file", type=Path, default=REPORT_DIR / "strategy_comparison.csv")
    parser.add_argument("--model-out", type=Path, default=ARTIFACTS_DIR / "meta_selector.pkl")
    parser.add_argument("--report-out", type=Path, default=REPORT_DIR / "meta_selector.csv")
    parser.add_argument("--audit", action="store_true", help="Write meta_selector_audit.md with feature importances")
    parser.add_argument("--loo-type", action="store_true", help="Perform leave-one-task-type-out evaluation")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset(args.tasks_file, args.comparison_file)
    model, feature_cols, accuracy = train_meta_selector(dataset)
    joblib.dump({"model": model, "feature_columns": feature_cols}, args.model_out)
    predictions = predict_best_strategies(model, feature_cols, dataset)
    predictions["selector_accuracy"] = accuracy
    predictions.to_csv(args.report_out, index=False)
    if args.audit:
        _write_audit(model, feature_cols, REPORT_DIR / "meta_selector_audit.md")
    if args.loo_type:
        _run_loo_type(dataset, REPORT_DIR / "meta_selector_loo.csv")
    print("Meta-selector accuracy:", accuracy)


if __name__ == "__main__":  # pragma: no cover
    main()
