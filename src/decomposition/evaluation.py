"""Evaluation helpers aggregating decomposition, RL, and multi-agent reports."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np
import pandas as pd

from src.config import PathConfig

REPORT_DIR = PathConfig().reports_root / "decomposition"
STRATEGY_FILE = REPORT_DIR / "strategy_comparison.csv"
RL_AGG_FILE = REPORT_DIR / "rl_metrics_aggregate.csv"
MULTI_AGG_FILE = REPORT_DIR / "rl_multiagent_aggregate.csv"
PER_TYPE_FILE = REPORT_DIR / "per_type_results.csv"
COST_FRONTIER_FILE = REPORT_DIR / "cost_frontier.csv"
COST_FRONTIER_MD = REPORT_DIR / "cost_frontier.md"
LEADERBOARD_MD = REPORT_DIR / "leaderboard.md"
LATEX_TABLES = REPORT_DIR / "latex_tables.tex"
LATEX_SNIPPETS = REPORT_DIR / "latex_snippets.tex"


def _safe_read(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing report: {path}")
    return pd.read_csv(path)


def bootstrap_ci(values: Iterable[float], confidence: float = 0.95, iters: int = 2000, seed: int = 13) -> Tuple[float, float]:
    arr = np.array(list(values), dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    rng = np.random.default_rng(seed)
    boot_means = []
    for _ in range(iters):
        sample = rng.choice(arr, size=arr.size, replace=True)
        boot_means.append(float(np.mean(sample)))
    alpha = 1 - confidence
    return float(np.quantile(boot_means, alpha / 2)), float(np.quantile(boot_means, 1 - alpha / 2))


def aggregate_rl_seed_reports() -> pd.DataFrame:
    seed_files = sorted(REPORT_DIR.glob("rl_decomposition_metrics_seed_*.csv"))
    if not seed_files:
        raise FileNotFoundError("No rl_decomposition_metrics_seed_*.csv files found. Run make decomp_rl_seeds first.")
    frames = []
    for file in seed_files:
        df = pd.read_csv(file)
        if "seed" not in df.columns:
            try:
                seed = int(file.stem.split("_")[-1])
            except ValueError:
                seed = -1
            df["seed"] = seed
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)

    rows = []
    metrics = ["avg_reward", "win_rate", "starved_tasks", "deadline_misses"]
    for agent, agent_df in full.groupby("agent"):
        row = {"agent": agent}
        for metric in metrics:
            values = agent_df[metric].to_numpy(dtype=float)
            row[f"{metric}_mean"] = float(np.mean(values))
            row[f"{metric}_std"] = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
            ci_low, ci_high = bootstrap_ci(values)
            row[f"{metric}_ci_low"] = ci_low
            row[f"{metric}_ci_high"] = ci_high
        rows.append(row)
    agg = pd.DataFrame(rows).sort_values("avg_reward_mean", ascending=False)
    agg.to_csv(RL_AGG_FILE, index=False)
    return agg


def aggregate_multiagent_reports() -> pd.DataFrame:
    seed_files = sorted(REPORT_DIR.glob("rl_multiagent_metrics_seed_*.csv"))
    if not seed_files:
        raise FileNotFoundError("No rl_multiagent_metrics_seed_*.csv files found. Run make decomp_multiagent first.")
    frames = [pd.read_csv(file) for file in seed_files]
    full = pd.concat(frames, ignore_index=True)
    metrics = ["avg_reward", "win_rate", "starved_tasks", "dropped_tasks", "deadline_misses"]
    rows = []
    for policy, policy_df in full.groupby("policy"):
        row = {"policy": policy}
        for metric in metrics:
            row[f"{metric}_mean"] = float(np.mean(policy_df[metric]))
            row[f"{metric}_std"] = float(np.std(policy_df[metric], ddof=1)) if len(policy_df) > 1 else 0.0
        row["market_starved_mean"] = float(np.mean(policy_df.get("market_starved", 0)))
        row["market_dropped_mean"] = float(np.mean(policy_df.get("market_dropped", 0)))
        rows.append(row)
    agg = pd.DataFrame(rows).sort_values("avg_reward_mean", ascending=False)
    agg.to_csv(MULTI_AGG_FILE, index=False)
    return agg


def _strategy_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, strat_df in df.groupby("strategy"):
        pass_values = strat_df["pass_rate"].to_numpy(dtype=float)
        tokens = strat_df.get("tokens_used")
        if tokens is not None and tokens.notna().any():
            cost_source = tokens.fillna(strat_df["decomposition_steps"])
        elif "planning_time" in strat_df:
            cost_source = strat_df["planning_time"].fillna(strat_df["decomposition_steps"])
        else:
            cost_source = strat_df["decomposition_steps"]
        mean_pass = float(np.mean(pass_values))
        ci_low, ci_high = bootstrap_ci(pass_values)
        rows.append(
            {
                "strategy": strategy,
                "pass_rate_mean": mean_pass,
                "pass_rate_ci_low": ci_low,
                "pass_rate_ci_high": ci_high,
                "avg_cost": float(np.mean(cost_source)),
            }
        )
    return pd.DataFrame(rows).sort_values("pass_rate_mean", ascending=False)


def _dominates(a_quality: float, a_cost: float, b_quality: float, b_cost: float) -> bool:
    return (a_quality >= b_quality and a_cost <= b_cost) and (a_quality > b_quality or a_cost < b_cost)


def build_cost_frontier(df: pd.DataFrame) -> pd.DataFrame:
    summary = _strategy_summary(df)
    rows = []
    for _, row in summary.iterrows():
        rows.append({
            "strategy": row["strategy"],
            "quality": row["pass_rate_mean"],
            "cost": row["avg_cost"],
        })
    frontier_df = pd.DataFrame(rows)
    pareto_flags = []
    for idx, row in frontier_df.iterrows():
        dominated = False
        for jdx, other in frontier_df.iterrows():
            if idx == jdx:
                continue
            if _dominates(other["quality"], other["cost"], row["quality"], row["cost"]):
                dominated = True
                break
        pareto_flags.append(not dominated)
    frontier_df["on_frontier"] = pareto_flags
    frontier_df.to_csv(COST_FRONTIER_FILE, index=False)

    summary_lines = ["# Cost vs Quality Frontier", ""]
    for _, row in frontier_df.sort_values(["on_frontier", "quality"], ascending=[False, False]).iterrows():
        badge = "(frontier)" if row["on_frontier"] else ""
        summary_lines.append(
            f"- **{row['strategy']}** quality={row['quality']:.3f} cost={row['cost']:.2f} {badge}".strip()
        )
    COST_FRONTIER_MD.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return frontier_df


def per_type_results(df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        df.groupby(["task_type", "task_difficulty", "split", "strategy"])  # type: ignore[arg-type]
        ["pass_rate"].mean()
        .reset_index()
        .rename(columns={"pass_rate": "avg_pass_rate"})
    )
    grouped.to_csv(PER_TYPE_FILE, index=False)
    return grouped


def generate_reports(
    rl_agg: pd.DataFrame | None = None,
    multi_agg: pd.DataFrame | None = None,
    build_frontier: bool = True,
) -> None:
    strategy_df = _safe_read(STRATEGY_FILE)
    if rl_agg is None and RL_AGG_FILE.exists():
        rl_agg = _safe_read(RL_AGG_FILE)
    if rl_agg is None:
        raise FileNotFoundError("RL aggregate metrics missing. Run evaluation with --aggregate-seeds.")

    strategy_summary = _strategy_summary(strategy_df)
    frontier_df = build_cost_frontier(strategy_df) if build_frontier else _safe_read(COST_FRONTIER_FILE)
    per_type_df = per_type_results(strategy_df)

    leaderboard_lines = ["# Decomposition Strategy Leaderboard", ""]
    for _, row in strategy_summary.iterrows():
        ci_span = row["pass_rate_ci_high"] - row["pass_rate_ci_low"]
        leaderboard_lines.append(
            f"- **{row['strategy']}** pass-rate={row['pass_rate_mean']:.3f} ± {ci_span/2:.3f}, avg-cost={row['avg_cost']:.2f}"
        )
    LEADERBOARD_MD.write_text("\n".join(leaderboard_lines) + "\n", encoding="utf-8")

    latex_blocks = ["% Auto-generated tables", ""]
    latex_blocks.append(strategy_summary[[
        "strategy",
        "pass_rate_mean",
        "pass_rate_ci_low",
        "pass_rate_ci_high",
        "avg_cost",
    ]].to_latex(index=False, float_format=lambda x: f"{x:.3f}"))
    rl_table = rl_agg[[
        "agent",
        "avg_reward_mean",
        "avg_reward_ci_low",
        "avg_reward_ci_high",
        "win_rate_mean",
        "win_rate_ci_low",
        "win_rate_ci_high",
        "starved_tasks_mean",
        "starved_tasks_ci_low",
        "starved_tasks_ci_high",
        "deadline_misses_mean",
        "deadline_misses_ci_low",
        "deadline_misses_ci_high",
    ]]
    latex_blocks.append("% RL aggregate metrics with 95% CI")
    latex_blocks.append(rl_table.to_latex(index=False, float_format=lambda x: f"{x:.3f}"))
    latex_blocks.append("% Per-type results")
    latex_blocks.append(per_type_df.head(30).to_latex(index=False, float_format=lambda x: f"{x:.3f}"))
    if multi_agg is not None:
        latex_blocks.append("% Multi-agent aggregate")
        latex_blocks.append(multi_agg.to_latex(index=False, float_format=lambda x: f"{x:.3f}"))
    latex_blocks.append("% Cost-quality frontier")
    latex_blocks.append(frontier_df.to_latex(index=False, float_format=lambda x: f"{x:.3f}"))
    LATEX_TABLES.write_text("\n".join(latex_blocks), encoding="utf-8")

    top_strategy = strategy_summary.iloc[0]
    top_agent = rl_agg.sort_values("avg_reward_mean", ascending=False).iloc[0]
    snippet = (
        "\\paragraph{Decomposition Lab Summary} "
        f"{top_strategy['strategy']} leads with {top_strategy['pass_rate_mean']:.2%} (95% CI "
        f"{top_strategy['pass_rate_ci_low']:.2%}--{top_strategy['pass_rate_ci_high']:.2%}), while "
        f"{top_agent['agent']} achieves {top_agent['avg_reward_mean']:.2f} average reward."
    )
    if multi_agg is not None and not multi_agg.empty:
        best_policy = multi_agg.iloc[0]
        snippet += (
            f" Multi-agent play highlights {best_policy['policy']} with reward {best_policy['avg_reward_mean']:.2f} "
            f"and market starved tasks {best_policy['market_starved_mean']:.2f}."
        )
    LATEX_SNIPPETS.write_text(snippet + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate decomposition + RL metrics")
    parser.add_argument("--aggregate-seeds", action="store_true", help="Aggregate per-seed RL metrics")
    parser.add_argument("--multiagent", action="store_true", help="Aggregate multi-agent metrics")
    parser.add_argument("--frontier", action="store_true", help="Recompute cost frontiers and markdown")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = parse_args()
    rl_agg = aggregate_rl_seed_reports() if args.aggregate_seeds else None
    multi_agg = aggregate_multiagent_reports() if args.multiagent else None
    generate_reports(rl_agg, multi_agg, build_frontier=args.frontier or not COST_FRONTIER_FILE.exists())
    print("Wrote leaderboard, per-type summaries, and LaTeX tables to", REPORT_DIR)


if __name__ == "__main__":  # pragma: no cover
    main()
