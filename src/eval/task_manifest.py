"""Task manifest helpers for the real evaluation harness."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, MutableMapping, Optional, Sequence

import json

from src.decomposition.interfaces import DecompositionContext


def _ensure_list(obj) -> List[Dict]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, MutableMapping):
        # Some task exports store tasks under a top-level "tasks" key.
        tasks = obj.get("tasks")
        if isinstance(tasks, list):
            return tasks
        return [obj]
    raise ValueError("Unsupported task manifest structure.")


@dataclass
class TaskSpec:
    """Canonical task representation consumed by the real evaluation runner."""

    task_id: str
    title: str
    statement: str
    category: str
    dataset_id: str
    source_path: str
    tests: List[Dict[str, object]] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)

    @staticmethod
    def from_payload(payload: Dict[str, object], dataset_id: str, source_path: str, default_category: str = "algo_coding") -> "TaskSpec":
        task_id = str(payload.get("id") or payload.get("task_id") or "")
        if not task_id:
            raise ValueError(f"Task payload is missing an id field: {payload.keys()}")
        title = str(payload.get("title") or payload.get("name") or task_id)
        statement = str(
            payload.get("problem_statement")
            or payload.get("statement")
            or payload.get("description")
            or title
        )
        metadata = dict(payload)
        tests_raw = metadata.get("tests") or []
        if isinstance(tests_raw, list):
            tests = [t for t in tests_raw if isinstance(t, dict)]
        else:
            tests = []
        category = str(metadata.get("category") or metadata.get("task_type") or default_category)
        return TaskSpec(
            task_id=task_id,
            title=title,
            statement=statement,
            category=category,
            dataset_id=dataset_id,
            source_path=source_path,
            tests=tests,
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.task_id,
            "title": self.title,
            "problem_statement": self.statement,
            "category": self.category,
            "dataset_id": self.dataset_id,
            "source_path": self.source_path,
            "metadata": self.metadata,
        }

    def to_context(self) -> DecompositionContext:
        """Build a decomposition context for downstream strategy execution."""

        metadata = dict(self.metadata)
        tags = metadata.get("tags")
        if not tags and metadata.get("type"):
            tags = [metadata["type"]]
        nearest_neighbors = metadata.get("neighbors") or []
        if not isinstance(nearest_neighbors, list):
            nearest_neighbors = []
        return DecompositionContext(
            task_id=self.task_id,
            problem_statement=self.statement,
            tags=tags or [],
            difficulty=metadata.get("difficulty"),
            constraints=metadata.get("constraints"),
            examples=metadata.get("examples", []),
            metadata=metadata,
            nearest_neighbors=nearest_neighbors,
            historical_stats=metadata.get("historical_stats"),
        )


@dataclass
class TaskManifest:
    """Container that exposes iteration/filtering helpers for TaskSpec lists."""

    tasks: List[TaskSpec]
    label: str
    source_path: Path

    def __iter__(self) -> Iterator[TaskSpec]:
        yield from self.tasks

    def filter(self, task_ids: Optional[Sequence[str]] = None, limit: Optional[int] = None) -> "TaskManifest":
        subset: Iterable[TaskSpec] = self.tasks
        if task_ids:
            wanted = {tid for tid in task_ids}
            subset = [task for task in subset if task.task_id in wanted]
        if limit is not None:
            subset = list(subset)[:limit]
        return TaskManifest(list(subset), self.label, self.source_path)

    @classmethod
    def from_path(cls, path: Path, *, dataset_id: Optional[str] = None, task_ids: Optional[Sequence[str]] = None) -> "TaskManifest":
        payload = json.loads(path.read_text(encoding="utf-8"))
        tasks_raw = _ensure_list(payload)
        specs: List[TaskSpec] = []
        dataset_hint = dataset_id or path.stem
        for raw in tasks_raw:
            if not isinstance(raw, dict):
                continue
            spec = TaskSpec.from_payload(raw, dataset_hint, str(path))
            specs.append(spec)
        manifest = TaskManifest(specs, label=dataset_hint, source_path=path)
        if task_ids:
            manifest = manifest.filter(task_ids=task_ids)
        return manifest
