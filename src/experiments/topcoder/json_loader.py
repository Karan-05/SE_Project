"""JSON/JSONL loader with mild normalization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def _flatten_payload(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "records", "rows", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [payload]
    return []


def _load_json_lines(path: Path, max_records: Optional[int]) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
            if max_records and len(records) >= max_records:
                break
    return records


def load_json_records(path: Path, *, max_records: Optional[int] = None) -> List[Dict[str, object]]:
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        records = _load_json_lines(path, max_records)
    else:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        records = _flatten_payload(payload)
    if max_records is not None:
        return records[:max_records]
    return records
