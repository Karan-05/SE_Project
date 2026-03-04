"""Global configuration helpers for the research pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PathConfig:
    """Convenience accessor for canonical project directories."""

    raw_data: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "raw")
    processed_data: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "processed")
    reports_root: Path = field(default_factory=lambda: PROJECT_ROOT / "reports")
    figs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "reports" / "figs")
    tables_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "reports" / "tables")
    embeddings_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "embeddings")
    artifacts_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "artifacts")
    experiments_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "experiments")
    paper_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "paper")

    def ensure(self) -> None:
        for path in [
            self.raw_data,
            self.processed_data,
            self.reports_root,
            self.figs_dir,
            self.tables_dir,
            self.embeddings_dir,
            self.artifacts_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class DataConfig:
    """High-level knobs for synthetic data generation and preprocessing."""

    seed: int = 42
    num_tasks: int = 400
    num_workers: int = 250
    max_registrations_per_task: int = 40
    max_submissions_per_task: int = 20
    market_bucket: str = "M"  # monthly aggregations by default


@dataclass
class SupervisedConfig:
    """Configuration for supervised experiments."""

    text_vectorizer: str = "tfidf"
    test_size: float = 0.2
    val_size: float = 0.2
    random_state: int = 42
    max_tfidf_features: int = 2048
    use_embeddings: bool = False
    classification_targets: Dict[str, str] = field(
        default_factory=lambda: {
            "starved": "classification",
            "failed": "classification",
            "dropped": "classification",
            "has_winner": "classification",
        }
    )
    regression_targets: Dict[str, str] = field(
        default_factory=lambda: {
            "num_submissions": "regression",
            "winning_score": "regression",
        }
    )


@dataclass
class EmbeddingConfig:
    dimensions: int = 64
    walk_length: int = 30
    num_walks: int = 20
    window: int = 5
    negative_samples: int = 5
    epochs: int = 5
    batch_size: int = 512
    learning_rate: float = 0.01
    seed: int = 42


@dataclass
class RLConfig:
    episode_length: int = 30
    num_episodes: int = 100
    max_tasks_per_step: int = 5
    stochastic_reward: bool = True
    seed: int = 42


def ensure_reports_subdirs(path_config: PathConfig | None = None) -> None:
    cfg = path_config or PathConfig()
    cfg.ensure()


__all__ = [
    "PROJECT_ROOT",
    "PathConfig",
    "DataConfig",
    "SupervisedConfig",
    "EmbeddingConfig",
    "RLConfig",
    "ensure_reports_subdirs",
]
