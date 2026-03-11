"""Shared dataclasses/enums for real evaluation logging."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class FinalStatus(str, Enum):
    PASS_ALL_TESTS = "PASS_ALL_TESTS"
    BUILD_PASS_TESTS_PARTIAL = "BUILD_PASS_TESTS_PARTIAL"
    BUILD_FAIL = "BUILD_FAIL"
    TEST_FAIL = "TEST_FAIL"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    UNSUPPORTED_TASK = "UNSUPPORTED_TASK"
    TIMEOUT = "TIMEOUT"
    NO_ASSETS = "NO_ASSETS"
    EXECUTION_ERROR = "EXECUTION_ERROR"


@dataclass
class ExecutionSummary:
    """Outcome of the build/test phase."""

    status: FinalStatus
    build_seconds: float = 0.0
    test_seconds: float = 0.0
    build_log: List[str] = field(default_factory=list)
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class DecompositionSummary:
    """High-level decomposition statistics captured from the strategy plan."""

    strategy: str
    num_subtasks: int
    num_tests: int
    plan_contract: Any
    notes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RealTaskResult:
    """Full record per (task, model, strategy) evaluation."""

    task_id: str
    task_title: str
    task_category: str
    dataset_id: str
    source_path: str
    run_id: str
    model_name: str
    strategy_name: str
    final_status: FinalStatus
    execution: ExecutionSummary
    decomposition: Optional[DecompositionSummary] = None
    strategy_metrics: Dict[str, Any] = field(default_factory=dict)
    tokens_used: Optional[float] = None
    elapsed_seconds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "task_category": self.task_category,
            "dataset_id": self.dataset_id,
            "source_path": self.source_path,
            "run_id": self.run_id,
            "model_name": self.model_name,
            "strategy_name": self.strategy_name,
            "final_status": self.final_status.value,
            "execution": self.execution.to_dict(),
            "strategy_metrics": self.strategy_metrics,
            "tokens_used": self.tokens_used,
            "elapsed_seconds": self.elapsed_seconds,
        }
        if self.decomposition is not None:
            payload["decomposition"] = self.decomposition.to_dict()
        return payload
