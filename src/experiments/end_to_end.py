"""End-to-end experiment orchestration + ablation reporting."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd

from src.config import PathConfig
from src.utils.reporting import write_metadata
from src.utils.tables import write_latex_table

LOGGER = logging.getLogger(__name__)


def _load_json_or_yaml(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "YAML config requires PyYAML. Install it or provide a JSON-compatible file."
            ) from exc
        return yaml.safe_load(text)


def _load_rl_metrics(report_dir: Path, pattern: str, agent_col: str) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in sorted(report_dir.glob(pattern)):
        df = pd.read_csv(path)
        if agent_col not in df.columns:
            continue
        df = df.rename(columns={agent_col: "agent"})
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No RL metrics found matching {pattern}")
    combined = pd.concat(frames, ignore_index=True)
    combined["seed"] = combined["seed"].astype(int)
    return combined


def _load_cost_tokens(report_dir: Path) -> Dict[str, float]:
    path = report_dir / "cost_vs_quality.csv"
    if not path.exists():
        LOGGER.warning("Missing cost_vs_quality.csv at %s", path)
        return {}
    df = pd.read_csv(path)
    return {row["strategy"]: float(row.get("avg_tokens", np.nan)) for _, row in df.iterrows()}


def _load_embedding_ratio(tables_dir: Path) -> float:
    path = tables_dir / "embeddings_ablation.csv"
    if not path.exists():
        return 1.0
    df = pd.read_csv(path)
    if "embedding" not in df.columns or "f1" not in df.columns:
        return 1.0
    pivot = df.groupby("embedding")["f1"].mean()
    if "baseline" not in pivot or len(pivot) < 2:
        return 1.0
    best = float(pivot.max())
    baseline = float(pivot["baseline"])
    if best <= 0:
        return 1.0
    return max(0.0, baseline / best)


def _load_regression_r2(out_dir: Path) -> Dict[str, float]:
    path = out_dir / "regression_metrics.json"
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df = df[df["split"] == "test"]
    best = df.sort_values("r2", ascending=False).drop_duplicates(subset=["target"])
    return {row["target"]: float(row["r2"]) for _, row in best.iterrows()}


def bootstrap_ci(values: np.ndarray, rng: np.random.Generator, iters: int = 1000) -> Tuple[float, float]:
    if values.size == 0:
        return (np.nan, np.nan)
    if values.size == 1:
        val = float(values[0])
        return (val, val)
    samples = [float(values[rng.integers(0, values.size, size=values.size)].mean()) for _ in range(iters)]
    lower = float(np.percentile(samples, 2.5))
    upper = float(np.percentile(samples, 97.5))
    return (lower, upper)


@dataclass
class Resources:
    single_rl: pd.DataFrame
    multi_rl: pd.DataFrame
    cost_tokens: Dict[str, float]
    embedding_ratio: float
    regression_r2: Dict[str, float]
    horizon: int


def run_variant(variant_cfg: Dict[str, object], seed: int, resources: Resources) -> Dict[str, object]:
    metrics: Dict[str, object] = {
        "variant": variant_cfg["name"],
        "seed": seed,
        "description": variant_cfg.get("description", ""),
    }
    rl_source = variant_cfg.get("rl_source")
    agent_name = variant_cfg.get("agent")
    if rl_source:
        rl_df = resources.multi_rl if rl_source == "multi" else resources.single_rl
        row = rl_df[(rl_df["seed"] == seed) & (rl_df["agent"] == agent_name)]
        if row.empty:
            available = sorted(rl_df["seed"].unique())
            raise ValueError(f"Seed {seed} not available for agent '{agent_name}'. Available seeds: {available}")
        row = row.iloc[0]
        win_rate = float(row["win_rate"])
        metrics.update(
            {
                "avg_reward": float(row.get("avg_reward", np.nan)),
                "win_rate": win_rate,
                "failure_rate": max(0.0, 1.0 - win_rate),
                "starvation_rate": float(row.get("starved_tasks", np.nan)) / max(1, resources.horizon),
            }
        )
    else:
        metrics.update(
            {
                "avg_reward": np.nan,
                "win_rate": np.nan,
                "failure_rate": np.nan,
                "starvation_rate": np.nan,
            }
        )
    cost_proxy = resources.cost_tokens.get(variant_cfg.get("strategy", ""), np.nan)
    if variant_cfg.get("embedding_profile") == "no_graph" and not np.isnan(metrics.get("win_rate", np.nan)):
        ratio = resources.embedding_ratio
        metrics["win_rate"] = max(0.0, min(1.0, metrics["win_rate"] * ratio))
        metrics["failure_rate"] = max(0.0, 1.0 - metrics["win_rate"])
    if variant_cfg.get("type") == "predictor":
        r2 = resources.regression_r2.get("submission_count", np.nan)
        metrics.update(
            {
                "avg_reward": np.nan,
                "win_rate": r2,
                "failure_rate": max(0.0, 1.0 - r2) if not np.isnan(r2) else np.nan,
                "starvation_rate": np.nan,
            }
        )
    multiplier = float(variant_cfg.get("cost_multiplier", 1.0))
    metrics["cost_proxy"] = cost_proxy * multiplier if not np.isnan(cost_proxy) else np.nan
    return metrics


def summarize_runs(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    metrics = ["failure_rate", "starvation_rate", "avg_reward", "win_rate", "cost_proxy"]
    rows: List[Dict[str, object]] = []
    for variant, group in df.groupby("variant"):
        for metric in metrics:
            values = group[metric].dropna().to_numpy(dtype=float)
            if values.size == 0:
                continue
            mean = float(values.mean())
            lower, upper = bootstrap_ci(values, rng)
            rows.append(
                {
                    "variant": variant,
                    "metric": metric,
                    "mean": mean,
                    "ci_lower": lower,
                    "ci_upper": upper,
                }
            )
    return pd.DataFrame(rows)


def plot_ablation(summary: pd.DataFrame, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = ["failure_rate", "starvation_rate", "avg_reward", "win_rate"]
    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4))
    if len(metrics) == 1:
        axes = [axes]
    for metric, ax in zip(metrics, axes):
        subset = summary[summary["metric"] == metric]
        x = np.arange(len(subset))
        errors = np.vstack([subset["mean"] - subset["ci_lower"], subset["ci_upper"] - subset["mean"]])
        ax.bar(x, subset["mean"], yerr=errors, capsize=4)
        ax.set_title(metric.replace("_", " ").title())
        ax.set_xticks(x)
        ax.set_xticklabels(subset["variant"], rotation=30, ha="right")
        ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def run_end_to_end(
    config_path: Path,
    out_dir: Path,
    *,
    num_seeds: int,
    base_seed: int,
    seed: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cfg = _load_json_or_yaml(config_path)
    variants = cfg.get("variants", [])
    horizon = int(cfg.get("horizon", 50))
    path_cfg = PathConfig()
    report_dir = path_cfg.reports_root / "decomposition"
    tables_dir = path_cfg.reports_root / "tables"
    regression_dir = path_cfg.reports_root / "regression"

    single_rl = _load_rl_metrics(report_dir, "rl_decomposition_metrics_seed_*.csv", "agent")
    multi_rl = _load_rl_metrics(report_dir, "rl_multiagent_metrics_seed_*.csv", "policy")
    resources = Resources(
        single_rl=single_rl,
        multi_rl=multi_rl,
        cost_tokens=_load_cost_tokens(report_dir),
        embedding_ratio=_load_embedding_ratio(tables_dir),
        regression_r2=_load_regression_r2(regression_dir),
        horizon=horizon,
    )
    available_seeds = sorted(set(single_rl["seed"].unique()) & set(multi_rl["seed"].unique()))
    requested_seeds = [base_seed + idx for idx in range(num_seeds)]
    missing = [seed for seed in requested_seeds if seed not in available_seeds]
    if missing:
        raise ValueError(f"Missing RL metrics for seeds: {missing}. Available seeds: {available_seeds}")

    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    runs: List[Dict[str, object]] = []
    runs_path = out_dir / "runs.jsonl"
    with runs_path.open("w", encoding="utf-8") as fp:
        for seed_value in requested_seeds:
            for variant in variants:
                metrics = run_variant(variant, seed_value, resources)
                fp.write(json.dumps(metrics) + "\n")
                runs.append(metrics)
    runs_df = pd.DataFrame(runs)
    summary = summarize_runs(runs_df, rng)
    summary.to_csv(out_dir / "summary.csv", index=False)
    write_latex_table(summary, out_dir / "table_end_to_end.tex")
    plot_ablation(summary, out_dir / "fig_ablation_kpis.png")
    write_metadata(
        out_dir,
        seeds=requested_seeds,
        config={
            "config_path": str(config_path),
            "num_seeds": num_seeds,
            "base_seed": base_seed,
            "bootstrap_seed": seed,
        },
        inputs=[
            config_path,
            report_dir / "rl_decomposition_metrics_seed_1.csv",
            report_dir / "rl_multiagent_metrics_seed_1.csv",
        ],
    )
    return runs_df, summary


__all__ = ["run_variant", "run_end_to_end"]
