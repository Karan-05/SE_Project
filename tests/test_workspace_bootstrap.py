from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.public_repos.pilot.workspace_bootstrap import plan_workspace_normalization


def python_snapshot(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "python"
    repo.mkdir()
    return {
        "repo_key": "github.com/example/python",
        "repo_url": "https://github.com/example/python",
        "local_path": str(repo),
        "languages": ["python"],
        "language_hint": "python",
        "detected_build_files": ["pyproject.toml"],
        "detected_test_paths": ["tests/test_app.py"],
        "build_systems": ["python-pyproject"],
        "test_frameworks": ["pytest"],
        "has_tests": True,
        "has_build_files": True,
    }


def test_python_bootstrap_detects_missing_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = python_snapshot(tmp_path)

    def fake_find_spec(name: str):
        if name == "build":
            return None
        return object()

    monkeypatch.setattr("src.public_repos.pilot.workspace_bootstrap.importlib.util.find_spec", fake_find_spec)
    plan = plan_workspace_normalization(snapshot)
    assert plan.language == "python"
    assert plan.build_command == "python -m build"
    assert plan.install_command == "pip install -e ."
    assert plan.test_command == "pytest"
    assert plan.bootstrap.required is True
    assert plan.bootstrap.category == "missing_python_build_module"
    assert any(cmd.endswith("build") for cmd in plan.bootstrap.commands)


def node_snapshot(tmp_path: Path, scripts: dict[str, str]) -> dict[str, object]:
    repo = tmp_path / "node"
    repo.mkdir()
    package_json = repo / "package.json"
    package_json.write_text(json.dumps({"name": "demo", "version": "0.1.0", "scripts": scripts}), encoding="utf-8")
    return {
        "repo_key": "github.com/example/node",
        "repo_url": "https://github.com/example/node",
        "local_path": str(repo),
        "languages": ["javascript"],
        "language_hint": "javascript",
        "detected_build_files": ["package.json"],
        "detected_test_paths": [],
        "build_systems": ["nodejs"],
        "test_frameworks": [],
        "has_tests": True,
        "has_build_files": True,
    }


def test_node_plan_missing_build_script(tmp_path: Path) -> None:
    snapshot = node_snapshot(tmp_path, {"test": "npm test"})
    plan = plan_workspace_normalization(snapshot)
    assert plan.build_command is None
    assert plan.test_command == "npm test"
    assert plan.unsupported_reason is None


def test_node_plan_missing_test_script(tmp_path: Path) -> None:
    snapshot = node_snapshot(tmp_path, {"build": "webpack --mode production"})
    plan = plan_workspace_normalization(snapshot)
    assert plan.build_command == "npm run build"
    assert plan.test_command is None
