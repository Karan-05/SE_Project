#!/usr/bin/env python3
"""Poll a Batch job, download outputs, and normalize them."""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import (
    ensure_dir,
    get_openai_client,
    load_jsonl,
    normalize_response_record,
    summarize_batch_results,
    write_jsonl,
)


def _to_plain(payload: Any) -> Any:
    if isinstance(payload, dict):
        return payload
    model_dump = getattr(payload, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return payload


def read_metadata(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    batch_id = data.get("batch_id")
    if not batch_id:
        raise ValueError(f"No batch_id recorded in {path}")
    return batch_id


def download_file(client, file_id: str) -> str:
    try:
        content = client.files.content(file_id)  # type: ignore[attr-defined]
        return content.read().decode("utf-8")
    except AttributeError:
        return client.files.retrieve_content(file_id)


def normalize_error_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        row = _to_plain(row)
        if not isinstance(row, dict):
            row = {"raw": row}
        error = row.get("error") or {}
        if isinstance(error, dict):
            code = error.get("code") or error.get("type") or error.get("status") or "unknown"
            message = error.get("message") or error.get("detail") or json.dumps(error, ensure_ascii=False)
        else:
            code = "unknown"
            message = str(error)
        normalized.append(
            {
                "custom_id": row.get("custom_id") or row.get("id"),
                "status": row.get("status"),
                "error_code": code,
                "error_message": message,
                "raw": row,
            }
        )
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll and normalize OpenAI batch outputs.")
    parser.add_argument("--batch-id", type=str, default="")
    parser.add_argument("--metadata", type=Path, default=Path("openai_artifacts/batches/latest.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("openai_artifacts/normalized"))
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Alias for --metadata openai_artifacts/batches/latest.json",
    )
    args = parser.parse_args()
    if args.latest:
        args.metadata = Path("openai_artifacts/batches/latest.json")

    client = get_openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is required to poll a batch.")
    batch_id = args.batch_id or read_metadata(args.metadata)
    print(f"Polling batch {batch_id} ...")
    while True:
        batch = client.batches.retrieve(batch_id=batch_id)
        status = batch.status
        print(f"status={status}")
        if status in {"completed", "finalized", "failed", "expired", "cancelled"}:
            break
        time.sleep(args.interval)

    ensure_dir(args.output_dir)
    output_file_id = getattr(batch, "output_file_id", None)
    error_file_id = getattr(batch, "error_file_id", None)
    batch_status = getattr(batch, "status", "unknown")
    normalized_path = args.output_dir / f"{batch_id}.jsonl"
    normalized_errors_path = args.output_dir / f"{batch_id}_errors.jsonl"
    summary_csv_path = args.output_dir / f"{batch_id}_summary.csv"
    summary_json_path = args.output_dir / f"{batch_id}_summary.json"
    latest_jsonl = args.output_dir / "latest.jsonl"
    latest_summary_csv = args.output_dir / "latest_summary.csv"
    latest_errors = args.output_dir / "latest_errors.jsonl"
    raw_success_path = args.output_dir / f"{batch_id}_raw_success.jsonl"
    raw_error_path = args.output_dir / f"{batch_id}_raw_errors.jsonl"

    normalized_results = []
    if output_file_id:
        success_text = download_file(client, output_file_id)
        raw_success_path.write_text(success_text, encoding="utf-8")
        raw_rows = load_jsonl(raw_success_path)
        normalized_results = [normalize_response_record(row) for row in raw_rows]
        write_jsonl(normalized_path, [res.model_dump() for res in normalized_results])
        write_jsonl(latest_jsonl, [res.model_dump() for res in normalized_results])
    else:
        write_jsonl(normalized_path, [])
        latest_jsonl.write_text("", encoding="utf-8")

    normalized_error_rows: List[Dict[str, Any]] = []
    if error_file_id:
        error_text = download_file(client, error_file_id)
        raw_error_path.write_text(error_text, encoding="utf-8")
        raw_error_rows = load_jsonl(raw_error_path)
        normalized_error_rows = normalize_error_rows(raw_error_rows)
    elif getattr(batch, "errors", None):
        error_dump = _to_plain(getattr(batch, "errors"))
        serializable = error_dump
        if not isinstance(error_dump, (list, dict)):
            serializable = _to_plain(error_dump)
        raw_error_path.write_text(json.dumps(serializable, indent=2, default=str), encoding="utf-8")
        if isinstance(error_dump, list):
            normalized_error_rows = normalize_error_rows(error_dump)
        else:
            normalized_error_rows = normalize_error_rows([error_dump])
    write_jsonl(normalized_errors_path, normalized_error_rows)
    write_jsonl(latest_errors, normalized_error_rows)

    error_counts = Counter(row.get("error_code", "unknown") for row in normalized_error_rows)
    if normalized_results:
        print(f"Normalized outputs -> {normalized_path}")
    if normalized_error_rows:
        print(f"Captured {len(normalized_error_rows)} error rows -> {normalized_errors_path}")
        most_common = error_counts.most_common(5)
        print("Top batch errors:")
        for code, count in most_common:
            print(f"- {code}: {count}")
    summary = summarize_batch_results(
        normalized_results,
        error_count=len(normalized_error_rows),
        batch_status=str(batch_status),
    )
    summary_dict = summary.model_dump()
    summary_dict.update(
        {
            "batch_id": batch_id,
            "output_file_id": output_file_id,
            "error_file_id": error_file_id,
            "error_reasons": dict(error_counts),
        }
    )
    fieldnames = [
        "run_id",
        "grader",
        "total_requests",
        "success_count",
        "error_count",
        "malformed_json_count",
        "avg_output_tokens",
        "batch_status",
    ]
    with summary_csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({field: summary_dict.get(field) for field in fieldnames})
    summary_json_path.write_text(json.dumps(summary_dict, indent=2), encoding="utf-8")
    latest_summary_csv.write_text(summary_csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Summary -> {summary_csv_path}")


if __name__ == "__main__":
    main()
