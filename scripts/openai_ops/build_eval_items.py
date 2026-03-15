#!/usr/bin/env python3
"""Convert CGCS dataset rows into eval-ready JSONL items."""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Dict, Iterable, List
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import EvalItem, load_jsonl, write_jsonl, ensure_dir


def _iter_rows(input_dir: Path, split: str) -> Iterable[Dict]:
    path = input_dir / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Split '{split}' not found at {path}")
    return load_jsonl(path)


def build_eval_items(
    input_dir: Path,
    output_file: Path,
    split: str,
    max_items: int,
    seed: int,
) -> List[EvalItem]:
    rows = list(_iter_rows(input_dir, split))
    if seed >= 0:
        random.Random(seed).shuffle(rows)
    if max_items > 0:
        rows = rows[:max_items]
    eval_items: List[EvalItem] = []
    for row in rows:
        item = EvalItem(
            task_id=row.get("task_id", "unknown"),
            split=split,
            round_index=int(row.get("round_index", 0)),
            strategy=row.get("strategy"),
            repo_snapshot_sha256=row.get("repo_snapshot_sha256"),
            active_clause_id=row.get("active_clause_id"),
            contract_items=row.get("contract_items", {}),
            witnesses=row.get("witnesses") or [],
            regression_guard_ids=row.get("regression_guard_ids") or [],
            candidate_files=row.get("candidate_files") or [],
            context_snippets=row.get("context_snippets") or [],
            raw_edit_payload=str(row.get("raw_edit_payload") or ""),
            outcome=row.get("outcome_metrics") or {},
            row_quality=row.get("row_quality") or {},
            oracle_patch_present=row.get("oracle_patch_present"),
            source_paths=row.get("source_paths") or {},
        )
        eval_items.append(item)
    ensure_dir(output_file.parent)
    write_jsonl(output_file, [item.model_dump() for item in eval_items])
    return eval_items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build eval-ready JSONL items from CGCS traces.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/cgcs"))
    parser.add_argument("--output-file", type=Path, default=Path("openai_artifacts/eval_items.jsonl"))
    parser.add_argument("--split", type=str, default="train", choices=["train", "dev", "test"])
    parser.add_argument("--max-items", type=int, default=0, help="Limit number of rows (0=all).")
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    eval_items = build_eval_items(
        input_dir=args.input_dir,
        output_file=args.output_file,
        split=args.split,
        max_items=args.max_items,
        seed=args.seed,
    )
    print(f"Wrote {len(eval_items)} eval items to {args.output_file}")


if __name__ == "__main__":
    main()
