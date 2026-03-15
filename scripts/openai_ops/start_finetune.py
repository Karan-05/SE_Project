#!/usr/bin/env python3
"""Start a guarded fine-tuning job for CGCS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import ensure_dir, get_openai_client, load_jsonl, utc_timestamp
from src.decomposition.openai_ops.leakage import detect_task_overlap


def read_tasks(path: Path) -> list[str]:
    return [row.get("task_id", "") for row in load_jsonl(path)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch a fine-tuning job once safety checks pass.")
    parser.add_argument("--train", type=Path, default=Path("data/cgcs_finetune/train.jsonl"))
    parser.add_argument("--valid", type=Path, default=Path("data/cgcs_finetune/valid.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("openai_artifacts/fine_tunes"))
    parser.add_argument("--model", type=str, default="gpt-4o-mini")
    args = parser.parse_args()

    ensure_dir(args.output_dir)
    train_rows = load_jsonl(args.train)
    valid_rows = load_jsonl(args.valid)
    if len(train_rows) < 50 or len(valid_rows) < 10:
        raise RuntimeError("Dataset too small for fine-tuning.")
    overlap = detect_task_overlap(read_tasks(args.train), read_tasks(args.valid))
    if overlap:
        raise RuntimeError(f"Train/valid leakage detected: {overlap}")

    client = get_openai_client()
    timestamp = utc_timestamp()
    meta_path = args.output_dir / f"{timestamp}.json"
    if client is None:
        meta_path.write_text(
            json.dumps({"error": "OPENAI_API_KEY missing", "train": str(args.train), "valid": str(args.valid)}, indent=2),
            encoding="utf-8",
        )
        print("Skipped fine-tuning job because no OpenAI credentials were provided.")
        return

    with args.train.open("rb") as handle:
        train_file = client.files.create(file=handle, purpose="fine-tune")
    with args.valid.open("rb") as handle:
        valid_file = client.files.create(file=handle, purpose="fine-tune")
    job = client.fine_tuning.jobs.create(
        model=args.model,
        training_file=train_file.id,
        validation_file=valid_file.id,
    )
    meta_path.write_text(
        json.dumps(
            {
                "job_id": job.id,
                "model": args.model,
                "train_file": train_file.id,
                "valid_file": valid_file.id,
                "created_at": job.created_at,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Fine-tuning job {job.id} submitted; metadata -> {meta_path}")


if __name__ == "__main__":
    main()
