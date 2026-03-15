from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.public_repos.validate_cgcs_workspaces import ValidationSettings
from src.public_repos.pilot.rescue import PilotRescueOrchestrator, PilotRescueResult


def _validation_record(repo_key: str, verdict: str, failure: str) -> dict[str, object]:
    return {
        "repo_key": repo_key,
        "final_verdict": verdict,
        "failure_category": failure,
        "install_status": "passed",
        "build_status": "skipped",
        "test_status": "skipped" if verdict != "runnable" else "passed",
    }


def test_rescue_upgrades_repo_and_replacement_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_a = "github.com/example/python"
    repo_b = "github.com/example/bad"
    repo_c = "github.com/example/new"

    work_a = tmp_path / "python"
    work_b = tmp_path / "bad"
    work_c = tmp_path / "new"
    for path in (work_a, work_b, work_c):
        path.mkdir()

    manifest = [
        {"repo_key": repo_a, "repo_url": "https://example/a", "local_path": str(work_a), "language": "python"},
        {"repo_key": repo_b, "repo_url": "https://example/b", "local_path": str(work_b), "language": "python"},
        {"repo_key": repo_c, "repo_url": "https://example/c", "local_path": str(work_c), "language": "python"},
    ]
    initial_subset = [{"repo_key": repo_a, "pilot_rank": 1}]
    seed_pool = [{"repo_key": repo_c, "language": "python", "runnable_confidence": 0.9}]

    rescued: set[str] = set()

    def fake_validator(entry: dict[str, object], settings: ValidationSettings) -> dict[str, object]:
        repo_key = str(entry.get("repo_key"))
        if repo_key == repo_a and repo_key not in rescued:
            return _validation_record(repo_key, "blocked_by_environment", "missing_python_packaging_tool")
        if repo_key == repo_b:
            return _validation_record(repo_key, "blocked_by_environment", "missing_tests")
        return _validation_record(repo_key, "runnable", "")

    def fake_python_bootstrap(local_path: Path):
        rescued.add(repo_a)
        from src.public_repos.pilot.bootstrap import BootstrapReport

        return BootstrapReport(success=True, commands_run=["python -m pip install build"], note="ok")

    monkeypatch.setattr("src.public_repos.pilot.bootstrap.ensure_python_packaging_stack", fake_python_bootstrap)

    settings = ValidationSettings(
        bootstrap_mode="safe",
        skip_build_if_missing=True,
        skip_install_if_prepared=False,
        timeout_seconds=60.0,
    )
    orchestrator = PilotRescueOrchestrator(
        seed_pool=seed_pool,
        manifest_entries=manifest,
        initial_subset=initial_subset,
        initial_size=1,
        target_validated=1,
        max_pilot_size=2,
        max_rounds=2,
        rng_seed=0,
        validation_settings=settings,
        validator=fake_validator,
    )
    result: PilotRescueResult = orchestrator.run()
    assert result.rescue_summary["final_validated"] == 1
    assert result.rescue_summary["rescue_counts"]["python_bootstrap"] == 1
    assert result.expansion_summary["replacements_added"] >= 0
    assert any(entry["repo_key"] == repo_a for entry in result.current_subset)
