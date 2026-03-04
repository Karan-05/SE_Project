"""Dataset discovery utilities for Topcoder problem tables."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.config import PROJECT_ROOT

from . import csv_loader, excel_loader, json_loader, task_conversion
from .types import TopcoderDatasetDescriptor

logger = logging.getLogger(__name__)

CANDIDATE_DIRS = [
    "data",
    "datasets",
    "challenge_data",
    "resources",
    "artifacts",
    "analysis",
    "experiments",
    "reports",
]

SUPPORTED_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".jsonl": "json",
    ".xlsx": "excel",
    ".xls": "excel",
    ".parquet": "parquet",
}

IDENTIFIER_HINTS = ["challengeid", "challenge_id", "legacyid", "problem_id", "id", "round_id"]
TITLE_HINTS = ["title", "name", "challenge", "problem", "task"]
STATEMENT_HINTS = ["statement", "description", "details", "prompt", "requirements", "overview"]
SCORING_HINTS = ["tests", "examples", "sample", "constraints", "tags", "technologies"]


def _normalize_column(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())


def _score_columns(columns: Iterable[str]) -> Tuple[int, List[str]]:
    normalized = [_normalize_column(col) for col in columns if col]
    id_hits = [col for col in normalized if any(hint in col for hint in IDENTIFIER_HINTS)]
    title_hits = [col for col in normalized if any(hint in col for hint in TITLE_HINTS)]
    statement_hits = [col for col in normalized if any(hint in col for hint in STATEMENT_HINTS)]
    bonus_hits = [col for col in normalized if any(hint in col for hint in SCORING_HINTS)]
    score = 0
    if id_hits:
        score += 2
    if title_hits:
        score += 1
    if statement_hits:
        score += 2
    if bonus_hits:
        score += 1
    interesting_cols = sorted(set(id_hits + title_hits + statement_hits + bonus_hits))
    return score, interesting_cols


def _iter_candidate_files(search_roots: Sequence[Path]) -> Iterable[Path]:
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield path


def _sheet_descriptors(path: Path) -> List[Tuple[str, Optional[str]]]:
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return [(path.stem, None)]
    sheet_names = excel_loader.available_sheets(path)
    if not sheet_names:
        return [(path.stem, None)]
    descriptors: List[Tuple[str, Optional[str]]] = []
    for sheet in sheet_names:
        descriptors.append((f"{path.stem}_{_normalize_column(sheet)}", sheet))
    return descriptors


def _preview_records(path: Path, file_type: str, sheet_name: Optional[str]) -> List[Dict[str, object]]:
    max_records = 25
    if file_type == "csv":
        return csv_loader.load_csv_records(path, max_records=max_records)
    if file_type == "json":
        return json_loader.load_json_records(path, max_records=max_records)
    if file_type == "excel":
        return excel_loader.load_excel_records(path, sheet_name=sheet_name, max_records=max_records)
    if file_type == "parquet":
        logger.warning("Skipping parquet preview for %s (pyarrow unavailable in sandbox)", path)
        return []
    return []


def _estimate_count(records: List[Dict[str, object]]) -> int:
    return len(records)


def _build_descriptor(path: Path, file_type: str, sheet_name: Optional[str], columns: List[str], approx: int) -> TopcoderDatasetDescriptor:
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = path
    dataset_name = f"{rel.as_posix()}".replace("/", "_")
    if sheet_name:
        dataset_name = f"{dataset_name}_{_normalize_column(sheet_name)}"
    return TopcoderDatasetDescriptor(
        dataset_id=dataset_name,
        path=path,
        file_type=file_type,
        sheet_name=sheet_name,
        task_columns=columns,
        approx_records=approx,
    )


def discover_topcoder_datasets(
    root: Path | None = None,
    search_paths: Optional[Sequence[Path]] = None,
    *,
    limit: Optional[int] = None,
) -> List[TopcoderDatasetDescriptor]:
    """Discover candidate datasets containing Topcoder problems."""

    base = root or PROJECT_ROOT
    roots = list(search_paths or [])
    if not roots:
        roots = [base / name for name in CANDIDATE_DIRS]
    seen: Dict[Tuple[Path, Optional[str]], TopcoderDatasetDescriptor] = {}
    for candidate in _iter_candidate_files(roots):
        file_type = SUPPORTED_EXTENSIONS.get(candidate.suffix.lower())
        if not file_type:
            continue
        for dataset_suffix, sheet_name in _sheet_descriptors(candidate):
            preview = _preview_records(candidate, file_type, sheet_name)
            if not preview:
                continue
            sample_columns = sorted({str(col) for row in preview for col in row.keys() if col})
            score, interesting = _score_columns(sample_columns)
            if score < 3:
                continue
            descriptor = _build_descriptor(candidate, file_type, sheet_name, interesting, _estimate_count(preview))
            seen[(candidate, sheet_name)] = descriptor
            logger.debug("Discovered dataset %s (score=%s columns=%s)", descriptor.dataset_id, score, interesting)
            if limit and len(seen) >= limit:
                break
        if limit and len(seen) >= limit:
            break
    return sorted(seen.values(), key=lambda d: d.dataset_id)


def load_tasks_from_dataset(descriptor: TopcoderDatasetDescriptor, *, max_tasks: Optional[int] = None) -> List[Dict[str, object]]:
    """Load canonical tasks from a dataset descriptor."""

    file_type = descriptor.file_type
    if file_type == "csv":
        records = csv_loader.load_csv_records(descriptor.path)
    elif file_type == "json":
        records = json_loader.load_json_records(descriptor.path)
    elif file_type == "excel":
        records = excel_loader.load_excel_records(descriptor.path, sheet_name=descriptor.sheet_name)
    elif file_type == "parquet":
        try:
            import pandas as pd  # type: ignore
        except ImportError:  # pragma: no cover
            logger.warning("Skipping parquet dataset %s because pandas is unavailable", descriptor.path)
            return []
        df = pd.read_parquet(descriptor.path)  # type: ignore[attr-defined]
        df = df.where(pd.notna(df), None)  # type: ignore[attr-defined]
        records = df.to_dict(orient="records")
    else:
        logger.warning("Unsupported dataset type %s for %s", file_type, descriptor.path)
        return []

    tasks: List[Dict[str, object]] = []
    for idx, row in enumerate(records):
        task = task_conversion.row_to_task(row, descriptor, row_index=idx)
        if not task:
            continue
        tasks.append(task)
        if max_tasks and len(tasks) >= max_tasks:
            break
    return tasks
