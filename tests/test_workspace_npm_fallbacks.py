from __future__ import annotations

from typing import Any, Dict, List

import pytest

from scripts.public_repos.validate_cgcs_workspaces import _attempt_npm_fallback


def test_npm_peer_dependency_fallback_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: List[str] = []

    def _fake_run_cmd(cmd: str, cwd, timeout) -> Dict[str, Any]:
        executed.append(cmd)
        return {"status": "passed", "returncode": 0, "duration": 0.0, "stdout": "", "stderr": ""}

    monkeypatch.setattr("scripts.public_repos.validate_cgcs_workspaces._run_cmd", _fake_run_cmd)
    rescue_actions: List[str] = []
    result = _attempt_npm_fallback(
        "npm install",
        cwd=None,  # unused in fake runner
        timeout=5.0,
        stderr="ERESOLVE could not resolve peer dep",
        rescue_actions=rescue_actions,
    )
    assert result is not None
    assert executed == ["npm install --legacy-peer-deps"]
    assert result["fallback_command"].endswith("--legacy-peer-deps")
    assert result["fallback_helped"] is True
    assert rescue_actions == ["npm_legacy_peer_deps"]


def test_npm_integrity_fallback_runs_cache_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: List[str] = []

    def _fake_run_cmd(cmd: str, cwd, timeout) -> Dict[str, Any]:
        executed.append(cmd)
        status = "passed" if "cache" in cmd else "failed"
        return {"status": status, "returncode": 1 if status != "passed" else 0, "duration": 0.0, "stdout": "", "stderr": ""}

    monkeypatch.setattr("scripts.public_repos.validate_cgcs_workspaces._run_cmd", _fake_run_cmd)
    rescue_actions: List[str] = []
    result = _attempt_npm_fallback(
        "npm install",
        cwd=None,
        timeout=5.0,
        stderr="npm ERR! code EINTEGRITY",
        rescue_actions=rescue_actions,
    )
    assert result is not None
    assert executed == ["npm cache clean --force", "npm install"]
    assert result["fallback_reason"] == "integrity"
    assert result["fallback_helped"] is False
    assert rescue_actions == ["npm_cache_clean", "npm_install_retry"]
