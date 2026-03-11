"""Dataclasses describing repository-backed benchmark tasks."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from src.config import PROJECT_ROOT


def _default_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


@dataclass
class RepoTaskSpec:
    """Repository-backed task specification."""

    task_id: str
    prompt: str
    repo_path: Path
    dataset: str = "local"
    dataset_source: str = "local_repo"
    task_type: str = "bugfix"
    difficulty: str = "M"
    language: str = "python"
    entry_point: str = "solve"
    build_commands: List[str] = field(default_factory=list)
    test_commands: List[str] = field(default_factory=lambda: ["pytest -q"])
    timeout_seconds: float = 120.0
    env: Dict[str, str] = field(default_factory=dict)
    target_files: List[str] = field(default_factory=list)
    apply_mode: str = "markers"
    markers: Dict[str, str] = field(default_factory=lambda: {"begin": "# BEGIN SOLUTION", "end": "# END SOLUTION"})
    file_context: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    heuristic_id: Optional[str] = None
    reportable: bool = False
    task_is_fixture: bool = False
    task_is_real_world: bool = False
    allow_file_creation: bool = False
    allowed_edit_paths: List[str] = field(default_factory=list)
    runtime_family: str = "python"
    package_manager: Optional[str] = None
    setup_commands: List[str] = field(default_factory=list)
    setup_timeout_seconds: Optional[float] = None
    requires_network: bool = False

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "RepoTaskSpec":
        repo_path_raw = str(payload.get("repo_path", ""))
        if not repo_path_raw:
            raise ValueError("repo_path is required for repo-backed tasks")
        repo_path = _default_path(repo_path_raw)
        markers = payload.get("markers") or {}
        if not isinstance(markers, dict):
            markers = {}
        env = payload.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        allowed_edit_paths = payload.get("allowed_edit_paths") or payload.get("editable_files") or []
        if isinstance(allowed_edit_paths, str):
            allowed_edit_paths = [allowed_edit_paths]
        allowed_paths_list = [str(path) for path in allowed_edit_paths] if allowed_edit_paths else []
        if not allowed_paths_list:
            fallback_paths = list(payload.get("target_files") or []) + list(payload.get("file_context") or [])
            deduped: List[str] = []
            for entry in fallback_paths:
                entry_str = str(entry)
                if entry_str and entry_str not in deduped:
                    deduped.append(entry_str)
            allowed_paths_list = deduped
        return RepoTaskSpec(
            task_id=str(payload.get("task_id") or payload.get("id")),
            prompt=str(payload.get("prompt") or payload.get("description") or ""),
            repo_path=repo_path,
            dataset=str(payload.get("dataset") or "local"),
            dataset_source=str(payload.get("dataset_source") or payload.get("source") or "local_repo"),
            task_type=str(payload.get("task_type") or payload.get("type") or "bugfix"),
            difficulty=str(payload.get("difficulty") or "M"),
            language=str(payload.get("language") or "python"),
            entry_point=str(payload.get("entry_point") or "solve"),
            build_commands=list(payload.get("build_commands") or []),
            test_commands=list(payload.get("test_commands") or ["pytest -q"]),
            timeout_seconds=float(payload.get("timeout_seconds") or 120.0),
            env={str(k): str(v) for k, v in env.items()},
            target_files=list(payload.get("target_files") or []),
            apply_mode=str(payload.get("apply_mode") or "markers"),
            markers={
                "begin": str(markers.get("begin") or "# BEGIN SOLUTION"),
                "end": str(markers.get("end") or "# END SOLUTION"),
            },
            file_context=list(payload.get("file_context") or payload.get("entry_files") or []),
            metadata=metadata,
            heuristic_id=str(payload.get("heuristic_id")) if payload.get("heuristic_id") else None,
            reportable=bool(payload.get("reportable", False)),
            task_is_fixture=bool(payload.get("task_is_fixture", False)),
            task_is_real_world=bool(payload.get("task_is_real_world", False)),
            allow_file_creation=bool(payload.get("allow_file_creation", False)),
            allowed_edit_paths=allowed_paths_list,
            runtime_family=str(payload.get("runtime_family") or payload.get("language") or "python"),
            package_manager=str(payload.get("package_manager")) if payload.get("package_manager") else None,
            setup_commands=[str(cmd) for cmd in payload.get("setup_commands", [])] if payload.get("setup_commands") else [],
            setup_timeout_seconds=float(payload.get("setup_timeout_seconds") or payload.get("setup_timeout_sec") or 0.0)
            if payload.get("setup_timeout_seconds") or payload.get("setup_timeout_sec")
            else None,
            requires_network=bool(payload.get("requires_network", False)),
        )

    def describe_context(self) -> str:
        file_list = ", ".join(self.file_context or self.target_files or [])
        repo_line = f"Repository: {self.repo_path.name}"
        files_line = f"Relevant files: {file_list or 'unspecified'}"
        return f"{self.prompt.strip()}\n\n{repo_line}\n{files_line}\nLanguage: {self.language}"

    def to_task_dict(self) -> Dict[str, object]:
        """Convert into the generic decomposition task dictionary."""

        metadata = dict(self.metadata)
        metadata.update(
            {
                "entry_point": self.entry_point,
                "repo_path": str(self.repo_path),
                "repo_target_files": self.target_files,
                "repo_file_context": self.file_context,
                "repo_dataset_source": self.dataset_source,
                "task_type": self.task_type,
                "difficulty": self.difficulty,
                "language": self.language,
                "tests": [],
                "real_repo_reportable": self.reportable,
                "task_is_fixture": self.task_is_fixture,
                "task_is_real_world": self.task_is_real_world,
                "repo_runtime_family": self.runtime_family,
                "repo_package_manager": self.package_manager,
                "repo_requires_network": self.requires_network,
                "repo_setup_commands": self.setup_commands,
                "repo_setup_timeout": self.setup_timeout_seconds,
            }
        )
        if self.heuristic_id:
            metadata["heuristic_id"] = self.heuristic_id
        return {
            "id": self.task_id,
            "problem_statement": self.describe_context(),
            "statement": self.describe_context(),
            "type": self.task_type,
            "difficulty": self.difficulty,
            "examples": [],
            "tests": [],
            "metadata": metadata,
        }
