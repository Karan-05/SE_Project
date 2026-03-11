"""Graph-informed repository and decomposition memory for AEGIS-RL."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, MutableMapping, Optional, Tuple

import numpy as np


@dataclass
class GraphMemoryConfig:
    """Configures lightweight graph tracking."""

    max_nodes: int = 512
    decay: float = 0.95
    enable_symbol_hops: bool = True
    enable_decomposition_tracking: bool = True


@dataclass
class GraphSummary:
    """Compact feature struct returned to policies."""

    visit_ratio: float
    unresolved_dependencies: int
    frontier_size: int
    evidence_diversity: float
    locality_score: float
    coverage_entropy: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [
                self.visit_ratio,
                self.unresolved_dependencies,
                self.frontier_size,
                self.evidence_diversity,
                self.locality_score,
                self.coverage_entropy,
            ],
            dtype=np.float32,
        )

    def as_dict(self) -> Dict[str, float]:
        return {
            "visit_ratio": float(self.visit_ratio),
            "unresolved_dependencies": float(self.unresolved_dependencies),
            "frontier_size": float(self.frontier_size),
            "evidence_diversity": float(self.evidence_diversity),
            "locality_score": float(self.locality_score),
            "coverage_entropy": float(self.coverage_entropy),
        }


class GraphMemory:
    """Tracks repository coverage using adjacency lists and simple statistics."""

    def __init__(self, config: GraphMemoryConfig | None = None) -> None:
        self.config = config or GraphMemoryConfig()
        self.file_visits: MutableMapping[str, float] = {}
        self.symbol_edges: MutableMapping[str, Dict[str, float]] = {}
        self.decomposition_tree: MutableMapping[str, List[str]] = {}
        self.unresolved: set[str] = set()
        self.rng = np.random.default_rng(42)

    def reset(self) -> None:
        self.file_visits.clear()
        self.symbol_edges.clear()
        self.decomposition_tree.clear()
        self.unresolved.clear()

    def record_file_visit(self, path: str, weight: float = 1.0) -> None:
        if not path:
            return
        current = self.file_visits.get(path, 0.0)
        self.file_visits[path] = min(current * self.config.decay + weight, 10.0)

    def record_symbol_jump(self, symbol_from: str, symbol_to: str, relation: str | None = None) -> None:
        if not self.config.enable_symbol_hops:
            return
        if not symbol_from or not symbol_to:
            return
        adjacency = self.symbol_edges.setdefault(symbol_from, {})
        key = f"{symbol_to}:{relation or 'generic'}"
        adjacency[key] = adjacency.get(key, 0.0) * self.config.decay + 1.0

    def record_decomposition(self, node_id: str, children: Iterable[str]) -> None:
        if not self.config.enable_decomposition_tracking:
            return
        child_list = list(children)
        self.decomposition_tree[node_id] = child_list
        self.unresolved.update(child_list)

    def resolve_subtask(self, node_id: str) -> None:
        self.unresolved.discard(node_id)

    def _visit_ratio(self) -> float:
        if not self.file_visits:
            return 0.0
        capped = len(self.file_visits) / float(self.config.max_nodes)
        return float(np.clip(capped, 0.0, 1.0))

    def _frontier_size(self) -> int:
        return sum(len(children) for children in self.decomposition_tree.values())

    def _evidence_diversity(self) -> float:
        weights = np.array(list(self.file_visits.values()), dtype=np.float32)
        if weights.size == 0:
            return 0.0
        probs = weights / np.sum(weights)
        unique = len(self.file_visits)
        diversity = np.sum(probs**2)
        return float(np.clip(1.0 - diversity, 0.0, 1.0)) * min(1.0, unique / 32)

    def _locality_score(self) -> float:
        if not self.symbol_edges:
            return 0.0
        degrees = [len(edges) for edges in self.symbol_edges.values()]
        if not degrees:
            return 0.0
        spread = np.var(degrees)
        return float(np.clip(1.0 / (1.0 + spread), 0.0, 1.0))

    def _coverage_entropy(self) -> float:
        visits = np.array(list(self.file_visits.values()), dtype=np.float32)
        if visits.size == 0:
            return 0.0
        probs = visits / np.sum(visits)
        entropy = -np.sum(probs * np.log(probs + 1e-9))
        return float(np.clip(entropy / np.log(max(2, len(visits))), 0.0, 1.0))

    def summary(self) -> GraphSummary:
        return GraphSummary(
            visit_ratio=self._visit_ratio(),
            unresolved_dependencies=len(self.unresolved),
            frontier_size=self._frontier_size(),
            evidence_diversity=self._evidence_diversity(),
            locality_score=self._locality_score(),
            coverage_entropy=self._coverage_entropy(),
        )

    def sample_locality_mask(self, seeds: Optional[List[str]] = None) -> Dict[str, float]:
        """Returns per-node locality confidence for action masking."""
        if not self.file_visits:
            return {}
        seeds = seeds or []
        base = np.mean(list(self.file_visits.values()))
        locality: Dict[str, float] = {}
        for node, weight in self.file_visits.items():
            bias = 1.0 if node in seeds else 0.5
            locality[node] = float(np.clip(bias * weight / (base + 1e-6), 0.0, 2.0))
        return locality

    def to_payload(self) -> Dict[str, object]:
        summary = self.summary()
        payload = {
            "files": dict(self.file_visits),
            "edges": {k: dict(v) for k, v in self.symbol_edges.items()},
            "decomposition": {k: list(v) for k, v in self.decomposition_tree.items()},
            "unresolved": list(self.unresolved),
        }
        payload.update(summary.as_dict())
        return payload
