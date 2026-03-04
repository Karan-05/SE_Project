"""Shared base classes for universal Topcoder solvers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..task_router import RoutingDecision, TaskType

if True:  # pragma: no cover - type checking guard
    try:
        from typing import Protocol
    except ImportError:  # pragma: no cover - Python <3.8 guard
        Protocol = object  # type: ignore

try:  # typing helpers to avoid circular imports
    from typing import TYPE_CHECKING
except ImportError:  # pragma: no cover
    TYPE_CHECKING = False

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..experiment_runner import ExperimentConfig
    from ..test_manager import TestManager
    from src.decomposition.self_verify import RetryConfig
else:  # pragma: no cover - runtime fallback
    ExperimentConfig = object  # type: ignore
    TestManager = object  # type: ignore
    RetryConfig = object  # type: ignore


def sanitize_task_id(task_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(task_id))
    return safe[:120] or "task"


def resolve_run_id(ctx: "SolverContext") -> str:
    """Best-effort run identifier for logging/repair prompts."""

    return str(getattr(ctx.retry_config, "run_id", None) or getattr(ctx.config, "run_id", None) or "topcoder_run")


@dataclass
class SolverContext:
    """Runtime wiring passed to each solver."""

    task: Dict[str, Any]
    decision: RoutingDecision
    config: ExperimentConfig  # type: ignore[assignment]
    retry_config: RetryConfig  # type: ignore[assignment]
    test_manager: Optional[TestManager]
    run_dir: Path
    artifact_dir: Path
    deliverables_dir: Path
    patches_dir: Path
    rubric_dir: Path
    test_results_dir: Path
    repo_logs_dir: Path
    repo_search_root: Path
    llm_available: bool = True

    @property
    def task_id(self) -> str:
        return str(self.task.get("id") or "task")


@dataclass
class SolverResult:
    """Normalized response describing how a solver handled a task."""

    status: str
    error_type: str
    verifier_type: str
    verifier_name: str = ""
    verifier_score: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)
    tests_run: Optional[List[Dict[str, Any]]] = None
    llm_calls_used: float = 0.0
    deliverable_success: bool = False
    unit_test_success: bool = False
    failure_signature: str = ""
    failing_tests: str = ""
    notes: str = ""


class BaseSolver(Protocol):  # pragma: no cover - interface container
    name: str
    supported_types: tuple[TaskType, ...]

    def solve(self, ctx: SolverContext) -> SolverResult:
        ...
