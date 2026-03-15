"""Tests for the trace quality auditor."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.public_repos.pilot.trace_quality import (
    _round_flags,
    audit_strategy_logs,
    audit_runs_root,
)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


# ---------------------------------------------------------------------------
# _audit_round
# ---------------------------------------------------------------------------

def test_audit_round_empty():
    flags, missing, status = _round_flags({})
    assert flags["ready_for_strict"] is False
    assert flags["has_contract_items"] is False
    assert "has_contract_items" in missing
    assert status == "unknown"


def test_audit_round_full():
    round_data = {
        "contract_items": [{"id": "C1", "description": "x"}],
        "active_clause_id": "C1",
        "witnesses": [{"test_case": "t", "message": "m"}],
        "raw_edit_payload": "EDIT src/foo.py ...",
        "candidate_files": ["src/foo.py"],
        "regression_guard_ids": ["T1"],
        "status": "applied",
    }
    flags, missing, status = _round_flags(round_data)
    assert flags["has_contract_items"] is True
    assert flags["has_active_clause"] is True
    assert flags["has_witnesses"] is True
    assert flags["has_payload"] is True
    assert flags["ready_for_strict"] is True
    assert missing == []
    assert status == "applied"


def test_audit_round_cgcs_state():
    round_data = {
        "edit_metadata": {
            "cgcs_state": {
                "contract_items": [{"id": "C2"}],
                "active_clause_id": "C2",
                "witness_sample": {"test_case": "t"},
                "regression_guards": ["T2"],
            },
            "raw_edit_payload": "EDIT ...",
        }
    }
    flags, missing, _ = _round_flags(round_data)
    assert flags["has_contract_items"] is True
    assert flags["has_active_clause"] is True
    assert flags["ready_for_strict"] is True
    assert "has_candidate_files" in missing


# ---------------------------------------------------------------------------
# audit_strategy_logs
# ---------------------------------------------------------------------------

def test_audit_strategy_logs_empty(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    result = audit_strategy_logs(logs_dir)
    assert result["rounds_total"] == 0


def test_audit_strategy_logs_with_edits_file(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    edits_data = {
        "rounds": [
            {
                "contract_items": [{"id": "C1"}],
                "active_clause_id": "C1",
                "raw_edit_payload": "EDIT src/a.py ...",
            },
            {
                "contract_items": [],
                "active_clause_id": "",
                "raw_edit_payload": "",
            },
        ]
    }
    _write_json(logs_dir / "edits_round1.json", edits_data)
    result = audit_strategy_logs(logs_dir)
    assert result["rounds_total"] == 2
    assert result["rounds_with_contract_items"] == 1
    assert result["rounds_ready_for_strict"] == 1


# ---------------------------------------------------------------------------
# audit_runs_root
# ---------------------------------------------------------------------------

def test_audit_runs_root_missing(tmp_path):
    per_run, aggregate = audit_runs_root(tmp_path / "nonexistent")
    assert per_run == []
    assert "error" in aggregate


def test_audit_runs_root_with_data(tmp_path):
    runs_root = tmp_path / "runs"
    logs_dir = runs_root / "task_001" / "cgcs" / "logs"
    logs_dir.mkdir(parents=True)
    _write_json(
        logs_dir / "edits_round1.json",
        {
            "rounds": [{
                "contract_items": [{"id": "C1"}],
                "active_clause_id": "C1",
                "raw_edit_payload": "EDIT ...",
            }]
        },
    )
    per_run, aggregate = audit_runs_root(runs_root)
    assert len(per_run) == 1
    assert aggregate["rounds_total"] == 1
    assert aggregate["rounds_with_contract_items"] == 1
    assert aggregate["rounds_ready_for_strict"] == 1
    assert aggregate["tasks_audited"] == 1
