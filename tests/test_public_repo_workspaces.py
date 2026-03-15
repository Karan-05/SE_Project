from __future__ import annotations

from pathlib import Path
import json

from src.public_repos.workspaces import build_workspaces, write_cgcs_seed_pool


def python_snapshot(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "python"
    repo.mkdir()
    return {
        "repo_key": "github.com/example/python",
        "repo_url": "https://github.com/example/python",
        "local_path": str(repo),
        "languages": ["python"],
        "language_hint": "python",
        "detected_build_files": ["pyproject.toml", "requirements.txt"],
        "detected_test_paths": ["tests/test_app.py"],
        "build_systems": ["python-pyproject"],
        "test_frameworks": ["pytest"],
        "has_tests": True,
        "has_build_files": True,
    }


def js_snapshot(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "js"
    repo.mkdir()
    package_json = repo / "package.json"
    package_json.write_text(
        json.dumps({"name": "demo", "version": "0.1.0", "scripts": {"build": "webpack", "test": "yarn test"}}),
        encoding="utf-8",
    )
    return {
        "repo_key": "github.com/example/js",
        "repo_url": "https://github.com/example/js",
        "local_path": str(repo),
        "languages": ["javascript"],
        "language_hint": "javascript",
        "detected_build_files": ["package.json", "yarn.lock"],
        "detected_test_paths": ["__tests__/app.test.js"],
        "build_systems": ["npm"],
        "test_frameworks": ["jest"],
        "has_tests": True,
        "has_build_files": True,
    }


def test_workspace_generation_sets_commands(tmp_path: Path) -> None:
    workspaces = build_workspaces([python_snapshot(tmp_path), js_snapshot(tmp_path)])
    python_ws = next(ws for ws in workspaces if ws.repo_key.endswith("python"))
    js_ws = next(ws for ws in workspaces if ws.repo_key.endswith("js"))
    assert python_ws.install_command == "pip install -r requirements.txt"
    assert python_ws.test_command == "pytest"
    assert python_ws.runnable_confidence > 0.5
    assert js_ws.install_command == "yarn install"
    assert js_ws.build_command == "yarn build"
    assert js_ws.test_command == "yarn test"


def test_cgcs_seed_pool_filters_by_confidence(tmp_path: Path) -> None:
    workspaces = build_workspaces([python_snapshot(tmp_path)])
    output = tmp_path / "cgcs.jsonl"
    write_cgcs_seed_pool(workspaces, output, confidence_threshold=0.5)
    lines = output.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
