"""CLI + harness for the Tower-of-Hanoi benchmark."""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib
import pandas as pd

from src.config import PathConfig
from src.utils.reporting import write_metadata
from src.utils.tables import write_latex_table

from .env import TowerOfHanoiEnv
from .strategies import STRATEGY_FACTORIES, BaseStrategy

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

TOKEN_PROXY = "word-count of planner instructions (prompt + response) per move"

LOGGER = logging.getLogger(__name__)


def _instantiate_strategy(name: str, token_budget: int | None) -> BaseStrategy:
    if name not in STRATEGY_FACTORIES:
        raise ValueError(f"Unknown strategy '{name}'. Available: {sorted(STRATEGY_FACTORIES)}")
    return STRATEGY_FACTORIES[name](token_budget)


def run_episode(
    strategy_name: str,
    n_disks: int,
    seed: int,
    token_budget: int | None,
    max_steps: int,
) -> Dict[str, float | int | str]:
    env = TowerOfHanoiEnv(n_disks=n_disks)
    strategy = _instantiate_strategy(strategy_name, token_budget=token_budget)
    strategy.reset(n_disks=n_disks, seed=seed, goal_peg=env.goal_peg)
    start = time.perf_counter()
    success = 0
    for _ in range(max_steps):
        if env.is_solved():
            success = 1
            break
        move = strategy.select_move(env)
        env.apply_move(move)
        if env.is_solved():
            success = 1
            break
    wall = time.perf_counter() - start
    moves_taken = env.moves_taken
    return {
        "n_disks": n_disks,
        "strategy": strategy_name,
        "seed": seed,
        "success": success,
        "moves_taken": moves_taken,
        "optimal_moves": env.optimal_moves,
        "excess_moves": moves_taken - env.optimal_moves,
        "token_estimate": strategy.token_used,
        "wall_time_sec": wall,
    }


def _aggregate_runs(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["n_disks", "strategy"])
        .agg(
            success_rate=("success", "mean"),
            mean_tokens=("token_estimate", "mean"),
            median_tokens=("token_estimate", "median"),
            mean_moves=("moves_taken", "mean"),
            median_moves=("moves_taken", "median"),
        )
        .reset_index()
    )


def _plot_success(summary: pd.DataFrame, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    for strategy, group in summary.groupby("strategy"):
        ax.plot(group["n_disks"], group["success_rate"], marker="o", label=strategy)
    ax.set_xlabel("Number of disks")
    ax.set_ylabel("Success rate")
    ax.set_ylim(-0.05, 1.05)
    ax.grid(alpha=0.3, linestyle="--")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "fig_success_rate.png", dpi=200)
    plt.close(fig)


def _plot_pareto(summary: pd.DataFrame, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    for strategy, group in summary.groupby("strategy"):
        ax.scatter(group["mean_tokens"], group["success_rate"], label=strategy, s=45)
    ax.set_xlabel("Mean token estimate")
    ax.set_ylabel("Success rate")
    ax.grid(alpha=0.3, linestyle="--")
    ax.legend(title="Strategy")
    fig.tight_layout()
    fig.savefig(out_dir / "fig_pareto.png", dpi=200)
    plt.close(fig)


def run_benchmark(
    out_dir: Path,
    *,
    seeds: Sequence[int],
    min_disks: int,
    max_disks: int,
    strategies: Sequence[str],
    token_budget: int | None,
    max_steps_multiplier: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, float | int | str]] = []
    for n_disks in range(min_disks, max_disks + 1):
        optimal = TowerOfHanoiEnv(n_disks).optimal_moves
        max_steps = max(1, int(max_steps_multiplier * optimal))
        for seed in seeds:
            for strategy_name in strategies:
                rows.append(run_episode(strategy_name, n_disks, seed, token_budget, max_steps=max_steps))
    runs = pd.DataFrame(rows)
    runs_path = out_dir / "tower_of_hanoi_runs.csv"
    runs.to_csv(runs_path, index=False)
    summary = _aggregate_runs(runs)
    summary_path = out_dir / "tower_of_hanoi_summary.csv"
    summary.to_csv(summary_path, index=False)
    summary.to_json(out_dir / "summary.json", orient="records", indent=2)
    _plot_success(summary, out_dir)
    _plot_pareto(summary, out_dir)
    write_latex_table(summary, out_dir / "table_toh.tex")
    return runs, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tower-of-Hanoi benchmark harness")
    default_out = PathConfig().reports_root / "llm_bench" / "tower_of_hanoi"
    parser.add_argument("--out_dir", type=Path, default=default_out, help="Directory for benchmark outputs")
    parser.add_argument("--seeds", type=int, default=5, help="Number of random seeds to evaluate")
    parser.add_argument("--base_seed", type=int, default=0, help="Base seed offset")
    parser.add_argument("--min_disks", type=int, default=4, help="Minimum number of disks")
    parser.add_argument("--max_disks", type=int, default=10, help="Maximum number of disks")
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=["full_decomposition", "select_then_decompose"],
        help="Strategies to evaluate",
    )
    parser.add_argument("--token_budget", type=int, default=None, help="Token budget for adaptive strategies")
    parser.add_argument("--max_steps_multiplier", type=float, default=3.0, help="Max steps allowed vs optimal")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    args = parse_args()
    seeds = [args.base_seed + idx for idx in range(args.seeds)]
    runs, summary = run_benchmark(
        args.out_dir,
        seeds=seeds,
        min_disks=args.min_disks,
        max_disks=args.max_disks,
        strategies=args.strategies,
        token_budget=args.token_budget,
        max_steps_multiplier=args.max_steps_multiplier,
    )
    write_metadata(
        args.out_dir,
        seeds=seeds,
        config={
            "min_disks": args.min_disks,
            "max_disks": args.max_disks,
            "strategies": args.strategies,
            "token_budget": args.token_budget,
            "max_steps_multiplier": args.max_steps_multiplier,
            "token_proxy": TOKEN_PROXY,
        },
        inputs=[
            Path(__file__),
            Path(__file__).with_name("env.py"),
            Path(__file__).with_name("strategies.py"),
        ],
    )
    LOGGER.info("Completed Tower-of-Hanoi benchmark → %s (runs=%d)", args.out_dir, len(runs))


if __name__ == "__main__":
    main()
