from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import scripts.public_repos.run_complete_public_repo_pilot as orchestrator
from src.public_repos.pilot.rescue import PilotRescueResult


def fake_rescue(out_dir: Path, **kwargs):
    record = {
        "repo_key": "github.com/demo/a",
        "pilot_rank": 1,
        "final_verdict": "runnable",
        "is_runnable": True,
        "failure_category": "",
    }
    validation_path = out_dir / "workspace_validation.jsonl"
    validation_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    summary = {"total": 1, "runnable": 1, "runnable_without_build": 0}
    (out_dir / "workspace_validation_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return PilotRescueResult(
        validation_results=[record],
        validation_summary=summary,
        attempt_log=[],
        expansion_log=[],
        rescue_summary={"final_validated": 1, "initial_validated": 0, "hard_blocked": 0, "rescue_counts": {}},
        expansion_summary={"replacements_added": 0, "current_subset_size": 1, "attempted_repos": 1},
        current_subset=[record],
        hard_blocked_repos=[],
    )


def fake_generate_tasks(validated_path: Path, out_dir: Path, **kwargs):
    manifest = {"task_id": "public_pilot_demo_000", "task_json_path": str(out_dir / "task.json")}
    (out_dir / "tasks_manifest.jsonl").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return {"tasks_generated": 1}


def fake_run_pilot_benchmark(**kwargs):
    return {"total_runs": 1}


def fake_run_strict_dataset(**kwargs):
    return {"usable_rows": 1, "rejection_reasons": {}}


def fake_build_eval_pack(*args, **kwargs):
    return {"total_eval_items": 1}


def test_run_complete_public_repo_pilot_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(orchestrator, "run_rescue_and_expand", fake_rescue)
    monkeypatch.setattr(orchestrator, "generate_tasks", fake_generate_tasks)
    monkeypatch.setattr(orchestrator, "run_pilot_benchmark", fake_run_pilot_benchmark)
    monkeypatch.setattr(orchestrator, "run_strict_dataset", fake_run_strict_dataset)
    monkeypatch.setattr(orchestrator, "build_eval_pack", fake_build_eval_pack)

    seed_pool = tmp_path / "pool.jsonl"
    seed_pool.write_text(json.dumps({"repo_key": "github.com/demo/a"}) + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"repo_key": "github.com/demo/a", "local_path": str(tmp_path)}) + "\n", encoding="utf-8")
    subset = tmp_path / "subset.jsonl"
    subset.write_text(json.dumps({"repo_key": "github.com/demo/a"}) + "\n", encoding="utf-8")

    args = [
        "run_complete_public_repo_pilot",
        "--seed-pool",
        str(seed_pool),
        "--workspace-manifest",
        str(manifest),
        "--initial-subset",
        str(subset),
        "--pilot-dir",
        str(tmp_path / "pilot"),
        "--report-dir",
        str(tmp_path / "reports"),
        "--ase-report",
        str(tmp_path / "report.md"),
        "--strict-output-dir",
        str(tmp_path / "strict"),
    ]
    monkeypatch.setattr(sys, "argv", args)
    orchestrator.main()
    summary_path = tmp_path / "pilot" / "complete_pilot_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["validated_repos"] == 1


def test_run_complete_public_repo_pilot_blocks_on_zero_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(orchestrator, "run_rescue_and_expand", fake_rescue)
    monkeypatch.setattr(orchestrator, "generate_tasks", fake_generate_tasks)
    monkeypatch.setattr(orchestrator, "run_pilot_benchmark", fake_run_pilot_benchmark)

    def zero_rows(**kwargs):
        return {"usable_rows": 0, "rejection_reasons": {"missing_active_clause_id": 2}}

    monkeypatch.setattr(orchestrator, "run_strict_dataset", zero_rows)
    monkeypatch.setattr(orchestrator, "build_eval_pack", fake_build_eval_pack)

    seed_pool = tmp_path / "pool.jsonl"
    seed_pool.write_text(json.dumps({"repo_key": "github.com/demo/a"}) + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"repo_key": "github.com/demo/a", "local_path": str(tmp_path)}) + "\n", encoding="utf-8")
    subset = tmp_path / "subset.jsonl"
    subset.write_text(json.dumps({"repo_key": "github.com/demo/a"}) + "\n", encoding="utf-8")

    args = [
        "run_complete_public_repo_pilot",
        "--seed-pool",
        str(seed_pool),
        "--workspace-manifest",
        str(manifest),
        "--initial-subset",
        str(subset),
        "--pilot-dir",
        str(tmp_path / "pilot"),
        "--report-dir",
        str(tmp_path / "reports"),
        "--strict-output-dir",
        str(tmp_path / "strict"),
    ]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        orchestrator.main()
    blocker = tmp_path / "reports" / "strict_dataset_blocker.md"
    assert blocker.exists()
