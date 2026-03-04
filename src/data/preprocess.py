"""Preprocessing pipeline that materialises TASK/WORKER/INTERACTION/MARKET tables."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from src.config import DataConfig, PathConfig
from src.data.load import load_or_generate


def _ensure_datetime(df: pd.DataFrame, columns) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


def _save_table(df: pd.DataFrame, name: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_dir / f"{name}.parquet", index=False)
    df.to_csv(output_dir / f"{name}.csv", index=False)


def _build_market_table(tasks: pd.DataFrame, freq: str = "M") -> pd.DataFrame:
    tasks = tasks.copy()
    tasks["time_bucket"] = tasks["posted_time"].dt.to_period(freq).dt.to_timestamp()

    aggregations = {
        "task_id": "count",
        "prize": "mean",
        "num_submissions": "mean",
        "starved": "mean",
        "failed": "mean",
        "dropped": "mean",
    }
    market_df = (
        tasks.groupby(["time_bucket", "track"]).agg(aggregations).reset_index()
    )
    market_df = market_df.rename(columns={"task_id": "num_tasks", "prize": "avg_prize"})

    tag_counts = (
        tasks.assign(tag=lambda df: df["tags"].str.split(","))
        .explode("tag")
        .groupby(["time_bucket", "tag"])
        .size()
        .reset_index(name="tasks_per_tag")
    )

    market_df = market_df.merge(tag_counts, on="time_bucket", how="left")
    return market_df


def preprocess(
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
    data_config: DataConfig | None = None,
) -> Dict[str, pd.DataFrame]:
    path_cfg = PathConfig()
    raw_root = raw_dir or path_cfg.raw_data
    processed_root = output_dir or path_cfg.processed_data

    bundle = load_or_generate(raw_root, data_config)
    tasks = bundle["tasks"].copy()
    workers = bundle["workers"].copy()
    interactions = bundle["interactions"].copy()

    tasks = _ensure_datetime(tasks, ["posted_time", "deadline"])
    tasks["duration_days"] = (tasks["deadline"] - tasks["posted_time"]).dt.days
    tasks["market_bucket"] = tasks["posted_time"].dt.to_period("M").astype(str)
    tasks["local_time_load"] = tasks.groupby("market_bucket")["task_id"].transform("count")
    tasks["tags_vector"] = tasks["tags"].str.split(",")

    workers["skill_vector"] = workers["skill_vector"].apply(
        lambda x: [float(v) for v in str(x).split(";") if v]
    )
    workers["domains"] = workers["domain_tags"].str.split(",")

    interactions = _ensure_datetime(interactions, ["timestamp"])
    interactions["scored"] = interactions["scored"].fillna(0).astype(int)
    interactions["rank"] = interactions["rank"].fillna(0).astype(int)

    market = _build_market_table(tasks, freq=(data_config.market_bucket if data_config else "M"))

    _save_table(tasks, "tasks", processed_root)
    _save_table(workers, "workers", processed_root)
    _save_table(interactions, "interactions", processed_root)
    _save_table(market, "market", processed_root)

    metadata_path = processed_root / "metadata.json"
    metadata = {
        "data_config": asdict(data_config or DataConfig()),
        "num_tasks": int(tasks.shape[0]),
        "num_workers": int(workers.shape[0]),
        "num_interactions": int(interactions.shape[0]),
    }
    with metadata_path.open("w", encoding="utf-8") as fp:
        json.dump(metadata, fp, indent=2, default=str)

    return {
        "tasks": tasks,
        "workers": workers,
        "interactions": interactions,
        "market": market,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Materialise processed datasets")
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-tasks", type=int, default=400)
    parser.add_argument("--num-workers", type=int, default=250)
    args = parser.parse_args()

    cfg = DataConfig(seed=args.seed, num_tasks=args.num_tasks, num_workers=args.num_workers)
    preprocess(args.raw_dir, args.output_dir, cfg)


if __name__ == "__main__":
    main()
