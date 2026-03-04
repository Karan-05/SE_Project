"""Self-supervised representation learning pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from src.config import EmbeddingConfig, PathConfig, SupervisedConfig
from src.models.embeddings import save_embeddings, train_node2vec
from src.models.supervised import SupervisedExperiment


class EmbeddingPipeline:
    def __init__(
        self,
        processed_dir: Path | None = None,
        embedding_dir: Path | None = None,
        embedding_config: EmbeddingConfig | None = None,
    ) -> None:
        paths = PathConfig()
        self.processed_dir = processed_dir or paths.processed_data
        self.embedding_dir = embedding_dir or paths.embeddings_dir
        self.embedding_config = embedding_config or EmbeddingConfig()
        self.paths = paths

    def _load_interactions(self) -> pd.DataFrame:
        interactions_path = self.processed_dir / "interactions.parquet"
        if not interactions_path.exists():
            raise FileNotFoundError(f"Missing interactions parquet at {interactions_path}")
        return pd.read_parquet(interactions_path)

    def train(self) -> Dict[str, Path]:
        interactions = self._load_interactions()
        task_df, worker_df = train_node2vec(interactions, self.embedding_config)
        return save_embeddings(task_df, worker_df, self.embedding_dir)

    def evaluate_with_supervised(self) -> pd.DataFrame:
        baseline_cfg = SupervisedConfig(use_embeddings=False)
        baseline = SupervisedExperiment(
            processed_dir=self.processed_dir,
            config=baseline_cfg,
            feature_mode="text_time",
        ).run()
        enriched_cfg = SupervisedConfig(use_embeddings=True)
        enriched = SupervisedExperiment(
            processed_dir=self.processed_dir,
            config=enriched_cfg,
            feature_mode="multimodal",
        ).run()
        baseline["embedding"] = "baseline"
        enriched["embedding"] = "node2vec"
        combined = pd.concat([baseline, enriched], ignore_index=True)
        output_path = self.paths.tables_dir / "embeddings_ablation.csv"
        combined.to_csv(output_path, index=False)

        summary = combined.loc[combined["split"] == "test"].groupby(
            ["target", "embedding"]
        )["f1"].mean().reset_index()
        pivot = summary.pivot(index="target", columns="embedding", values="f1")
        improvement_lines = []
        for target, row in pivot.iterrows():
            base = row.get("baseline", float("nan"))
            enriched_val = row.get("node2vec", float("nan"))
            improvement = enriched_val - base if pd.notnull(base) and pd.notnull(enriched_val) else float("nan")
            improvement_lines.append(f"- **{target}**: ΔF1={improvement:.4f}")
        summary_path = self.paths.reports_root / "embeddings_summary.md"
        summary_path.write_text(
            "# Embedding Impact\n\n" + "\n".join(improvement_lines) + "\n",
            encoding="utf-8",
        )
        return combined


__all__ = ["EmbeddingPipeline"]
