"""CLI entrypoint for supervised outcome prediction experiments."""
from __future__ import annotations

import argparse
from pathlib import Path

from src.config import PathConfig, SupervisedConfig
from src.models.supervised import SupervisedExperiment, run_ablation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train supervised baselines")
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument("--feature-mode", choices=["text_only", "text_metadata", "text_time", "multimodal"], default="multimodal")
    parser.add_argument("--use-embeddings", action="store_true", help="Include learned embeddings")
    parser.add_argument("--ablation", action="store_true", help="Run all feature ablations")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    processed_dir = args.processed_dir or PathConfig().processed_data
    if args.ablation:
        run_ablation(
            processed_dir=processed_dir,
            feature_modes=["text_only", "text_metadata", "text_time", "multimodal"],
        )
        return
    cfg = SupervisedConfig(use_embeddings=args.use_embeddings)
    experiment = SupervisedExperiment(
        processed_dir=processed_dir,
        config=cfg,
        feature_mode=args.feature_mode,
    )
    metrics = experiment.run()
    print(metrics.head())


if __name__ == "__main__":
    main()
