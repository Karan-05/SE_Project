"""CSV loader with basic normalization."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional


def _clean_value(value: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def load_csv_records(path: Path, *, max_records: Optional[int] = None) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            cleaned = {str(k).strip(): _clean_value(v) for k, v in row.items()}
            if not any(value not in (None, "") for value in cleaned.values()):
                continue
            records.append(cleaned)
            if max_records and len(records) >= max_records:
                break
    return records
