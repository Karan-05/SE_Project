"""Shared interfaces and dataclasses for task decomposition strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


@dataclass
class DecompositionContext:
    """Problem context passed into every strategy."""

    task_id: str
    problem_statement: str
    tags: List[str] = field(default_factory=list)
    difficulty: Optional[str] = None
    constraints: Optional[str] = None
    examples: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    nearest_neighbors: List[Dict[str, str]] = field(default_factory=list)
    embeddings: Optional[List[float]] = None
    historical_stats: Optional[Dict[str, float]] = None


@dataclass
class DecompositionPlan:
    """Structured plan produced by every strategy."""

    strategy_name: str
    contract: Dict[str, str] = field(default_factory=dict)
    patterns: List[str] = field(default_factory=list)
    subtasks: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    simulation_traces: List[str] = field(default_factory=list)
    role_messages: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    candidate_files: List[str] = field(default_factory=list)
    subtask_file_map: Dict[str, List[str]] = field(default_factory=dict)
    repair_target_files: Dict[str, List[str]] = field(default_factory=dict)
    diagnostics: Dict[str, str] = field(default_factory=dict)


@dataclass
class StrategyResult:
    """Full result bundle from executing a strategy."""

    plan: DecompositionPlan
    solution_code: str
    tests_run: List[Dict[str, str]] = field(default_factory=list)
    metrics: Dict[str, float | str] = field(default_factory=dict)
    round_traces: List[Dict[str, object]] = field(default_factory=list)


class TaskDecompositionStrategy(Protocol):
    """Protocol that all strategies must implement."""

    name: str

    def decompose(self, ctx: DecompositionContext) -> DecompositionPlan:
        ...

    def solve(self, ctx: DecompositionContext, plan: DecompositionPlan) -> StrategyResult:
        ...
