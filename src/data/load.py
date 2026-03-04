"""Raw data loaders and synthetic generators for coding marketplace research."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from src.config import DataConfig, PathConfig

RAW_FILENAMES = {
    "tasks": "tasks.csv",
    "workers": "workers.csv",
    "interactions": "interactions.csv",
}


def load_raw_exports(raw_dir: Path | None = None) -> Dict[str, pd.DataFrame]:
    """Load pre-exported CSV snapshots if they exist."""

    path_cfg = PathConfig()
    raw_root = raw_dir or path_cfg.raw_data
    data: Dict[str, pd.DataFrame] = {}
    for key, filename in RAW_FILENAMES.items():
        file_path = raw_root / filename
        if file_path.exists():
            data[key] = pd.read_csv(file_path)
    return data


def _sample_tags(rng: np.random.Generator, k: int) -> str:
    vocab = [
        "python",
        "javascript",
        "react",
        "nodejs",
        "sql",
        "aws",
        "docker",
        "ml",
        "ai",
        "java",
        "go",
        "rust",
    ]
    return ",".join(sorted(rng.choice(vocab, size=k, replace=False).tolist()))


def _sample_track(rng: np.random.Generator) -> str:
    return rng.choice(["Dev", "DS", "QA", "Design", "Blockchain"])


def _sample_platform(rng: np.random.Generator) -> str:
    return rng.choice(["Topcoder", "Kaggle", "CrowdWorks"])


def _skill_vector(rng: np.random.Generator, dim: int = 8) -> Tuple[float, ...]:
    return tuple(np.round(rng.normal(0, 1, size=dim), 3))


def generate_synthetic_data(config: DataConfig | None = None) -> Dict[str, pd.DataFrame]:
    cfg = config or DataConfig()
    rng = np.random.default_rng(cfg.seed)

    base_time = datetime(2023, 1, 1)
    tasks_records = []
    interactions_records = []

    worker_ids = [f"worker_{i:05d}" for i in range(cfg.num_workers)]
    worker_records = []
    for worker_id in worker_ids:
        skill_vec = _skill_vector(rng)
        worker_records.append(
            {
                "worker_id": worker_id,
                "skill_vector": ";".join(map(str, skill_vec)),
                "past_tasks_count": int(rng.integers(5, 200)),
                "past_wins": int(rng.integers(0, 25)),
                "domain_tags": _sample_tags(rng, k=int(rng.integers(2, 5))),
            }
        )

    for task_idx in range(cfg.num_tasks):
        task_id = f"task_{task_idx:05d}"
        posted_time = base_time + timedelta(days=int(rng.integers(0, 365)))
        duration = int(rng.integers(3, 30))
        deadline = posted_time + timedelta(days=duration)
        prize = float(np.round(rng.uniform(250, 5000), 2))
        difficulty = int(rng.integers(1, 5))
        tags = _sample_tags(rng, k=int(rng.integers(2, 5)))
        track = _sample_track(rng)
        platform = _sample_platform(rng)
        company = rng.choice(["Acme", "Globex", "Initech", "Umbrella", "WayneTech"])
        max_reg = min(cfg.max_registrations_per_task, len(worker_ids))
        num_reg = int(rng.integers(1, max_reg + 1))
        num_sub = int(rng.integers(0, min(cfg.max_submissions_per_task, num_reg)))
        has_winner = int(num_sub > 0 and rng.random() > 0.1)
        winning_score = float(np.round(rng.uniform(60, 100) if has_winner else 0.0, 2))
        starved = int(num_sub == 0)
        dropped = int(num_sub == 0 and num_reg > 0)
        failed = int(has_winner == 0)

        tasks_records.append(
            {
                "task_id": task_id,
                "title": f"{track} Challenge {task_idx}",
                "description": f"Solve {track} task {task_idx} with tags {tags}.",
                "tags": tags,
                "tech_stack": tags,
                "prize": prize,
                "difficulty": difficulty,
                "duration": duration,
                "posted_time": posted_time,
                "deadline": deadline,
                "platform": platform,
                "track": track,
                "company": company,
                "num_registrants": num_reg,
                "num_submissions": num_sub,
                "has_winner": has_winner,
                "starved": starved,
                "dropped": dropped,
                "failed": failed,
                "winning_score": winning_score,
            }
        )

        registrants = rng.choice(worker_ids, size=num_reg, replace=False)
        submitted_workers = (
            rng.choice(registrants, size=num_sub, replace=False) if num_sub > 0 else []
        )
        for order, worker_id in enumerate(registrants):
            submitted = worker_id in submitted_workers
            score = float(np.round(rng.uniform(60, 100), 2)) if submitted else 0.0
            interactions_records.append(
                {
                    "worker_id": worker_id,
                    "task_id": task_id,
                    "registered": 1,
                    "submitted": int(submitted),
                    "scored": int(submitted and rng.random() > 0.2),
                    "score": score,
                    "rank": order + 1 if submitted else np.nan,
                    "timestamp": posted_time + timedelta(days=int(rng.integers(0, duration))),
                }
            )

    tasks_df = pd.DataFrame(tasks_records)
    workers_df = pd.DataFrame(worker_records)
    interactions_df = pd.DataFrame(interactions_records)

    return {
        "tasks": tasks_df,
        "workers": workers_df,
        "interactions": interactions_df,
        "metadata": pd.DataFrame([asdict(cfg)]),
    }


def load_or_generate(raw_dir: Path | None = None, config: DataConfig | None = None) -> Dict[str, pd.DataFrame]:
    """Load existing exports; otherwise synthesise realistic stand-ins."""

    exports = load_raw_exports(raw_dir)
    if exports:
        return exports
    return generate_synthetic_data(config)


__all__ = [
    "load_raw_exports",
    "generate_synthetic_data",
    "load_or_generate",
]
