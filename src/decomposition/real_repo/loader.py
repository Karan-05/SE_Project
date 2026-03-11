"""Load repo-backed tasks from JSON or JSONL sources."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from .task import RepoTaskSpec


def _read_lines(path: Path) -> Iterable[dict]:
    if path.suffix in {".jsonl", ".jsonlines"}:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                yield json.loads(stripped)
    else:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, list):
                yield from data
            else:
                yield data


def load_repo_tasks(path: Path) -> List[RepoTaskSpec]:
    """Load RepoTaskSpec objects from manifest files or snapshot directories."""

    if path.is_dir():
        return _load_from_directory(path)
    records = []
    for payload in _read_lines(path):
        records.append(RepoTaskSpec.from_dict(payload))
    return records


def _load_from_directory(root: Path) -> List[RepoTaskSpec]:
    records: List[RepoTaskSpec] = []
    manifest_files = sorted(root.rglob("task.json"))
    for manifest in manifest_files:
        with manifest.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        payload = dict(data)
        payload.setdefault("task_id", manifest.parent.name)
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            patch_ref = metadata.get("ground_truth_patch")
            if patch_ref:
                patch_path = Path(patch_ref)
                if not patch_path.is_absolute():
                    metadata["ground_truth_patch"] = str((manifest.parent / patch_path).resolve())
        repo_path = payload.get("repo_path")
        if not repo_path:
            candidate = payload.get("repo_dir") or payload.get("repo_rel_path") or "."
            payload["repo_path"] = str((manifest.parent / candidate).resolve())
        payload.setdefault("dataset_source", manifest.parent.parent.name if manifest.parent.parent else "local_repo")
        records.append(RepoTaskSpec.from_dict(payload))
    return records
