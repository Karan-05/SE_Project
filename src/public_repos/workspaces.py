"""Prepare workspace manifests and CGCS-ready subsets from repo snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .pilot.workspace_bootstrap import plan_workspace_normalization
from .utils import now_utc_iso, write_jsonl


@dataclass(slots=True)
class WorkspaceSpec:
    workspace_id: str
    repo_key: str
    repo_url: str
    local_path: Path
    language: str | None
    package_manager: str | None
    package_manager_spec: str | None
    build_system: str | None
    install_command: str | None
    build_command: str | None
    test_command: str | None
    build_systems: list[str]
    test_frameworks: list[str]
    detected_build_files: list[str]
    detected_test_paths: list[str]
    runnable_confidence: float
    notes: str
    bootstrap_commands: list[str]
    bootstrap_required: bool
    bootstrap_reason: str | None
    bootstrap_category: str | None
    unsupported_reason: str | None
    command_inference_source: str
    metadata: dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=now_utc_iso)

    def as_dict(self) -> dict[str, object]:
        payload = {
            "workspace_id": self.workspace_id,
            "repo_key": self.repo_key,
            "repo_url": self.repo_url,
            "local_path": str(self.local_path),
            "language": self.language,
            "package_manager": self.package_manager,
            "package_manager_spec": self.package_manager_spec,
            "build_system": self.build_system,
            "install_command": self.install_command,
            "build_command": self.build_command,
            "test_command": self.test_command,
            "build_systems": self.build_systems,
            "test_frameworks": self.test_frameworks,
            "detected_build_files": self.detected_build_files,
            "detected_test_paths": self.detected_test_paths,
            "runnable_confidence": round(self.runnable_confidence, 3),
            "notes": self.notes,
            "bootstrap_commands": self.bootstrap_commands,
            "bootstrap_required": self.bootstrap_required,
            "bootstrap_reason": self.bootstrap_reason,
            "bootstrap_category": self.bootstrap_category,
            "unsupported_reason": self.unsupported_reason,
            "command_inference_source": self.command_inference_source,
            "timestamp": self.timestamp,
        }
        payload.update(self.metadata)
        return payload


def load_snapshots(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def build_workspace(snapshot: dict[str, object]) -> WorkspaceSpec:
    repo_key = snapshot["repo_key"]
    repo_url = snapshot.get("repo_url", "")
    local_path = Path(snapshot.get("local_path") or "")
    plan = plan_workspace_normalization(snapshot)
    resolved_commit = snapshot.get("resolved_commit")
    workspace_id = f"{repo_key}@{str(resolved_commit)[:7]}" if resolved_commit else repo_key
    metadata = {
        "selection_rank": snapshot.get("selection_rank"),
        "candidate_entry_files": snapshot.get("detected_build_files", []),
        "top_level_files": snapshot.get("top_level_files", []),
        "has_tests": snapshot.get("has_tests"),
        "has_build_files": snapshot.get("has_build_files"),
        "language_hint": snapshot.get("language_hint"),
        "required_tools": plan.required_tools,
    }

    test_frameworks = plan.test_frameworks or [str(f) for f in snapshot.get("test_frameworks", [])]

    return WorkspaceSpec(
        workspace_id=workspace_id,
        repo_key=repo_key,
        repo_url=repo_url,
        local_path=local_path,
        language=plan.language,
        package_manager=plan.package_manager,
        package_manager_spec=plan.package_manager_spec,
        build_system=plan.build_system,
        install_command=plan.install_command,
        build_command=plan.build_command,
        test_command=plan.test_command,
        build_systems=list(snapshot.get("build_systems", [])),
        test_frameworks=test_frameworks,
        detected_build_files=list(snapshot.get("detected_build_files", [])),
        detected_test_paths=list(snapshot.get("detected_test_paths", [])),
        runnable_confidence=plan.runnable_confidence,
        notes=plan.notes,
        bootstrap_commands=plan.bootstrap.commands,
        bootstrap_required=plan.bootstrap.required,
        bootstrap_reason=plan.bootstrap.reason,
        bootstrap_category=plan.bootstrap.category,
        unsupported_reason=plan.unsupported_reason,
        command_inference_source=plan.command_inference_source,
        metadata=metadata,
    )


def build_workspaces(snapshots: Sequence[dict[str, object]]) -> list[WorkspaceSpec]:
    return [build_workspace(snapshot) for snapshot in snapshots]


def write_workspace_outputs(
    workspaces: Sequence[WorkspaceSpec],
    manifest_path: Path,
) -> None:
    write_jsonl(manifest_path, (workspace.as_dict() for workspace in workspaces))


def write_cgcs_seed_pool(
    workspaces: Sequence[WorkspaceSpec],
    output_path: Path,
    confidence_threshold: float,
) -> None:
    selected = (
        workspace.as_dict()
        for workspace in workspaces
        if workspace.metadata.get("has_tests")
        and workspace.metadata.get("has_build_files")
        and workspace.runnable_confidence >= confidence_threshold
    )
    write_jsonl(output_path, selected)
