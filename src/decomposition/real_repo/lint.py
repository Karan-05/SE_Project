"""Linting policies for repository edit payloads prior to application."""
from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Sequence

from src.decomposition.real_repo.edit_batch import RepoEditBatch
from src.decomposition.real_repo.task import RepoTaskSpec


def _normalize_path(path: str) -> str:
    return Path(path).as_posix()


def _glob_match(path: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/")
    regex_parts: List[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                follow_slash = i + 2 < len(pattern) and pattern[i + 2] == "/"
                if follow_slash:
                    regex_parts.append("(?:.*/)?")
                    i += 3
                else:
                    regex_parts.append(".*")
                    i += 2
            else:
                regex_parts.append("[^/]*")
                i += 1
        elif char == "?":
            regex_parts.append("[^/]")
            i += 1
        else:
            regex_parts.append(re.escape(char))
            i += 1
    regex = "^" + "".join(regex_parts) + "$"
    return bool(re.match(regex, path))


def _matches_allowed(path: str, patterns: Sequence[str]) -> bool:
    normalized = _normalize_path(path)
    path_obj = PurePosixPath(normalized)
    for pattern in patterns:
        normalized_pattern = _normalize_path(pattern)
        if normalized_pattern in {"*", "**"}:
            return True
        if fnmatch(normalized, normalized_pattern):
            return True
        if path_obj.match(normalized_pattern):
            return True
        if _glob_match(normalized, normalized_pattern):
            return True
        if normalized.startswith(normalized_pattern.rstrip("/") + "/"):
            return True
    return False


def _expected_targets(task_spec: RepoTaskSpec, metadata: Dict[str, object]) -> List[str]:
    order = [
        metadata.get("implementation_target_files"),
        metadata.get("expected_files"),
        metadata.get("repo_target_files"),
        task_spec.target_files,
    ]
    for candidate in order:
        if not candidate:
            continue
        if isinstance(candidate, str):
            return [candidate]
        if isinstance(candidate, Iterable):
            return [str(entry) for entry in candidate if str(entry)]
    return []


def _multi_file_required(metadata: Dict[str, object], expected: Sequence[str]) -> bool:
    if metadata.get("multi_file_localization"):
        return True
    return len(set(expected)) > 1


def _collect_skipped_targets(batch: RepoEditBatch) -> List[str]:
    skipped = batch.metadata.get("skipped_targets")
    if isinstance(skipped, dict):
        return [str(key) for key in skipped.keys()]
    if isinstance(skipped, list):
        return [str(entry) for entry in skipped]
    if isinstance(skipped, str):
        return [skipped]
    return []


def _is_test_path(path: str) -> bool:
    normalized = _normalize_path(path).lower()
    if any(segment in {"test", "tests", "__tests__"} for segment in normalized.split("/")):
        return True
    if normalized.endswith((".spec.js", ".spec.ts", ".spec.tsx", ".spec.jsx", ".test.js", ".test.ts", ".test.tsx", ".test.jsx", ".spec.py", ".test.py")):
        return True
    return False


def lint_repo_edit_payload(
    batch: RepoEditBatch,
    task_spec: RepoTaskSpec,
    metadata: Dict[str, object],
) -> List[str]:
    """Return lint violations for the given payload."""

    errors: List[str] = []
    allowed_patterns = task_spec.allowed_edit_paths or metadata.get("allowed_edit_paths") or []
    if isinstance(allowed_patterns, str):
        allowed_patterns = [allowed_patterns]
    edited_paths = [edit.path for edit in batch.edits]

    if allowed_patterns:
        for path in edited_paths:
            if not _matches_allowed(path, allowed_patterns):
                errors.append(f"edit path '{path}' outside allowed scope {allowed_patterns}")

    expected_targets = _expected_targets(task_spec, metadata)
    multi_required = _multi_file_required(metadata, expected_targets)
    edited_set = {_normalize_path(path) for path in edited_paths}
    expected_set = {_normalize_path(path) for path in expected_targets}

    if multi_required and expected_set:
        missing = expected_set - edited_set
        if missing:
            skipped = {_normalize_path(path) for path in _collect_skipped_targets(batch)}
            if not skipped or not missing <= skipped:
                errors.append(
                    "multi-file target requires edits for "
                    f"{sorted(expected_set)}; missing {sorted(missing)} without skipped_targets rationale"
                )

    allow_test_edits = bool(metadata.get("allow_test_edits"))
    if not allow_test_edits:
        for path in edited_paths:
            if _is_test_path(path):
                errors.append(f"test edits are prohibited: {path}")

    return errors


__all__ = ["lint_repo_edit_payload"]
