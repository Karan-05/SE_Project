"""Utility helpers for persisting unit test executions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ..solvers.base import sanitize_task_id


def persist_test_results(task_id: str, tests_run: List[Dict[str, Any]], target_dir: Path) -> Path:
    """Write raw test traces so reporting has per-task artifacts."""

    target_dir.mkdir(parents=True, exist_ok=True)
    safe = sanitize_task_id(task_id)
    path = target_dir / f"{safe}.json"
    payload = {"task_id": task_id, "tests": tests_run or []}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

