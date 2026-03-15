#!/usr/bin/env python3
"""Inspect CGCS dataset quality, completeness, and rejection reasons."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.decomposition.openai_ops import load_jsonl  # noqa: E402


def load_rows(input_dir: Path, split: str) -> List[Dict]:
    path = input_dir / f"{split}.jsonl"
    if not path.exists():
        return []
    return load_jsonl(path)


def summarize_rows(rows: List[Dict]) -> Dict[str, float]:
    stats = Counter()
    total = len(rows)
    for row in rows:
        if row.get("active_clause_id"):
            stats["active_clause_present"] += 1
        contract_items = row.get("contract_items")
        if isinstance(contract_items, list) and contract_items:
            stats["contract_items_present"] += 1
        elif isinstance(contract_items, dict) and contract_items:
            stats["contract_items_present"] += 1
        witnesses = row.get("witnesses") or []
        if witnesses:
            stats["witnesses_present"] += 1
        if row.get("raw_edit_payload"):
            stats["payload_present"] += 1
        quality = row.get("row_quality") or {}
        if quality.get("contract_quality") == "weak":
            stats["weak_contract_rows"] += 1
    return {
        "total": total,
        "active_clause_pct": percentage(stats["active_clause_present"], total),
        "contract_items_pct": percentage(stats["contract_items_present"], total),
        "witness_pct": percentage(stats["witnesses_present"], total),
        "payload_pct": percentage(stats["payload_present"], total),
        "weak_contract_pct": percentage(stats["weak_contract_rows"], total),
    }


def percentage(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug CGCS dataset quality.")
    parser.add_argument("--input-dir", type=Path, default=Path("data/cgcs"))
    parser.add_argument("--top-n", type=int, default=3, help="Number of rejected samples to print.")
    args = parser.parse_args()

    train = load_rows(args.input_dir, "train")
    dev = load_rows(args.input_dir, "dev")
    test = load_rows(args.input_dir, "test")
    rejected = load_rows(args.input_dir, "rejected")

    usable = train + dev + test
    stats = summarize_rows(usable)
    print("=== CGCS Dataset Quality Summary ===")
    print(f"Total usable rows: {stats['total']}")
    print(f"Active clause present: {stats['active_clause_pct']}%")
    print(f"Contract items present: {stats['contract_items_pct']}%")
    print(f"Witness coverage: {stats['witness_pct']}%")
    print(f"Raw payload coverage: {stats['payload_pct']}%")
    print(f"Weak contract rows: {stats['weak_contract_pct']}%")

    rejection_counts = Counter()
    for row in rejected:
        for reason in row.get("row_errors") or []:
            rejection_counts[reason] += 1
    print("\n=== Top Rejection Reasons ===")
    for reason, count in rejection_counts.most_common(10):
        print(f"- {reason}: {count}")

    print("\n=== Sample Rejected Rows ===")
    for row in rejected[: args.top_n]:
        sample = {
            "task_id": row.get("task_id"),
            "round_index": row.get("round_index"),
            "split": row.get("split"),
            "strategy": row.get("strategy"),
            "row_errors": row.get("row_errors"),
            "row_quality": row.get("row_quality"),
        }
        print(json.dumps(sample, indent=2))


if __name__ == "__main__":
    main()
