"""Graph embedding utilities with a lightweight DeepWalk/skip-gram trainer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import networkx as nx
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F

from src.config import EmbeddingConfig, PathConfig


def build_bipartite_graph(interactions: pd.DataFrame) -> nx.Graph:
    graph = nx.Graph()
    for _, row in interactions.iterrows():
        task_node = f"task::{row['task_id']}"
        worker_node = f"worker::{row['worker_id']}"
        graph.add_node(task_node, bipartite="task")
        graph.add_node(worker_node, bipartite="worker")
        weight = 1.0 + float(row.get("submitted", 0)) + float(row.get("score", 0)) / 100.0
        graph.add_edge(task_node, worker_node, weight=weight)
    return graph


def _random_walk(graph: nx.Graph, start: str, length: int, rng: np.random.Generator) -> List[str]:
    walk = [start]
    current = start
    for _ in range(length - 1):
        neighbors = list(graph.neighbors(current))
        if not neighbors:
            break
        weights = np.array([graph[current][nbr].get("weight", 1.0) for nbr in neighbors], dtype=float)
        probabilities = weights / weights.sum()
        current = rng.choice(neighbors, p=probabilities)
        walk.append(current)
    return walk


def _generate_walks(graph: nx.Graph, cfg: EmbeddingConfig, rng: np.random.Generator) -> List[List[str]]:
    nodes = list(graph.nodes())
    walks: List[List[str]] = []
    for node in nodes:
        for _ in range(cfg.num_walks):
            walks.append(_random_walk(graph, node, cfg.walk_length, rng))
    return walks


def _build_training_pairs(walks: Sequence[Sequence[str]], window: int, node_to_idx: Dict[str, int]) -> Tuple[np.ndarray, np.ndarray]:
    centers: List[int] = []
    contexts: List[int] = []
    for walk in walks:
        encoded = [node_to_idx[node] for node in walk]
        for i, center in enumerate(encoded):
            start = max(0, i - window)
            end = min(len(encoded), i + window + 1)
            for j in range(start, end):
                if i == j:
                    continue
                centers.append(center)
                contexts.append(encoded[j])
    if not centers:
        raise ValueError("Insufficient co-occurrences to train embeddings")
    return np.array(centers, dtype=np.int64), np.array(contexts, dtype=np.int64)


class SkipGramNS(nn.Module):
    def __init__(self, num_nodes: int, embedding_dim: int) -> None:
        super().__init__()
        self.input_embeddings = nn.Embedding(num_nodes, embedding_dim)
        self.output_embeddings = nn.Embedding(num_nodes, embedding_dim)
        nn.init.xavier_uniform_(self.input_embeddings.weight)
        nn.init.xavier_uniform_(self.output_embeddings.weight)

    def forward(self, center: torch.Tensor, context: torch.Tensor, negatives: torch.Tensor) -> torch.Tensor:
        center_emb = self.input_embeddings(center)
        context_emb = self.output_embeddings(context)
        negative_emb = self.output_embeddings(negatives)

        pos_score = torch.sum(center_emb * context_emb, dim=1)
        pos_loss = F.logsigmoid(pos_score)

        neg_score = torch.bmm(negative_emb, center_emb.unsqueeze(2)).squeeze(2)
        neg_loss = F.logsigmoid(-neg_score).sum(dim=1)
        loss = -(pos_loss + neg_loss).mean()
        return loss


def _train_skipgram(
    centers: np.ndarray,
    contexts: np.ndarray,
    num_nodes: int,
    cfg: EmbeddingConfig,
) -> np.ndarray:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SkipGramNS(num_nodes, cfg.dimensions).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)
    dataset_size = centers.shape[0]

    for epoch in range(cfg.epochs):
        permutation = np.random.permutation(dataset_size)
        centers = centers[permutation]
        contexts = contexts[permutation]
        for start in range(0, dataset_size, cfg.batch_size):
            end = min(start + cfg.batch_size, dataset_size)
            center_batch = torch.tensor(centers[start:end], dtype=torch.long, device=device)
            context_batch = torch.tensor(contexts[start:end], dtype=torch.long, device=device)
            neg_batch = torch.randint(0, num_nodes, (center_batch.size(0), cfg.negative_samples), device=device)
            loss = model(center_batch, context_batch, neg_batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    return model.input_embeddings.weight.detach().cpu().numpy()


def train_node2vec(
    interactions: pd.DataFrame,
    config: EmbeddingConfig | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cfg = config or EmbeddingConfig()
    graph = build_bipartite_graph(interactions)
    if graph.number_of_nodes() == 0:
        raise ValueError("No interactions available for embedding training")

    rng = np.random.default_rng(cfg.seed)
    walks = _generate_walks(graph, cfg, rng)
    nodes = list(graph.nodes())
    node_to_idx = {node: idx for idx, node in enumerate(nodes)}
    centers, contexts = _build_training_pairs(walks, cfg.window, node_to_idx)
    embedding_matrix = _train_skipgram(centers, contexts, len(nodes), cfg)

    task_rows = []
    worker_rows = []
    for node, idx in node_to_idx.items():
        vector = embedding_matrix[idx]
        prefix, node_id = node.split("::", 1)
        record = {"id": node_id, **{f"dim_{i}": float(v) for i, v in enumerate(vector)}}
        if prefix == "task":
            task_rows.append(record)
        else:
            worker_rows.append(record)

    task_df = pd.DataFrame(task_rows)
    worker_df = pd.DataFrame(worker_rows)
    return task_df, worker_df


def save_embeddings(
    task_df: pd.DataFrame,
    worker_df: pd.DataFrame,
    output_dir: Path | None = None,
) -> Dict[str, Path]:
    cfg = PathConfig()
    target_dir = output_dir or cfg.embeddings_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    task_array = task_df.filter(like="dim_").to_numpy()
    worker_array = worker_df.filter(like="dim_").to_numpy()

    task_path = target_dir / "tasks.npy"
    worker_path = target_dir / "workers.npy"
    np.save(task_path, task_array)
    np.save(worker_path, worker_array)

    with (target_dir / "task_index.json").open("w", encoding="utf-8") as fp:
        json.dump(task_df["id"].tolist(), fp, indent=2)
    with (target_dir / "worker_index.json").open("w", encoding="utf-8") as fp:
        json.dump(worker_df["id"].tolist(), fp, indent=2)

    task_df.to_csv(target_dir / "task_embeddings.csv", index=False)
    worker_df.to_csv(target_dir / "worker_embeddings.csv", index=False)

    return {"task": task_path, "worker": worker_path}


__all__ = ["build_bipartite_graph", "train_node2vec", "save_embeddings"]
