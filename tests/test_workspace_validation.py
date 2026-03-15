"""Regression tests for workspace validation helpers."""
from __future__ import annotations

from pathlib import Path

from scripts.public_repos.validate_cgcs_workspaces import ValidationSettings, build_summary, validate_workspace


def base_entry(tmp_path: Path) -> dict[str, object]:
    workspace = tmp_path / "repo"
    return {
        "repo_key": "github.com/demo/r",
        "repo_url": "https://github.com/demo/r",
        "workspace_id": "github.com/demo/r@abc123",
        "pilot_rank": 1,
        "selection_reason": "test",
        "language": "python",
        "build_system": "pyproject",
        "package_manager": "pip",
        "test_frameworks": ["pytest"],
        "local_path": str(workspace),
        "install_command": "",
        "build_command": "",
        "test_command": "",
        "bootstrap_commands": [],
        "bootstrap_required": False,
        "bootstrap_category": None,
        "bootstrap_reason": None,
        "required_tools": [],
    }


def settings(**overrides: object) -> ValidationSettings:
    data = {
        "bootstrap_mode": "off",
        "skip_build_if_missing": False,
        "skip_install_if_prepared": False,
        "timeout_seconds": 2.0,
    }
    data.update(overrides)
    return ValidationSettings(**data)  # type: ignore[arg-type]


def test_validate_missing_workspace(tmp_path: Path) -> None:
    entry = base_entry(tmp_path)
    result = validate_workspace(entry, settings())
    assert result["final_verdict"] == "blocked_by_environment"
    assert result["failure_category"] == "missing_workspace"


def test_validate_runnable_without_build(tmp_path: Path) -> None:
    entry = base_entry(tmp_path)
    workspace = Path(entry["local_path"])
    workspace.mkdir()
    entry["test_command"] = "true"
    result = validate_workspace(entry, settings(skip_build_if_missing=True))
    assert result["final_verdict"] == "runnable_without_build"
    assert result["is_runnable"] is True


def test_validate_failing_test(tmp_path: Path) -> None:
    entry = base_entry(tmp_path)
    workspace = Path(entry["local_path"])
    workspace.mkdir()
    entry["test_command"] = "false"
    result = validate_workspace(entry, settings(skip_build_if_missing=True))
    assert result["final_verdict"] == "blocked_by_environment"
    assert result["failure_category"] == "test_command_failed"


def test_build_summary() -> None:
    results = [
        {"final_verdict": "runnable"},
        {"final_verdict": "runnable_without_build"},
        {"final_verdict": "blocked_by_environment"},
        {"final_verdict": "blocked_by_environment"},
    ]
    summary = build_summary(results)
    assert summary["total"] == 4
    assert summary["runnable"] == 1
    assert summary["runnable_without_build"] == 1
