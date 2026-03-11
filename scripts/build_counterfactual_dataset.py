"""CLI entry-point for counterfactual override dataset generation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rl.aegis_env import AegisEnvConfig
from src.rl.counterfactual_dataset import CounterfactualDatasetConfig, build_counterfactual_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build counterfactual branch-rollout datasets for override learning.")
    parser.add_argument("--episodes", type=int, default=128, help="Number of teacher episodes to sample (default 128).")
    parser.add_argument("--max-alternatives", type=int, default=3, help="Maximum alternate macros per state (default 3).")
    parser.add_argument("--max-branch-steps", type=int, default=32, help="Maximum macro steps to simulate per branch.")
    parser.add_argument("--min-uncertainty", type=float, default=0.0, help="Only log states with uncertainty >= threshold.")
    parser.add_argument("--min-budget-pressure", type=float, default=0.0, help="Only log states with spent-budget ratio >= threshold.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/aegis_rl/counterfactual"),
        help="Directory for JSON/CSV outputs.",
    )
    parser.add_argument("--seed", type=int, default=2026, help="PRNG seed for alternative sampling.")
    parser.add_argument(
        "--full-action-space",
        action="store_true",
        help="Use the full macro action space (default reduced).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    use_reduced = not args.full_action_space
    env_config = AegisEnvConfig(
        use_reduced_action_space=use_reduced,
        enable_hierarchy=False,
        reward_log_path=args.output_dir / "reward_diag.jsonl",
    )
    dataset_cfg = CounterfactualDatasetConfig(
        episodes=args.episodes,
        max_alternatives=args.max_alternatives,
        max_branch_steps=args.max_branch_steps,
        reduced_action_space=use_reduced,
        min_uncertainty=args.min_uncertainty,
        min_budget_pressure=args.min_budget_pressure,
        seed=args.seed,
    )
    summary = build_counterfactual_dataset(args.output_dir, env_config=env_config, dataset_config=dataset_cfg)
    print(f"Wrote counterfactual datasets to {args.output_dir}")
    print(summary)


if __name__ == "__main__":
    main()
