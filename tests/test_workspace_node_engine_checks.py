from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.public_repos.validate_cgcs_workspaces import (
    ValidationSettings,
    _parse_node_engine_requirement,
    validate_workspace,
)


def test_parse_node_engine_requirement_handles_ranges() -> None:
    assert _parse_node_engine_requirement(">=16.0.0 <19") == (16, 0, 0)
    assert _parse_node_engine_requirement("^18.14.0") == (18, 14, 0)
    assert _parse_node_engine_requirement(">=18 || >=20") == (20, 0, 0)
    assert _parse_node_engine_requirement("") is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime not available")
def test_node_engine_mismatch_sets_hard_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "node_repo"
    repo.mkdir()
    package_json = repo / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "name": "repo",
                "engines": {"node": ">=99.0.0"},
                "scripts": {"test": "echo tests"},
            }
        ),
        encoding="utf-8",
    )

    settings = ValidationSettings(
        bootstrap_mode="safe",
        skip_build_if_missing=True,
        skip_install_if_prepared=True,
        timeout_seconds=5.0,
    )
    entry = {
        "repo_key": "example/node",
        "repo_url": "",
        "workspace_id": "example/node@main",
        "pilot_rank": 1,
        "selection_reason": "",
        "language": "node",
        "build_system": "nodejs",
        "package_manager": "npm",
        "local_path": str(repo),
        "install_command": "",
        "build_command": "",
        "test_command": "",
        "bootstrap_commands": [],
        "bootstrap_required": False,
        "required_tools": [],
    }

    monkeypatch.setattr(
        "scripts.public_repos.validate_cgcs_workspaces._run_cmd",
        lambda *args, **kwargs: {"status": "passed", "returncode": 0, "duration": 0.0, "stdout": "", "stderr": ""},
    )
    result = validate_workspace(entry, settings)
    assert result["failure_category"] == "node_engine_mismatch"
    assert result["hard_blocked"] is True
    assert result["hard_block_reason"] == "node_engine_mismatch"
    assert "node" in result.get("engine_requirements", {})
