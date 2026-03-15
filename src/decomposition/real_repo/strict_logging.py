"""Helpers for persisting strict per-round trace payloads into repo logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

STRICT_TRACE_FILENAME = "strict_round_traces.jsonl"
STRICT_TOP_LEVEL_FIELDS = {
    "contract_items",
    "active_clause_id",
    "active_clause",
    "regression_guard_ids",
    "witnesses",
    "raw_edit_payload",
    "candidate_files",
    "candidate_files_raw",
    "candidate_files_filtered",
    "row_quality",
    "payload_parse_ok",
    "payload_parse_error",
}


def _as_path(path_like: Optional[str | Path]) -> Optional[Path]:
    if not path_like:
        return None
    return Path(path_like)


def _safe_load_json(path: Path) -> Dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _merge_metadata(container: Dict[str, object], strict_payload: Dict[str, object]) -> None:
    metadata = container.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata.update(
            {
                "strict_trace": strict_payload,
                "contract_items": strict_payload.get("contract_items", metadata.get("contract_items")),
                "active_clause_id": strict_payload.get("active_clause_id", metadata.get("active_clause_id")),
                "regression_guard_ids": strict_payload.get("regression_guard_ids", metadata.get("regression_guard_ids")),
                "witnesses": strict_payload.get("witnesses", metadata.get("witnesses")),
                "row_quality": strict_payload.get("row_quality", metadata.get("row_quality")),
                "candidate_files": strict_payload.get("candidate_files", metadata.get("candidate_files")),
            }
        )


def persist_strict_trace_entry(
    *,
    logs_dir: Optional[str | Path],
    edit_log_path: Optional[str | Path],
    strict_entry: Dict[str, object],
) -> None:
    """Store a strict per-round payload on disk and merge it into the edit log."""

    if not strict_entry:
        return

    log_path = _as_path(edit_log_path)
    if log_path and log_path.exists():
        data = _safe_load_json(log_path)
        data["strict_trace"] = strict_entry
        for key in STRICT_TOP_LEVEL_FIELDS:
            if key in strict_entry:
                data[key] = strict_entry[key]
        _merge_metadata(data, strict_entry)
        _write_json(log_path, data)

    logs_root = _as_path(logs_dir)
    if logs_root:
        strict_path = logs_root / STRICT_TRACE_FILENAME
        _append_jsonl(strict_path, strict_entry)


__all__ = ["persist_strict_trace_entry", "STRICT_TRACE_FILENAME"]
