"""Tests for the pilot benchmark runner helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_load_task_json_missing(tmp_path):
    from scripts.public_repos.run_public_repo_pilot import _load_task_json
    result = _load_task_json(tmp_path / "nonexistent.json")
    assert result is None


def test_load_task_json_valid(tmp_path):
    from scripts.public_repos.run_public_repo_pilot import _load_task_json
    task_file = tmp_path / "task.json"
    _write_json(task_file, {"id": "test_task", "prompt": "fix it"})
    result = _load_task_json(task_file)
    assert result is not None
    assert result["id"] == "test_task"


def test_run_task_with_strategy_missing_repo(tmp_path):
    """Running on a task whose repo_path doesn't exist should return spec or harness error."""
    from scripts.public_repos.run_public_repo_pilot import run_task_with_strategy

    task_json = {
        "id": "t1",
        "problem_statement": "fix bug",
        "repo_path": str(tmp_path / "nonexistent_repo"),
        "language": "python",
        "test_commands": ["pytest -q"],
        "metadata": {
            "contract": [{"id": "C001", "label": "test", "description": "test", "category": "test"}],
        },
    }
    result = run_task_with_strategy(task_json, "contract_first", tmp_path / "runs")
    # Should fail gracefully — either spec_error or harness_error
    assert result["status"] in ("spec_error", "harness_error", "setup_failed", "strategy_error")
    assert result["task_id"] == "t1"
    assert result["strategy"] == "contract_first"


def test_run_task_with_strategy_invalid_task(tmp_path):
    """Task missing repo_path should return spec_error or similar."""
    from scripts.public_repos.run_public_repo_pilot import run_task_with_strategy

    task_json = {"id": "t_missing", "problem_statement": "fix"}  # no repo_path
    result = run_task_with_strategy(task_json, "cgcs", tmp_path / "runs")
    assert result["status"] in ("spec_error", "harness_error")
