from __future__ import annotations

from pathlib import Path

from src.decomposition.topcoder.workspaces import infer_workspace_commands


def test_workspace_infers_node_commands(tmp_path: Path) -> None:
    repo_path = tmp_path / "node_repo"
    repo_path.mkdir()
    (repo_path / "package.json").write_text(
        '{"scripts": {"build": "webpack --mode production", "test": "jest"}}',
        encoding="utf-8",
    )
    (repo_path / "yarn.lock").write_text("lock", encoding="utf-8")
    snapshot = {
        "snapshot_id": "snap-node",
        "repo_url": "https://github.com/topcoder/node_repo",
        "local_path": str(repo_path),
    }
    manifest = infer_workspace_commands(snapshot)
    assert manifest.install_command == "yarn install --frozen-lockfile"
    assert manifest.build_command == "yarn run build"
    assert manifest.test_command == "yarn test"
    assert manifest.runnable_confidence == "high"


def test_workspace_infers_python_commands(tmp_path: Path) -> None:
    repo_path = tmp_path / "python_repo"
    repo_path.mkdir()
    (repo_path / "requirements.txt").write_text("pytest\nflask", encoding="utf-8")
    snapshot = {
        "snapshot_id": "snap-python",
        "repo_url": "https://github.com/topcoder/python_repo",
        "local_path": str(repo_path),
    }
    manifest = infer_workspace_commands(snapshot)
    assert manifest.install_command == "pip install -r requirements.txt"
    assert manifest.test_command == "pytest"
    assert manifest.runnable_confidence == "medium"
