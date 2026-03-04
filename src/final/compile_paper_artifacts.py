"""Build a consolidated artifact pack for the paper appendix."""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import matplotlib
import numpy as np
import pandas as pd

from src.config import PathConfig
from src.utils.reporting import write_metadata
from src.utils.tables import write_latex_table

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic helpers


def _require_files(paths: Sequence[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required input files: {missing}")


def _ensure_out_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _bootstrap_ci(values: np.ndarray, rng: np.random.Generator, *, iters: int = 1000, alpha: float = 0.05) -> Tuple[float, float]:
    if values.size == 0:
        return (np.nan, np.nan)
    if values.size == 1:
        val = float(values[0])
        return (val, val)
    samples = []
    for _ in range(iters):
        idx = rng.integers(0, values.size, size=values.size)
        samples.append(float(values[idx].mean()))
    lower = float(np.percentile(samples, 100 * (alpha / 2)))
    upper = float(np.percentile(samples, 100 * (1 - alpha / 2)))
    return (lower, upper)


# ---------------------------------------------------------------------------
# Supervised metrics stitching


def _normalize_feature_mode(path: Path, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "feature_mode" not in df.columns:
        stem = path.stem.replace("supervised_metrics_", "")
        df["feature_mode"] = stem
    df["feature_mode"] = df["feature_mode"].fillna("unknown")
    if "split" in df.columns:
        df["split"] = df["split"].astype(str)
    if "target" not in df.columns:
        df["target"] = "aggregate"
    return df


def _summarize_supervised(paths: Sequence[Path], out_dir: Path) -> pd.DataFrame:
    _require_files(paths)
    frames: List[pd.DataFrame] = []
    for path in paths:
        df = pd.read_csv(path)
        df = _normalize_feature_mode(path, df)
        df["source_file"] = str(path)
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    split_mask = (
        combined["split"].str.lower() == "test"
        if "split" in combined.columns
        else pd.Series([True] * len(combined), index=combined.index)
    )
    filtered = combined[split_mask].copy()
    metric_candidates = [
        "f1",
        "accuracy",
        "precision",
        "recall",
        "roc_auc",
        "log_loss",
        "rmse",
        "mae",
        "r2",
    ]
    present_metrics = [col for col in metric_candidates if col in filtered.columns]
    summary_rows: List[Dict[str, object]] = []
    grouped = filtered.groupby(["feature_mode", "target"], dropna=False)
    for (feature_mode, target), group in grouped:
        row: Dict[str, object] = {"feature_mode": feature_mode, "target": target}
        for metric in present_metrics:
            row[metric] = float(group[metric].mean())
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows).sort_values(["feature_mode", "target"]).reset_index(drop=True)
    summary.to_csv(out_dir / "supervised_summary.csv", index=False)
    if not summary.empty:
        write_latex_table(summary, out_dir / "table_supervised.tex")
        plot_metric = next((metric for metric in ["f1", "roc_auc", "accuracy", "r2"] if metric in summary.columns), None)
        if plot_metric:
            fig, ax = plt.subplots(figsize=(6, 4))
            plot_data = summary.groupby("feature_mode")[plot_metric].mean().reset_index()
            ax.bar(plot_data["feature_mode"], plot_data[plot_metric], color="#003f5c")
            ax.set_ylabel(plot_metric.upper())
            ax.set_xlabel("Feature mode")
            ax.set_title(f"Supervised overview ({plot_metric.upper()})")
            ax.set_ylim(0, min(1.05, max(1.0, plot_data[plot_metric].max() * 1.1))) if plot_metric != "r2" else None
            ax.grid(axis="y", linestyle="--", alpha=0.4)
            fig.tight_layout()
            fig.savefig(out_dir / "fig_supervised_overview.png", dpi=200)
            plt.close(fig)
    return summary


# ---------------------------------------------------------------------------
# RL CI computation


@dataclass
class RLSummaryResult:
    raw: pd.DataFrame
    summary: pd.DataFrame


def _load_rl_frames(single_paths: Sequence[Path], multi_paths: Sequence[Path]) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for path in single_paths:
        df = pd.read_csv(path)
        df["rl_type"] = "single_agent"
        df["source_file"] = str(path)
        frames.append(df)
    for path in multi_paths:
        df = pd.read_csv(path)
        df["rl_type"] = "multi_agent"
        df["source_file"] = str(path)
        frames.append(df)
    if not frames:
        raise FileNotFoundError("No RL metrics found under reports/decomposition/. Run make decomp_rl_seeds first.")
    return pd.concat(frames, ignore_index=True)


def _summarize_rl(single_paths: Sequence[Path], multi_paths: Sequence[Path], out_dir: Path, rng: np.random.Generator) -> RLSummaryResult:
    raw = _load_rl_frames(single_paths, multi_paths)
    kpis = [col for col in ["avg_reward", "win_rate", "starved_tasks"] if col in raw.columns]
    summary_rows: List[Dict[str, object]] = []
    for (rl_type, agent), group in raw.groupby(["rl_type", "agent"]):
        for metric in kpis:
            values = group[metric].dropna().to_numpy(dtype=float)
            if values.size == 0:
                continue
            lower, upper = _bootstrap_ci(values, rng)
            summary_rows.append(
                {
                    "rl_type": rl_type,
                    "agent": agent,
                    "metric": metric,
                    "mean": float(values.mean()),
                    "ci_lower": lower,
                    "ci_upper": upper,
                    "num_samples": int(values.size),
                }
            )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(out_dir / "rl_ci_summary.csv", index=False)
    if not summary.empty:
        write_latex_table(summary, out_dir / "table_rl_ci.tex")
        metrics = [metric for metric in ["avg_reward", "win_rate", "starved_tasks"] if metric in summary["metric"].unique()]
        if metrics:
            fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4))
            if len(metrics) == 1:
                axes = [axes]
            for metric, ax in zip(metrics, axes):
                plot_df = summary[summary["metric"] == metric].copy()
                plot_df["label"] = plot_df.apply(lambda row: f"{row['agent']} ({row['rl_type']})", axis=1)
                x = np.arange(len(plot_df))
                ax.bar(x, plot_df["mean"], color="#7a5195")
                ax.errorbar(
                    x,
                    plot_df["mean"],
                    yerr=[plot_df["mean"] - plot_df["ci_lower"], plot_df["ci_upper"] - plot_df["mean"]],
                    fmt="none",
                    ecolor="black",
                    capsize=4,
                )
                ax.set_title(metric.replace("_", " ").title())
                ax.set_xticks(x)
                ax.set_xticklabels(plot_df["label"], rotation=45, ha="right")
                ax.grid(axis="y", linestyle="--", alpha=0.4)
            fig.tight_layout()
            fig.savefig(out_dir / "fig_rl_ci.png", dpi=200)
            plt.close(fig)
    return RLSummaryResult(raw=raw, summary=summary)


