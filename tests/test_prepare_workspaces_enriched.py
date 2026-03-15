from __future__ import annotations

import json
from pathlib import Path

from src.public_repos.workspaces import build_workspaces


def python_snapshot(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "py"
    repo.mkdir()
    return {
        "repo_key": "github.com/demo/py",
        "repo_url": "https://github.com/demo/py",
        "local_path": str(repo),
        "languages": ["python"],
        "language_hint": "python",
        "detected_build_files": ["pyproject.toml", "requirements.txt"],
        "detected_test_paths": ["tests/test_core.py"],
        "build_systems": ["python-pyproject"],
        "test_frameworks": ["pytest"],
        "has_tests": True,
        "has_build_files": True,
    }


def node_snapshot(tmp_path: Path, scripts: dict[str, str]) -> dict[str, object]:
    repo = tmp_path / "node"
    repo.mkdir()
    package_json = repo / "package.json"
    package_json.write_text(json.dumps({"name": "demo-node", "version": "0.1.0", "scripts": scripts}), encoding="utf-8")
    return {
        "repo_key": "github.com/demo/node",
        "repo_url": "https://github.com/demo/node",
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


def test_manifest_includes_bootstrap_fields(tmp_path: Path) -> None:
    workspace = build_workspaces([python_snapshot(tmp_path)])[0]
    payload = workspace.as_dict()
    assert payload["package_manager"] == "pip"
    assert payload["bootstrap_commands"] is not None
    assert "command_inference_source" in payload and payload["command_inference_source"]
    assert payload["install_command"] == "pip install -r requirements.txt"
    assert payload["test_command"] == "pytest"


def test_build_command_optional_for_node(tmp_path: Path) -> None:
    workspace = build_workspaces([node_snapshot(tmp_path, {"test": "npm run test:unit"})])[0]
    assert workspace.build_command is None
    assert workspace.test_command == "npm test"
    manifest = workspace.as_dict()
    assert manifest["command_inference_source"].startswith("package.json")
