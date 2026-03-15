#!/usr/bin/env python3
"""Prepare fine-tune-ready datasets from CGCS attempts."""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Dict, List
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import (
    FineTuneDatasetStats,
    ensure_dir,
    load_config,
    load_jsonl,
    write_jsonl,
    detect_task_overlap,
    validate_holdout_separation,
)


def qualifies(row: Dict, held_out: List[str]) -> bool:
    if row.get("task_id") in held_out:
        return False
    if not row.get("raw_edit_payload"):
        return False
    witnesses = row.get("witnesses") or []
    if not witnesses:
        return False
    outcome = row.get("outcome_metrics") or {}
    return float(outcome.get("pass_rate", 0.0)) >= 1.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare fine-tune datasets from CGCS outputs.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/cgcs"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/cgcs_finetune"))
    parser.add_argument("--research-config", type=Path, default=Path("configs/openai_ops/research.yaml"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--train-ratio", type=float, default=0.9)
    args = parser.parse_args()

    cfg = load_config(args.research_config)
    held_out = cfg.get("held_out", [])
    rows = []
    for split in ("train", "dev", "test"):
        split_path = args.input_dir / f"{split}.jsonl"
        if split_path.exists():
            rows.extend(load_jsonl(split_path))
    rows = [row for row in rows if qualifies(row, held_out)]

    random.Random(args.seed).shuffle(rows)
    cutoff = int(len(rows) * args.train_ratio)
    train_rows = rows[:cutoff]
    valid_rows = rows[cutoff:]

    ensure_dir(args.output_dir)
    train_path = args.output_dir / "train.jsonl"
    valid_path = args.output_dir / "valid.jsonl"
    write_jsonl(train_path, train_rows)
    write_jsonl(valid_path, valid_rows)

    train_tasks = [row.get("task_id", "") for row in train_rows]
    valid_tasks = [row.get("task_id", "") for row in valid_rows]
    stats = FineTuneDatasetStats(
        train_examples=len(train_rows),
        valid_examples=len(valid_rows),
        unique_tasks=len(set(train_tasks + valid_tasks)),
        unique_clause_types=len({row.get("active_clause_id") for row in rows if row.get("active_clause_id")}),
        witness_density=sum(len(row.get("witnesses") or []) for row in rows) / max(len(rows), 1),
        avg_payload_length=sum(len(row.get("raw_edit_payload") or "") for row in rows) / max(len(rows), 1),
        leakage_warnings=[
            *detect_task_overlap(train_tasks, valid_tasks),
            *validate_holdout_separation(train_tasks, set(held_out)),
        ],
    )
    stats_path = args.output_dir / "stats.json"
    stats_path.write_text(stats.model_dump_json(indent=2), encoding="utf-8")
    print(
        f"Prepared fine-tune splits -> train:{train_path} ({len(train_rows)} rows) "
        f"valid:{valid_path} ({len(valid_rows)} rows)"
    )
    if stats.leakage_warnings:
        print(f"[warn] Leakage detected: {stats.leakage_warnings}")


if __name__ == "__main__":
    main()