# ---------------------------------------------------------------------------
# Cost frontier rendering


def _summarize_cost_frontier(cost_path: Path, cost_vs_path: Path | None, out_dir: Path) -> pd.DataFrame:
    _require_files([cost_path])
    cost_df = pd.read_csv(cost_path)
    if cost_vs_path and cost_vs_path.exists():
        cvq_df = pd.read_csv(cost_vs_path)
        merged = cost_df.merge(cvq_df, on="strategy", how="left", suffixes=("", "_avg"))
    else:
        merged = cost_df.copy()
    merged.to_csv(out_dir / "cost_frontier_summary.csv", index=False)
    write_latex_table(merged, out_dir / "table_cost_frontier.tex")
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    if "on_frontier" in merged.columns:
        on_frontier = merged["on_frontier"].astype(bool)
    else:
        on_frontier = pd.Series([False] * len(merged))
    ax.scatter(merged.loc[~on_frontier, "cost"], merged.loc[~on_frontier, "quality"], color="#c7c7c7", label="Off frontier")
    ax.scatter(merged.loc[on_frontier, "cost"], merged.loc[on_frontier, "quality"], color="#ef5675", label="Frontier")
    ax.set_xlabel("Cost (tokens)")
    ax.set_ylabel("Quality (pass rate)")
    ax.set_title("Cost-quality frontier")
    for _, row in merged.iterrows():
        ax.annotate(row["strategy"], (row["cost"], row["quality"]), fontsize=8, alpha=0.7)
    ax.legend()
    ax.grid(alpha=0.3, linestyle="--")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_cost_frontier.png", dpi=200)
    plt.close(fig)
    return merged


# ---------------------------------------------------------------------------
# End-to-end ablation builder


def _load_strategy_summary(strategy_path: Path) -> pd.DataFrame:
    _require_files([strategy_path])
    df = pd.read_csv(strategy_path)
    if "strategy" not in df.columns or "pass_rate" not in df.columns:
        raise ValueError(f"strategy_comparison missing required columns: {strategy_path}")
    strat_summary = df.groupby("strategy")["pass_rate"].mean().reset_index()
    strat_summary = strat_summary.sort_values("pass_rate", ascending=False)
    return strat_summary


