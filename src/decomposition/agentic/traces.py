"""Persist per-round traces for decomposition strategies."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from src.config import PathConfig
from src.decomposition.interfaces import DecompositionPlan


def _default_trace_dir() -> Path:
    return PathConfig().reports_root / "decomposition" / "traces"


def _plan_snapshot(plan: DecompositionPlan) -> Dict[str, object]:
    return {
        "strategy": plan.strategy_name,
        "contract": plan.contract,
        "patterns": plan.patterns,
        "subtasks": plan.subtasks,
        "tests": plan.tests,
        "diagnostics": plan.diagnostics,
        "target_files": plan.target_files,
        "candidate_files": plan.candidate_files,
        "subtask_file_map": plan.subtask_file_map,
    }


def write_round_traces(
    *,
    task_id: str,
    strategy_name: str,
    plan: DecompositionPlan,
    rounds: List[Dict[str, object]],
    output_dir: Optional[Path] = None,
) -> Path:
    """Store a structured trace for downstream reporting."""

    target_root = output_dir or _default_trace_dir()
    strategy_dir = target_root / strategy_name
    strategy_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "strategy": strategy_name,
        "plan": _plan_snapshot(plan),
        "rounds": rounds,
    }
    path = strategy_dir / f"{task_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


__all__ = ["write_round_traces"]
