"""Convert raw dataset rows into canonical Topcoder tasks."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .test_parsing import TestSpec, extract_tests_from_row
from .types import TopcoderDatasetDescriptor

ID_COLUMNS = [
    "problem_id",
    "challengeid",
    "legacyid",
    "challenge_id",
    "task_id",
    "id",
    "round_id",
]
TITLE_COLUMNS = ["title", "name", "challenge_name", "challenge", "problem"]
STATEMENT_COLUMNS = [
    "problem_statement",
    "statement",
    "description",
    "details",
    "prompt",
    "requirements",
    "overview",
    "detailedrequirements",
]
CONSTRAINT_COLUMNS = ["constraints", "notes", "limits", "restrictions"]
TAG_COLUMNS = ["tags", "technologies", "tech", "stack", "platforms", "skills", "track", "category"]


def _normalize_key(key: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in key.strip().lower())


def _canonical_value(value: Any) -> Any:
    if isinstance(value, (str, int, float)):
        return value
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _canonical_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_canonical_value(item) for item in value]
    return str(value)


def _first_match(row: Dict[str, Any], candidates: Sequence[str]) -> Optional[str]:
    lower_map = {_normalize_key(k): k for k in row.keys()}
    for candidate in candidates:
        target = lower_map.get(candidate)
        if target:
            value = row[target]
            if value not in (None, "", []):
                return str(value).strip()
    return None


def _extract_statement(row: Dict[str, Any]) -> Optional[str]:
    lower_map = {_normalize_key(k): k for k in row.keys()}
    for candidate in STATEMENT_COLUMNS:
        column = lower_map.get(candidate)
        if column:
            value = row[column]
            if isinstance(value, str) and value.strip():
                return value.strip()
    for column in row:
        if "description" in _normalize_key(column) and isinstance(row[column], str):
            return row[column].strip()
    return None


def _extract_tags(row: Dict[str, Any]) -> List[str]:
    lower_map = {_normalize_key(k): k for k in row.keys()}
    tags: List[str] = []
    for candidate in TAG_COLUMNS:
        column = lower_map.get(candidate)
        if not column:
            continue
        value = row[column]
        if isinstance(value, str):
            tags.extend([part.strip() for part in value.split(",") if part.strip()])
        elif isinstance(value, (list, tuple, set)):
            tags.extend(str(item).strip() for item in value if str(item).strip())
    return sorted({tag for tag in tags if tag})


def row_to_task(row: Dict[str, Any], descriptor: TopcoderDatasetDescriptor, *, row_index: int) -> Optional[Dict[str, Any]]:
    statement = _extract_statement(row)
    if not statement:
        return None
    task_id = _first_match(row, ID_COLUMNS) or f"{descriptor.dataset_id}_{row_index:05d}"
    title = _first_match(row, TITLE_COLUMNS) or f"Topcoder Challenge {task_id}"
    difficulty = _first_match(row, ["difficulty", "level", "complexity"])
    constraints = _first_match(row, CONSTRAINT_COLUMNS)
    tags = _extract_tags(row)
    tests, source = extract_tests_from_row(row, statement)
    entry_point = _first_match(row, ["entry_point", "function", "method_name"])  # type: ignore[list-item]
    reference_solution = _first_match(row, ["reference_solution", "solution_code", "starter_code"])  # type: ignore[list-item]
    metadata: Dict[str, Any] = {
        "dataset_id": descriptor.dataset_id,
        "dataset_path": str(descriptor.path),
        "sheet_name": descriptor.sheet_name,
        "row_index": row_index,
        "raw": {str(k): _canonical_value(v) for k, v in row.items()},
    }
    if tests:
        metadata["tests"] = [spec.to_metadata_dict() for spec in tests]
        metadata["tests_source"] = source or "extracted"
        metadata.setdefault("entry_point", "solve")
    if entry_point:
        metadata["entry_point"] = entry_point
    if reference_solution:
        metadata["reference_solution"] = reference_solution
    task = {
        "id": str(task_id),
        "title": title,
        "problem_statement": statement,
        "statement": statement,
        "difficulty": difficulty,
        "constraints": constraints,
        "tags": tags,
        "metadata": metadata,
    }
    if tests:
        task["examples"] = [{"name": spec.name, "mode": spec.mode} for spec in tests]
    return task
