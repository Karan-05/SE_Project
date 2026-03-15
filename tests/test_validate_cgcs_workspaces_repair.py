from __future__ import annotations

from pathlib import Path

import pytest

from scripts.public_repos.validate_cgcs_workspaces import ValidationSettings, validate_workspace


def base_entry(tmp_path: Path) -> dict[str, object]:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    return {
        "repo_key": "github.com/demo/repo",
        "repo_url": "https://github.com/demo/repo",
        "workspace_id": "github.com/demo/repo@deadbee",
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
    base = {
        "bootstrap_mode": "off",
        "skip_build_if_missing": False,
        "skip_install_if_prepared": False,
        "timeout_seconds": 2.0,
    }
    base.update(overrides)
    return ValidationSettings(**base)  # type: ignore[arg-type]


def test_bootstrap_required_without_safe_mode(tmp_path: Path) -> None:
    entry = base_entry(tmp_path)
    entry.update({
        "install_command": "true",
        "build_command": "python -m build",
        "test_command": "true",
        "bootstrap_required": True,
        "bootstrap_category": "missing_python_build_module",
        "bootstrap_reason": "python build module missing",
        "bootstrap_commands": ["python -m pip install build"],
    })
    result = validate_workspace(entry, settings(bootstrap_mode="off"))
    assert result["final_verdict"] == "blocked_by_environment"
    assert result["failure_category"] == "missing_python_build_module"
    assert result["bootstrap_applied"] is False


def test_repo_without_build_can_pass_when_skipped(tmp_path: Path) -> None:
    entry = base_entry(tmp_path)
    entry.update({
        "language": "node",
        "build_system": "nodejs",
        "package_manager": "npm",
        "install_command": "",
        "build_command": "",
        "test_command": "true",
    })
    result = validate_workspace(entry, settings(skip_build_if_missing=True))
    assert result["final_verdict"] == "runnable_without_build"
    assert result["failure_category"] == ""


def test_missing_node_package_manager_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    entry = base_entry(tmp_path)
    entry.update({
        "language": "node",
        "build_system": "nodejs",
        "package_manager": "pnpm",
        "test_command": "true",
        "required_tools": ["pnpm"],
    })

    def fake_which(tool: str) -> None:
        return None

    monkeypatch.setattr("scripts.public_repos.validate_cgcs_workspaces.shutil.which", fake_which)
    result = validate_workspace(entry, settings(skip_build_if_missing=True))
    assert result["final_verdict"] == "blocked_by_environment"
    assert result["failure_category"] == "missing_node_package_manager"