def _load_embeddings_summary(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        LOGGER.warning("Embeddings ablation metrics missing: %s", path)
        return None
    df = pd.read_csv(path)
    if "embedding" not in df.columns:
        return None
    metric = "f1" if "f1" in df.columns else next((col for col in ["accuracy", "roc_auc", "r2"] if col in df.columns), None)
    if not metric:
        return None
    summary = df.groupby("embedding")[metric].mean().reset_index()
    summary = summary.rename(columns={metric: "score"})
    summary["metric"] = metric
    return summary


def _pivot_rl_summary(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return summary
    pivot = summary.pivot_table(index=["rl_type", "agent"], columns="metric", values="mean").reset_index()
    return pivot


def _build_end_to_end_summary(
    strategy_summary: pd.DataFrame,
    rl_pivot: pd.DataFrame,
    embeddings_summary: pd.DataFrame | None,
    supervised_summary: pd.DataFrame,
    out_dir: Path,
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    best_strategy = strategy_summary.iloc[0] if not strategy_summary.empty else None
    best_pass_rate = float(best_strategy["pass_rate"]) if best_strategy is not None else np.nan
    best_strategy_name = str(best_strategy["strategy"]) if best_strategy is not None else "N/A"
    rl_best_multi = None
    rl_best_single = None
    if not rl_pivot.empty:
        multi = rl_pivot[rl_pivot["rl_type"] == "multi_agent"]
        single = rl_pivot[rl_pivot["rl_type"] == "single_agent"]
        if not multi.empty and "avg_reward" in multi.columns:
            rl_best_multi = multi.sort_values("avg_reward", ascending=False).iloc[0]
        if not single.empty and "avg_reward" in single.columns:
            rl_best_single = single.sort_values("avg_reward", ascending=False).iloc[0]
    best_rl_row = rl_best_multi or rl_best_single
    random_rl_row = rl_pivot[rl_pivot["agent"] == "random"].iloc[0] if ("agent" in rl_pivot.columns and not rl_pivot[rl_pivot["agent"] == "random"].empty) else None
    skill_rl_row = rl_pivot[rl_pivot["agent"].str.contains("skill", case=False, na=False)].iloc[0] if "agent" in rl_pivot.columns and not rl_pivot.empty else None

    def _mk_row(name: str, rl_row: pd.Series | None, extra: Dict[str, object] | None = None) -> Dict[str, object]:
        row: Dict[str, object] = {
            "variant": name,
            "pass_rate": best_pass_rate,
            "failure_rate": 1 - best_pass_rate if pd.notna(best_pass_rate) else np.nan,
            "avg_reward": float(rl_row["avg_reward"]) if rl_row is not None and "avg_reward" in rl_row else np.nan,
            "win_rate": float(rl_row["win_rate"]) if rl_row is not None and "win_rate" in rl_row else np.nan,
            "starved_tasks": float(rl_row["starved_tasks"]) if rl_row is not None and "starved_tasks" in rl_row else np.nan,
            "notes": "",
        }
        if extra:
            row.update(extra)
        return row

    if best_rl_row is not None:
        rows.append(
            _mk_row(
                "full",
                best_rl_row,
                {"notes": f"{best_strategy_name} + {best_rl_row['agent']} ({best_rl_row['rl_type']})"},
            )
        )
    if random_rl_row is not None:
        rows.append(_mk_row("no_rl_allocation", random_rl_row, {"notes": "Random agent allocation"}))
    if rl_best_single is not None:
        rows.append(_mk_row("no_multi_agent", rl_best_single, {"notes": f"Best single-agent: {rl_best_single['agent']}"}))
    if skill_rl_row is not None:
        rows.append(_mk_row("predictor_only", skill_rl_row, {"notes": "Skill-match heuristic"}))

    if embeddings_summary is not None and not embeddings_summary.empty:
        baseline = embeddings_summary[embeddings_summary["embedding"].str.contains("baseline", case=False, na=False)]
        baseline_score = baseline["score"].mean() if not baseline.empty else embeddings_summary["score"].min()
        graph_score = embeddings_summary["score"].max()
        rows.append(
            {
                "variant": "no_graph_embeddings",
                "pass_rate": best_pass_rate,
                "failure_rate": 1 - best_pass_rate if pd.notna(best_pass_rate) else np.nan,
                "avg_reward": np.nan,
                "win_rate": np.nan,
                "starved_tasks": np.nan,
                "embedding_score": float(baseline_score),
                "notes": "Baseline embedding configuration",
            }
        )
        rows.append(
            {
                "variant": "graph_embeddings",
                "pass_rate": best_pass_rate,
                "failure_rate": 1 - best_pass_rate if pd.notna(best_pass_rate) else np.nan,
                "avg_reward": np.nan,
                "win_rate": np.nan,
                "starved_tasks": np.nan,
                "embedding_score": float(graph_score),
                "notes": "Best embedding configuration",
            }
        )

    if not supervised_summary.empty:
        ordering_cols = [col for col in ["f1", "roc_auc", "r2"] if col in supervised_summary.columns]
        sorted_supervised = supervised_summary.sort_values(by=ordering_cols, ascending=False) if ordering_cols else supervised_summary
        best_supervised = sorted_supervised.iloc[0]
        rows.append(
            {
                "variant": "predictor_only_performance",
                "pass_rate": np.nan,
                "failure_rate": np.nan,
                "avg_reward": np.nan,
                "win_rate": np.nan,
                "starved_tasks": np.nan,
                "embedding_score": float(best_supervised.get("f1", best_supervised.get("roc_auc", best_supervised.get("r2", np.nan)))),
                "notes": f"Best supervised feature mode: {best_supervised['feature_mode']}",
            }
        )

    summary = pd.DataFrame(rows).drop_duplicates(subset=["variant"]).reset_index(drop=True)
    summary.to_csv(out_dir / "end_to_end_ablation_summary.csv", index=False)
    if not summary.empty:
        write_latex_table(summary, out_dir / "table_end_to_end.tex")
        metrics = [metric for metric in ["pass_rate", "win_rate", "starved_tasks"] if metric in summary.columns]
        if metrics:
            fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4))
            if len(metrics) == 1:
                axes = [axes]
            for metric, ax in zip(metrics, axes):
                plot_df = summary[["variant", metric]].dropna()
                x = np.arange(len(plot_df))
                ax.bar(x, plot_df[metric], color="#ffa600")
                ax.set_title(metric.replace("_", " ").title())
                ax.set_xticks(x)
                ax.set_xticklabels(plot_df["variant"], rotation=30, ha="right")
                ax.grid(axis="y", linestyle="--", alpha=0.4)
            fig.tight_layout()
            fig.savefig(out_dir / "fig_end_to_end_ablation.png", dpi=200)
            plt.close(fig)
    return summary


# ---------------------------------------------------------------------------
# CLI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile supervised, RL, and decomposition artifacts into a paper-ready bundle.")
    parser.add_argument("--out_dir", type=Path, default=PathConfig().reports_root / "final", help="Directory for compiled artifacts")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for bootstrapping")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = parse_args()
    out_dir = args.out_dir
    _ensure_out_dir(out_dir)
    rng = np.random.default_rng(args.seed)
    path_cfg = PathConfig()
    input_paths: List[Path] = []

    supervised_paths = [
        path_cfg.tables_dir / "supervised_metrics_multimodal.csv",
        path_cfg.tables_dir / "supervised_metrics_text_only.csv",
        path_cfg.tables_dir / "supervised_metrics_text_time.csv",
        path_cfg.tables_dir / "supervised_metrics_text_metadata.csv",
    ]
    supervised_summary = _summarize_supervised(supervised_paths, out_dir)
    input_paths.extend(supervised_paths)

    single_rl_paths = sorted((path_cfg.reports_root / "decomposition").glob("rl_decomposition_metrics_seed_*.csv"))
    multi_rl_paths = sorted((path_cfg.reports_root / "decomposition").glob("rl_multiagent_metrics_seed_*.csv"))
    rl_result = _summarize_rl(single_rl_paths, multi_rl_paths, out_dir, rng)
    input_paths.extend(single_rl_paths)
    input_paths.extend(multi_rl_paths)

    cost_path = path_cfg.reports_root / "decomposition" / "cost_frontier.csv"
    cost_vs_path = path_cfg.reports_root / "decomposition" / "cost_vs_quality.csv"
    _summarize_cost_frontier(cost_path, cost_vs_path, out_dir)
    input_paths.extend([cost_path, cost_vs_path])

    strategy_path = path_cfg.reports_root / "decomposition" / "strategy_comparison.csv"
    embeddings_path = path_cfg.reports_root / "tables" / "embeddings_ablation.csv"
    strategy_summary = _load_strategy_summary(strategy_path)
    embeddings_summary = _load_embeddings_summary(embeddings_path)
    rl_pivot = _pivot_rl_summary(rl_result.summary)
    _build_end_to_end_summary(strategy_summary, rl_pivot, embeddings_summary, supervised_summary, out_dir)
    input_paths.extend([strategy_path, embeddings_path])

    write_metadata(
        out_dir,
        seeds=[args.seed],
        config={"out_dir": str(out_dir), "seed": args.seed},
        inputs=input_paths,
    )
    LOGGER.info("Wrote compiled artifacts to %s", out_dir)


if __name__ == "__main__":  # pragma: no cover
    main()
