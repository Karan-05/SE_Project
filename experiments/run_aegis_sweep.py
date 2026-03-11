"""Hyper-parameter sweep runner for AEGIS-RL."""
from __future__ import annotations

import argparse
import csv
import itertools
from pathlib import Path
from typing import Dict, List, Tuple

from experiments.run_aegis_rl import (
    AegisAgentConfig,
    AegisEnvConfig,
    run_online_training,
    _default_curriculum_schedule,
)


def _grid() -> List[Dict[str, object]]:
    lrs = [3e-4, 1e-4]
    gammas = [0.95, 0.99]
    epsilon_decays = [0.995, 0.998]
    epsilon_finals = [0.05, 0.1]
    reduced_flags = [False, True]
    warm_start_flags = [0, 5]
    hierarchy_flags = [True, False]
    grid: List[Dict[str, object]] = []
    for lr, gamma, decay, final, reduced, warm, hierarchy in itertools.product(
        lrs, gammas, epsilon_decays, epsilon_finals, reduced_flags, warm_start_flags, hierarchy_flags
    ):
        grid.append(
            {
                "lr": lr,
                "gamma": gamma,
                "epsilon_decay": decay,
                "epsilon_final": final,
                "use_reduced_action_space": reduced,
                "warm_start": warm,
                "enable_hierarchy": hierarchy,
            }
        )
    return grid


def run_sweep(args: argparse.Namespace) -> None:
    sweep_dir = args.output_dir / "sweeps"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    grid = _grid()
    if args.max_configs is not None:
        grid = grid[: args.max_configs]
    seeds = [2026 + i for i in range(3 if args.lightweight else 5)]
    sweep_rows: List[Dict[str, object]] = []
    for idx, config in enumerate(grid):
        for seed in seeds:
            env_cfg = AegisEnvConfig(
                use_reduced_action_space=config["use_reduced_action_space"],
                enable_hierarchy=config["enable_hierarchy"],
            )
            env_cfg.workflow.seed = seed
            env_cfg.reward_log_path = sweep_dir / f"reward_diag_{idx}_seed{seed}.jsonl"
            agent_cfg = AegisAgentConfig(
                lr=config["lr"],
                gamma=config["gamma"],
                epsilon_decay=config["epsilon_decay"],
                epsilon_final=config["epsilon_final"],
            )
            schedule = _default_curriculum_schedule(args.episodes) if args.curriculum else None
            metrics, summary = run_online_training(
                label=f"sweep_{idx}",
                env_config=env_cfg,
                agent_config=agent_cfg,
                output_dir=sweep_dir / f"cfg_{idx}_seed{seed}",
                episodes=args.episodes,
                pretrain_summary=None,
                warm_start_episodes=int(config["warm_start"]),
                curriculum_schedule=schedule,
            )
            sweep_rows.append(
                {
                    "config_id": idx,
                    "seed": seed,
                    "success_rate": summary["success_rate"],
                    "avg_reward": summary["avg_reward"],
                    "budgeted_success": summary.get("budgeted_success", 0.0),
                    "notes": summary.get("notes", ""),
                    "config": config,
                }
            )
    _write_sweep_results(sweep_rows, sweep_dir / "sweep_results.csv")
    _write_top_configs(sweep_rows, sweep_dir / "top_configs.csv")
    _write_sweep_summary(sweep_rows, Path("reports/ase2026_aegis/sweep_summary.md"))


def _write_sweep_results(rows: List[Dict[str, object]], path: Path) -> None:
    fieldnames = ["config_id", "seed", "success_rate", "avg_reward", "budgeted_success", "notes", "config"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            serializable = dict(row)
            serializable["config"] = str(serializable["config"])
            writer.writerow(serializable)


def _write_top_configs(rows: List[Dict[str, object]], path: Path) -> None:
    grouped: Dict[int, List[Dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(int(row["config_id"]), []).append(row)
    ranked: List[Tuple[int, float]] = []
    for cfg_id, samples in grouped.items():
        mean_success = sum(float(s["success_rate"]) for s in samples) / len(samples)
        ranked.append((cfg_id, mean_success))
    ranked.sort(key=lambda x: x[1], reverse=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["config_id", "mean_success"])
        for cfg_id, score in ranked:
            writer.writerow([cfg_id, score])


def _write_sweep_summary(rows: List[Dict[str, object]], path: Path) -> None:
    top = sorted(rows, key=lambda r: r["success_rate"], reverse=True)[:5]
    lines = ["# Sweep Summary", "", "## Top Settings"]
    for entry in top:
        lines.append(
            f"- config {entry['config_id']} seed {entry['seed']}: success {float(entry['success_rate']):.2f}, "
            f"avg reward {float(entry['avg_reward']):.2f}, config {entry['config']}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AEGIS-RL sweep runner")
    parser.add_argument("--output-dir", type=Path, default=Path("results/aegis_rl"))
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--lightweight", action="store_true")
    parser.add_argument("--curriculum", action="store_true", help="Use curriculum schedule inside sweep.")
    parser.add_argument("--max-configs", type=int, default=None, help="Limit number of configurations (for testing).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_sweep(args)


if __name__ == "__main__":
    main()
