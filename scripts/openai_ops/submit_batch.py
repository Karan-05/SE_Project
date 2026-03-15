#!/usr/bin/env python3
"""Submit an OpenAI Batch job built from request JSONL."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import ensure_dir, get_openai_client, utc_timestamp


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a Responses API batch job.")
    parser.add_argument("--requests-file", type=Path, default=Path("openai_artifacts/batch_requests.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("openai_artifacts/batches"))
    parser.add_argument("--endpoint", type=str, default="/v1/responses")
    parser.add_argument("--completion-window", type=str, default="24h")
    args = parser.parse_args()

    client = get_openai_client()
    ensure_dir(args.output_dir)
    timestamp = utc_timestamp()
    metadata_path = args.output_dir / f"{timestamp}.json"
    latest_path = args.output_dir / "latest.json"
    if client is None:
        payload = {
            "error": "OPENAI_API_KEY missing",
            "requests_file": str(args.requests_file),
            "timestamp": timestamp,
        }
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("No OpenAI credentials detected; wrote placeholder metadata.")
        return

    with args.requests_file.open("rb") as handle:
        input_file = client.files.create(file=handle, purpose="batch")
    batch = client.batches.create(
        input_file_id=input_file.id,
        endpoint=args.endpoint,
        completion_window=args.completion_window,
    )
    request_counts = getattr(batch, "request_counts", None)
    if isinstance(request_counts, dict):
        total_requests = request_counts.get("total", "unknown")
    else:
        total_requests = getattr(request_counts, "total", "unknown")
    metadata = {
        "batch_id": batch.id,
        "input_file_id": input_file.id,
        "endpoint": args.endpoint,
        "completion_window": args.completion_window,
        "created_at": batch.created_at,
        "request_count": total_requests,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Submitted batch {batch.id}; metadata saved to {metadata_path}")


if __name__ == "__main__":
    main()
