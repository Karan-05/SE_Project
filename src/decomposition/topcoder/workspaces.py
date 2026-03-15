"""Workspace preparation heuristics for Topcoder repositories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(slots=True)
class WorkspaceManifestEntry:
    workspace_id: str
    snapshot_id: str
    repo_url: str
    source_origin: str
    local_path: str
    install_command: Optional[str]
    build_command: Optional[str]
    test_command: Optional[str]
    env_hints: List[str] = field(default_factory=list)
    prep_status: str = "manifest_only"
    prep_error: Optional[str] = None
    runnable_confidence: str = "low"
    notes: str = ""
    synthetic_workspace: bool = False
    original_repo_recovered: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "snapshot_id": self.snapshot_id,
            "repo_url": self.repo_url,
            "source_origin": self.source_origin,
            "local_path": self.local_path,
            "install_command": self.install_command,
            "build_command": self.build_command,
            "test_command": self.test_command,
            "env_hints": self.env_hints,
            "prep_status": self.prep_status,
            "prep_error": self.prep_error,
            "runnable_confidence": self.runnable_confidence,
            "notes": self.notes,
            "synthetic_workspace": self.synthetic_workspace,
            "original_repo_recovered": self.original_repo_recovered,
        }


def _read_package_json(repo_path: Path) -> Dict[str, object]:
    candidate = repo_path / "package.json"
    if not candidate.exists():
        return {}
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def _detect_node_manager(repo_path: Path) -> Tuple[Optional[str], List[str]]:
    env_hints: List[str] = []
    manager = None
    if (repo_path / "pnpm-lock.yaml").exists():
        manager = "pnpm"
    elif (repo_path / "yarn.lock").exists():
        manager = "yarn"
    elif (repo_path / "package-lock.json").exists():
        manager = "npm"
    elif (repo_path / "package.json").exists():
        manager = "npm"
    if manager:
        env_hints.extend(["nodejs", manager])
    return manager, env_hints


def _detect_python_tooling(repo_path: Path) -> Tuple[Optional[str], List[str]]:
    env_hints: List[str] = []
    installer = None
    if (repo_path / "poetry.lock").exists():
        installer = "poetry"
    elif (repo_path / "Pipfile").exists():
        installer = "pipenv"
    elif (repo_path / "requirements.txt").exists():
        installer = "pip"
    elif (repo_path / "setup.py").exists() or (repo_path / "pyproject.toml").exists():
        installer = "pip"
    if installer:
        env_hints.extend(["python", installer])
    return installer, env_hints


def _detect_java_tooling(repo_path: Path) -> Tuple[Optional[str], List[str]]:
    env_hints: List[str] = []
    if (repo_path / "mvnw").exists():
        env_hints.extend(["java", "maven"])
        return "./mvnw", env_hints
    if (repo_path / "gradlew").exists():
        env_hints.extend(["java", "gradle"])
        return "./gradlew", env_hints
    if (repo_path / "pom.xml").exists():
        env_hints.extend(["java", "maven"])
        return "mvn", env_hints
    if (repo_path / "build.gradle").exists() or (repo_path / "build.gradle.kts").exists():
        env_hints.extend(["java", "gradle"])
        return "gradle", env_hints
    return None, env_hints


def infer_workspace_commands(snapshot: Dict[str, object]) -> WorkspaceManifestEntry:
    repo_path = Path(snapshot["local_path"])
    workspace_id = f"{snapshot['snapshot_id']}::workspace"
    source_origin = str(snapshot.get("source_origin") or "unknown")
    synthetic_workspace = bool(snapshot.get("synthetic_workspace", False))
    original_repo_recovered = bool(snapshot.get("original_repo_recovered", not synthetic_workspace))
    install_command = None
    build_command = None
    test_command = None
    env_hints: List[str] = []
    notes: List[str] = []

    node_manager, node_hints = _detect_node_manager(repo_path)
    env_hints.extend(node_hints)
    if node_manager:
        package_data = _read_package_json(repo_path)
        has_build = False
        has_test = False
        if node_manager == "npm":
            install_command = "npm install"
        elif node_manager == "yarn":
            install_command = "yarn install --frozen-lockfile"
        elif node_manager == "pnpm":
            install_command = "pnpm install"
        scripts = package_data.get("scripts") if isinstance(package_data, dict) else None
        if isinstance(scripts, dict):
            if "build" in scripts:
                has_build = True
                build_command = f"{node_manager} run build" if node_manager != "npm" else "npm run build"
            if "test" in scripts:
                has_test = True
                test_command = f"{node_manager} test" if node_manager == "npm" else f"{node_manager} test"
        if not has_build and (repo_path / "tsconfig.json").exists():
            build_command = f"{node_manager} run build"
        if not has_test and (repo_path / "tests").exists():
            test_command = f"{node_manager} run test"
        notes.append(f"node_manager:{node_manager}")

    python_tool, python_hints = _detect_python_tooling(repo_path)
    env_hints.extend([hint for hint in python_hints if hint not in env_hints])
    if python_tool:
        if python_tool == "poetry":
            install_command = install_command or "poetry install"
            test_command = test_command or "poetry run pytest"
        elif python_tool == "pipenv":
            install_command = install_command or "pipenv install"
            test_command = test_command or "pipenv run pytest"
        else:
            requirements = repo_path / "requirements.txt"
            if requirements.exists():
                install_command = install_command or "pip install -r requirements.txt"
            elif (repo_path / "setup.py").exists():
                install_command = install_command or "pip install -e ."
            test_command = test_command or "pytest"
        notes.append(f"python_tool:{python_tool}")

    java_tool, java_hints = _detect_java_tooling(repo_path)
    env_hints.extend([hint for hint in java_hints if hint not in env_hints])
    if java_tool:
        install_command = install_command or f"{java_tool} -q install -DskipTests"
        build_command = build_command or f"{java_tool} -q package"
        test_command = test_command or f"{java_tool} -q test"
        notes.append(f"java_tool:{java_tool}")

    if not install_command and (repo_path / "Makefile").exists():
        install_command = "make install"
        build_command = build_command or "make build"
        test_command = test_command or "make test"
        notes.append("makefile_detected")

    confidence = "low"
    filled = sum(1 for cmd in (install_command, build_command, test_command) if cmd)
    if filled == 3:
        confidence = "high"
    elif filled >= 1:
        confidence = "medium"

    return WorkspaceManifestEntry(
        workspace_id=workspace_id,
        snapshot_id=str(snapshot["snapshot_id"]),
        repo_url=str(snapshot["repo_url"]),
        source_origin=source_origin,
        local_path=str(snapshot["local_path"]),
        install_command=install_command,
        build_command=build_command,
        test_command=test_command,
        env_hints=env_hints,
        prep_status="manifest_only",
        prep_error=None,
        runnable_confidence=confidence,
        notes=";".join(notes),
        synthetic_workspace=synthetic_workspace,
        original_repo_recovered=original_repo_recovered,
    )
