"""CLI entrypoint for end-to-end ablation runner."""
from __future__ import annotations

import argparse
from pathlib import Path

from src.experiments.end_to_end import run_end_to_end


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run end-to-end ablation sweeps.")
    parser.add_argument("--config", type=Path, required=True, help="Path to end_to_end.yaml")
    parser.add_argument("--out_dir", type=Path, default=Path("reports") / "end_to_end", help="Output directory")
    parser.add_argument("--seeds", type=int, default=10, help="Number of seeds to evaluate")
    parser.add_argument("--base_seed", type=int, default=1, help="First seed id to use")
    parser.add_argument("--bootstrap_seed", type=int, default=123, help="Random seed for bootstrap CIs")
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = parse_args()
    run_end_to_end(
        args.config,
        args.out_dir,
        num_seeds=args.seeds,
        base_seed=args.base_seed,
        seed=args.bootstrap_seed,
    )


if __name__ == "__main__":
    main()
