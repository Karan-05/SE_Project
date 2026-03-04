"""Data models for representing agentic plans and evaluation artefacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class TaskNode:
    """Single node in a task graph."""

    node_id: str
    label: str
    tools: Tuple[str, ...] = field(default_factory=tuple)
    parallel_group: Optional[str] = None


@dataclass(frozen=True)
class TaskEdge:
    """Directed dependency between two task nodes."""

    source: str
    target: str


@dataclass
class AgenticPlan:
    """Full task graph with metadata for execution planning."""

    challenge_id: str
    scenario_type: str
    granularity: str
    nodes: Dict[str, TaskNode]
    edges: List[TaskEdge]
    notes: List[str] = field(default_factory=list)

    def node_labels(self) -> Dict[str, str]:
        return {node_id: node.label for node_id, node in self.nodes.items()}

    def tool_index(self) -> Dict[str, Set[str]]:
        return {node_id: set(node.tools) for node_id, node in self.nodes.items()}

    def adjacency(self) -> Dict[str, Set[str]]:
        graph: Dict[str, Set[str]] = {node_id: set() for node_id in self.nodes}
        for edge in self.edges:
            if edge.source in graph:
                graph[edge.source].add(edge.target)
        return graph

    def in_degree(self) -> Dict[str, int]:
        indeg: Dict[str, int] = {node_id: 0 for node_id in self.nodes}
        for edge in self.edges:
            if edge.target in indeg:
                indeg[edge.target] += 1
        return indeg

    def parallel_groups(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for node_id, node in self.nodes.items():
            if node.parallel_group:
                groups.setdefault(node.parallel_group, []).append(node_id)
        return groups

    def complexity_score(self) -> int:
        return len(self.nodes) + len(self.edges)


@dataclass
class PlanEvaluation:
    """Metric summary comparing a generated plan against a baseline."""

    challenge_id: str
    baseline_id: str
    node_precision: float
    node_recall: float
    node_f1: float
    edge_precision: float
    edge_recall: float
    edge_f1: float
    tool_precision: float
    tool_recall: float
    tool_f1: float
    node_label_similarity: float
    structural_similarity_index: float
    path_length_similarity: float
    complexity_score: int
    scenario_type: str
    granularity: str
    notes: Sequence[str] = field(default_factory=tuple)


def normalize_label(label: str) -> str:
    return " ".join(label.lower().strip().split())


def normalize_tool(tool: str) -> str:
    return tool.lower().strip()


def to_edge_set(edges: Iterable[TaskEdge]) -> Set[Tuple[str, str]]:
    return {(edge.source, edge.target) for edge in edges}
