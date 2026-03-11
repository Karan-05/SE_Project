"""Workspace preparation helpers for repo-backed benchmarks."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .task import RepoTaskSpec


def _clean_commands(commands: List[str]) -> List[str]:
    cleaned: List[str] = []
    for cmd in commands:
        cmd_str = str(cmd).strip()
        if cmd_str:
            cleaned.append(cmd_str)
    return cleaned


@dataclass
class SetupPlan:
    """Resolved setup strategy for a repo workspace."""

    commands: List[str]
    strategy: str
    derived: bool
    package_manager: str
    runtime_family: str
    notes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "commands": self.commands,
            "strategy": self.strategy,
            "derived": self.derived,
            "package_manager": self.package_manager,
            "runtime_family": self.runtime_family,
            "notes": self.notes,
        }


def _infer_node_commands(repo_root: Path) -> tuple[List[str], str, Dict[str, str]]:
    lockfile = repo_root / "package-lock.json"
    pkg_json = repo_root / "package.json"
    if lockfile.exists():
        return ["npm ci --no-audit --no-fund"], "npm_ci_lockfile", {"lockfile": str(lockfile)}
    if pkg_json.exists():
        return ["npm install --no-audit --no-fund"], "npm_install_package_json", {"package_json": str(pkg_json)}
    return [], "npm_missing_package_json", {}


def resolve_setup_plan(task: RepoTaskSpec, repo_root: Path) -> SetupPlan:
    """Derive the setup commands that should run prior to benchmark attempts."""

    repo_root = repo_root.resolve()
    runtime = (task.runtime_family or "").lower()
    package_manager = (task.package_manager or "").lower()
    commands = _clean_commands(list(task.setup_commands or []))
    derived = False
    strategy = "task_defined" if commands else "none"
    notes: Dict[str, str] = {}

    if not commands:
        derived = True
        if package_manager == "npm" or runtime == "node":
            commands, strategy, notes = _infer_node_commands(repo_root)

    return SetupPlan(
        commands=commands,
        strategy=strategy,
        derived=derived,
        package_manager=package_manager,
        runtime_family=runtime,
        notes=notes,
    )


__all__ = ["SetupPlan", "resolve_setup_plan"]
