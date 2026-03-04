"""Train Node2Vec embeddings and evaluate their impact."""
from __future__ import annotations

import argparse
from pathlib import Path

from src.config import EmbeddingConfig, PathConfig
from src.models.self_supervised import EmbeddingPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train worker/task embeddings")
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument("--embedding-dir", type=Path, default=None)
    parser.add_argument("--dimensions", type=int, default=64)
    parser.add_argument("--walk-length", type=int, default=30)
    parser.add_argument("--num-walks", type=int, default=20)
    parser.add_argument("--window", type=int, default=5)
    parser.add_argument("--negative-samples", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--skip-eval", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    embedding_cfg = EmbeddingConfig(
        dimensions=args.dimensions,
        walk_length=args.walk_length,
        num_walks=args.num_walks,
        window=args.window,
        negative_samples=args.negative_samples,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
    )
    pipeline = EmbeddingPipeline(
        processed_dir=args.processed_dir or PathConfig().processed_data,
        embedding_dir=args.embedding_dir or PathConfig().embeddings_dir,
        embedding_config=embedding_cfg,
    )
    pipeline.train()
    if not args.skip_eval:
        pipeline.evaluate_with_supervised()


if __name__ == "__main__":
    main()
